"""
Scraper Transfermarkt CARRIÈRE PAR JOUEUR via API ceapi.

Endpoint :
    GET https://www.transfermarkt.com/ceapi/performance-game/{player_id}

Caractéristiques :
- 1 seul GET par joueur, JSON ~600KB-3.5MB selon longueur de carrière.
- Pas d'auth, pas de cookie.
- Granularité MATCH : tous les matchs de toute la carrière du joueur en 1
  réponse, y compris matchs où il n'a pas joué (status='not in squad' /
  'injured' / 'absent' / 'in squad') et matchs en sélection nationale.

Pipeline :
  1) Lecture de la liste des player_id depuis un CSV source produit par
     tm_league_scraper.py (ex: mar1.csv, filtré sur la saison en cours pour
     ne taper que les joueurs ACTIFS).
  2) GET ceapi pour chaque player_id (3 workers en parallèle, pause
     polie 0.3-0.6s entre 2 requêtes d'un même worker).
  3) Agrégation en 3 grains :
       - summary : 1 ligne par joueur (totaux carrière complète)
       - career  : 1 ligne par (player, season, competition, club)
       - matches : 10 derniers matchs OU 3 derniers mois (max des 2),
                   avec participation_state natif TM (played/injured/...)
  4) Sortie : 3 CSV dans live/data/tm_career/{league}_{summary|career|matches}.csv

Note : on conserve les matchs en sélection nationale (isNationalGame=true)
dans les 3 fichiers, marqués via la colonne is_national_team.

Note 2 : les stats détaillées (tirs total, tirs cadrés) ne sont remontées
par TM que pour les saisons récentes (~2010+) et certains championnats.
Sur les saisons antérieures les colonnes shots_* seront 0/null.

Usage CLI :
    python tm_player_career.py --league mar1
    python tm_player_career.py --league mar1 --test --test-n 5
    python tm_player_career.py --player-ids 199704,776215
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

# ============================================================
# Config
# ============================================================
BASE_URL = "https://www.transfermarkt.com"
CEAPI_PATH = "/ceapi/performance-game/{pid}"

TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.transfermarkt.com/",
    "Accept-Encoding": "gzip",
}

TIMEOUT = 30
PAUSE_MIN = 0.30
PAUSE_MAX = 0.60
DEFAULT_WORKERS = 3

# Fenêtre matches récents : max(N derniers matchs, M derniers mois)
RECENT_MATCHES_N = 10
RECENT_MATCHES_DAYS = 90  # 3 mois

# ============================================================
# HTTP
# ============================================================
_print_lock = threading.Lock()


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _polite_pause() -> None:
    time.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))


def _fetch_json(
    url: str, timeout: int = TIMEOUT
) -> tuple[dict | None, int | None, str | None]:
    """GET JSON avec gzip + headers Chrome.

    Returns (parsed_json, status, error). En cas de succès : (dict, 200, None).
    """
    req = urllib.request.Request(url, headers=TM_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            text = data.decode("utf-8", errors="replace")
            try:
                return json.loads(text), r.status, None
            except json.JSONDecodeError as e:
                return None, r.status, f"JSON decode: {e}"
    except urllib.error.HTTPError as e:
        return None, e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, None, f"URL error: {e.reason}"
    except TimeoutError:
        return None, None, "timeout"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def fetch_player_career(player_id: str) -> dict | None:
    """GET ceapi/performance-game/{pid}. Retourne le dict 'data' ou None."""
    url = BASE_URL + CEAPI_PATH.format(pid=player_id)
    payload, status, err = _fetch_json(url)
    if payload is None:
        _log(f"   ! échec player_id={player_id}: status={status} err={err}")
        return None
    if not payload.get("success"):
        _log(f"   ! API non-success player_id={player_id}: {payload.get('message')}")
        return None
    return payload.get("data")


# ============================================================
# Helpers d'agrégation
# ============================================================
def _safe_int(v) -> int:
    """None / '' / non-numérique → 0."""
    if v is None or v == "":
        return 0
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return 0


def _is_played(state: str | None) -> bool:
    """True ssi le joueur est entré sur le terrain ce match."""
    return state == "played"


def _extract_match_row(p: dict, player_id: str, player_name: str) -> dict:
    """Aplatit 1 entrée 'performance' en dict tabulaire pour le CSV matches."""
    gi = p.get("gameInformation", {}) or {}
    ci = p.get("clubsInformation", {}) or {}
    club = ci.get("club", {}) or {}
    opp = ci.get("opponent", {}) or {}
    st = p.get("statistics", {}) or {}
    gen = st.get("generalStatistics", {}) or {}
    goal = st.get("goalStatistics", {}) or {}
    pt = st.get("playingTimeStatistics", {}) or {}
    card = st.get("cardStatistics", {}) or {}

    date = (gi.get("date") or {}).get("dateTimeUTC") or ""
    yc = card.get("yellowCard") or {}
    sub_in = pt.get("substitutedIn") or {}
    sub_out = pt.get("substitutedOut") or {}

    return {
        "player_id": player_id,
        "player_name": player_name,
        "game_date_utc": date,
        "season": gi.get("seasonId"),
        "competition_id": gi.get("competitionId") or "",
        "competition_type_id": gi.get("competitionTypeId"),
        "is_national_team": bool(gi.get("isNationalGame")),
        "game_id": gi.get("gameId"),
        "game_day": gi.get("gameDay"),
        "club_id": club.get("clubId") or "",
        "venue": club.get("venue") or "",
        "opponent_club_id": opp.get("clubId") or "",
        "club_goals": _safe_int(club.get("goalsTotal")),
        "opponent_goals": _safe_int(club.get("opponentGoalsTotal")),
        "participation_state": gen.get("participationState") or "",
        "shirt_number": gen.get("shirtNumber"),
        "position_id": gen.get("positionId"),
        "is_captain": bool(gen.get("isCaptain")),
        "played_minutes": _safe_int(pt.get("playedMinutes")),
        "goals": _safe_int(goal.get("goalsScoredTotal")),
        "assists": _safe_int(goal.get("assists")),
        "shots_total": _safe_int(goal.get("scoringAttempts")),
        "shots_on_goal": _safe_int(goal.get("scoringAttemptsOnGoal")),
        "shots_off_goal": _safe_int(goal.get("scoringAttemptsOffGoal")),
        "shots_blocked": _safe_int(goal.get("scoringAttemptsBlocked")),
        "yellow_card_minute": yc.get("minute"),
        "substituted_in_minute": sub_in.get("minute"),
        "substituted_out_minute": sub_out.get("minute"),
        "injury_id": gen.get("injuryId") or 0,
        "absence_id": gen.get("absenceId") or 0,
    }


def aggregate_player(
    player_id: str,
    player_name: str,
    player_meta: dict,
    data: dict,
) -> tuple[dict, list[dict], list[dict], set[str]]:
    """Depuis le payload ceapi d'un joueur, retourne (summary, career, matches, comp_ids).

    - summary : 1 dict (1 ligne)
    - career  : list[dict] (1 ligne par season×competition×club)
    - matches : list[dict] (10 derniers matchs OU 3 derniers mois, max des 2)
    - comp_ids : set des competition_id rencontrés (pour rapport mapping)
    """
    perfs = (data or {}).get("performance", []) or []

    # Toutes les lignes plates en mémoire
    flat_all = [_extract_match_row(p, player_id, player_name) for p in perfs]
    comp_ids: set[str] = {r["competition_id"] for r in flat_all if r["competition_id"]}

    # ============================================================
    # CAREER (1 ligne par season × competition × club)
    # ============================================================
    career_buckets: dict[tuple, dict] = defaultdict(lambda: {
        "matches_total": 0,
        "matches_played": 0,
        "matches_injured_absent": 0,
        "minutes": 0,
        "goals": 0,
        "assists": 0,
        "shots_total": 0,
        "shots_on_goal": 0,
        "yellow_cards": 0,
    })
    for r in flat_all:
        key = (
            r["season"],
            r["competition_id"],
            r["club_id"],
            r["is_national_team"],
        )
        b = career_buckets[key]
        b["matches_total"] += 1
        if _is_played(r["participation_state"]):
            b["matches_played"] += 1
            b["minutes"] += r["played_minutes"]
            b["goals"] += r["goals"]
            b["assists"] += r["assists"]
            b["shots_total"] += r["shots_total"]
            b["shots_on_goal"] += r["shots_on_goal"]
            if r["yellow_card_minute"] is not None:
                b["yellow_cards"] += 1
        elif r["participation_state"] in ("injured", "absent"):
            b["matches_injured_absent"] += 1

    career_rows: list[dict] = []
    for (season, comp, club, is_nat), b in career_buckets.items():
        career_rows.append({
            "player_id": player_id,
            "player_name": player_name,
            "season": season,
            "competition_id": comp,
            "club_id": club,
            "is_national_team": is_nat,
            **b,
        })
    career_rows.sort(
        key=lambda r: (r["season"] or 0, r["competition_id"], r["club_id"]),
        reverse=True,
    )

    # ============================================================
    # SUMMARY (totaux carrière, 1 ligne)
    # ============================================================
    played_rows = [r for r in flat_all if _is_played(r["participation_state"])]
    seasons_set = {r["season"] for r in flat_all if r["season"]}
    clubs_set = {r["club_id"] for r in flat_all if r["club_id"] and not r["is_national_team"]}
    summary = {
        "player_id": player_id,
        "player_name": player_name,
        # Métadonnées venant du CSV source (snapshot de l'effectif courant)
        "current_team_id": player_meta.get("team_id", ""),
        "current_team_name": player_meta.get("team_name", ""),
        "current_position": player_meta.get("position", ""),
        "current_age": player_meta.get("age", ""),
        "nationality": player_meta.get("nationality", ""),
        "shirt_number": player_meta.get("shirt_number", ""),
        # Totaux carrière complète
        "career_seasons": len(seasons_set),
        "career_clubs": len(clubs_set),
        "career_competitions": len(comp_ids),
        "career_matches_in_squad": len(flat_all),
        "career_matches_played": len(played_rows),
        "career_minutes": sum(r["played_minutes"] for r in played_rows),
        "career_goals": sum(r["goals"] for r in played_rows),
        "career_assists": sum(r["assists"] for r in played_rows),
        "career_shots_total": sum(r["shots_total"] for r in played_rows),
        "career_shots_on_goal": sum(r["shots_on_goal"] for r in played_rows),
        "career_yellow_cards": sum(
            1 for r in played_rows if r["yellow_card_minute"] is not None
        ),
        "career_national_team_matches": sum(
            1 for r in played_rows if r["is_national_team"]
        ),
        "first_season": min(seasons_set) if seasons_set else "",
        "last_season": max(seasons_set) if seasons_set else "",
    }

    # ============================================================
    # MATCHES récents : max(10 derniers matchs in_squad, 3 derniers mois)
    # ============================================================
    # Tri par date desc
    def _parse_date(s: str) -> datetime:
        if not s:
            return datetime(1900, 1, 1, tzinfo=timezone.utc)
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return datetime(1900, 1, 1, tzinfo=timezone.utc)

    flat_sorted = sorted(flat_all, key=lambda r: _parse_date(r["game_date_utc"]), reverse=True)
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_MATCHES_DAYS)

    by_n = flat_sorted[:RECENT_MATCHES_N]
    by_date = [r for r in flat_sorted if _parse_date(r["game_date_utc"]) >= cutoff]
    # Union (dédup par game_id, garde tri date desc)
    seen: set = set()
    matches_recent: list[dict] = []
    for r in (by_n + by_date):
        gid = r["game_id"]
        if gid in seen:
            continue
        seen.add(gid)
        matches_recent.append(r)
    matches_recent.sort(key=lambda r: _parse_date(r["game_date_utc"]), reverse=True)

    return summary, career_rows, matches_recent, comp_ids


# ============================================================
# Pipeline
# ============================================================
SUMMARY_COLS = [
    "player_id", "player_name",
    "current_team_id", "current_team_name", "current_position",
    "current_age", "nationality", "shirt_number",
    "career_seasons", "career_clubs", "career_competitions",
    "career_matches_in_squad", "career_matches_played", "career_minutes",
    "career_goals", "career_assists",
    "career_shots_total", "career_shots_on_goal",
    "career_yellow_cards", "career_national_team_matches",
    "first_season", "last_season",
]

CAREER_COLS = [
    "player_id", "player_name", "season", "competition_id", "club_id",
    "is_national_team",
    "matches_total", "matches_played", "matches_injured_absent",
    "minutes", "goals", "assists",
    "shots_total", "shots_on_goal", "yellow_cards",
]

MATCHES_COLS = [
    "player_id", "player_name", "game_date_utc", "season",
    "competition_id", "competition_type_id", "is_national_team",
    "game_id", "game_day",
    "club_id", "venue", "opponent_club_id",
    "club_goals", "opponent_goals",
    "participation_state",
    "shirt_number", "position_id", "is_captain",
    "played_minutes", "goals", "assists",
    "shots_total", "shots_on_goal", "shots_off_goal", "shots_blocked",
    "yellow_card_minute", "substituted_in_minute", "substituted_out_minute",
    "injury_id", "absence_id",
]


def load_player_meta_from_league_csv(
    csv_path: str, season_filter: int | None = None
) -> dict[str, dict]:
    """Lit un CSV produit par tm_league_scraper.py et indexe sur player_id.

    Si plusieurs lignes par joueur (cas normal: plusieurs saisons), garde la
    plus récente (saison max). Si season_filter, ne garde que les player_id
    présents dans cette saison (= effectif actif).
    """
    by_id: dict[str, dict] = {}
    seasons_by_id: dict[str, int] = {}
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pid = r.get("player_id")
            if not pid:
                continue
            try:
                s = int(r.get("season") or 0)
            except ValueError:
                s = 0
            if season_filter is not None and s != season_filter:
                continue
            prev_s = seasons_by_id.get(pid, -1)
            if s >= prev_s:
                seasons_by_id[pid] = s
                by_id[pid] = {
                    "team_id": r.get("team_id", ""),
                    "team_name": r.get("team_name", ""),
                    "position": r.get("position", ""),
                    "age": r.get("age", ""),
                    "nationality": r.get("nationality", ""),
                    "shirt_number": r.get("shirt_number", ""),
                    "player_name": r.get("player_name", ""),
                }
    return by_id


def scrape_players(
    player_meta_by_id: dict[str, dict],
    workers: int = DEFAULT_WORKERS,
) -> tuple[list[dict], list[dict], list[dict], dict[str, int], list[str]]:
    """Scrape la carrière de tous les player_id fournis. Multi-thread.

    Returns (summary_rows, career_rows, matches_rows, comp_id_counts, failed_ids).
    """
    summary_all: list[dict] = []
    career_all: list[dict] = []
    matches_all: list[dict] = []
    comp_id_counts: dict[str, int] = defaultdict(int)
    failed_ids: list[str] = []

    total = len(player_meta_by_id)
    done = 0
    t0 = time.time()

    def _process(pid_meta: tuple[str, dict]):
        pid, meta = pid_meta
        _polite_pause()
        data = fetch_player_career(pid)
        if data is None:
            return pid, None
        name = meta.get("player_name") or f"player_{pid}"
        return pid, aggregate_player(pid, name, meta, data)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_process, item): item[0] for item in player_meta_by_id.items()}
        for fut in as_completed(futs):
            pid = futs[fut]
            try:
                _pid, result = fut.result()
            except Exception as e:
                _log(f"   ! exception player_id={pid}: {type(e).__name__}: {e}")
                failed_ids.append(pid)
                continue
            done += 1
            if result is None:
                failed_ids.append(pid)
            else:
                summary, career, matches, comp_ids = result
                summary_all.append(summary)
                career_all.extend(career)
                matches_all.extend(matches)
                for c in comp_ids:
                    comp_id_counts[c] += 1
            if done % 25 == 0 or done == total:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                _log(
                    f"   progress {done}/{total} "
                    f"({100 * done / total:.0f}%) "
                    f"elapsed={elapsed:.0f}s rate={rate:.1f}/s "
                    f"failed={len(failed_ids)}"
                )

    return summary_all, career_all, matches_all, dict(comp_id_counts), failed_ids


def write_csv(path: str, rows: list[dict], cols: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    _log(f"   ✓ écrit {len(rows)} lignes → {path}")


# ============================================================
# CLI
# ============================================================
def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league", default=None,
        help="Code interne ligue (ex: mar1). Lit live/data/tm_scrap/{league}.csv "
             "et écrit live/data/tm_career/{league}_*.csv",
    )
    parser.add_argument(
        "--season-filter", type=int, default=2025,
        help="N'inclut que les joueurs présents dans l'effectif de cette saison "
             "(défaut: 2025 = saison 25/26 en cours). 0 = toutes saisons.",
    )
    parser.add_argument(
        "--player-ids", default=None,
        help="Liste explicite de player_id séparés par des virgules (ignore --league).",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Nb de threads parallèles (défaut: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Mode test: limite à --test-n joueurs",
    )
    parser.add_argument(
        "--test-n", type=int, default=5,
        help="Nb joueurs en mode test",
    )
    parser.add_argument(
        "--out-dir", default="live/data/tm_career",
        help="Dossier de sortie (défaut: live/data/tm_career)",
    )
    args = parser.parse_args()

    # Construit la liste des joueurs
    if args.player_ids:
        ids = [s.strip() for s in args.player_ids.split(",") if s.strip()]
        player_meta_by_id = {pid: {} for pid in ids}
        league_label = "custom"
    elif args.league:
        src = f"live/data/tm_scrap/{args.league}.csv"
        if not os.path.exists(src):
            _log(f"   ! introuvable: {src}")
            sys.exit(1)
        season_filter = args.season_filter if args.season_filter > 0 else None
        player_meta_by_id = load_player_meta_from_league_csv(src, season_filter)
        league_label = args.league
        _log(
            f"   chargé {len(player_meta_by_id)} joueurs depuis {src} "
            f"(saison filter={season_filter})"
        )
    else:
        parser.error("Il faut --league ou --player-ids")

    if args.test:
        n = min(args.test_n, len(player_meta_by_id))
        player_meta_by_id = dict(list(player_meta_by_id.items())[:n])
        _log(f"   MODE TEST: limité à {len(player_meta_by_id)} joueurs")

    # Scrape
    _log(f"\n>>> Scraping carrière {league_label} ({len(player_meta_by_id)} joueurs, "
         f"{args.workers} workers)...\n")
    t0 = time.time()
    summary, career, matches, comp_counts, failed = scrape_players(
        player_meta_by_id, workers=args.workers
    )
    elapsed = time.time() - t0
    _log(f"\n>>> Terminé en {elapsed:.0f}s. Échecs: {len(failed)}")
    if failed:
        _log(f"   IDs en échec: {failed[:20]}{' ...' if len(failed) > 20 else ''}")

    # Écrit les CSV
    out = args.out_dir
    write_csv(f"{out}/{league_label}_summary.csv", summary, SUMMARY_COLS)
    write_csv(f"{out}/{league_label}_career.csv", career, CAREER_COLS)
    write_csv(f"{out}/{league_label}_matches.csv", matches, MATCHES_COLS)

    # Rapport compétitions rencontrées
    comp_report_path = f"{out}/{league_label}_competitions_seen.csv"
    os.makedirs(os.path.dirname(comp_report_path), exist_ok=True)
    with open(comp_report_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["competition_id", "n_players_with_match"])
        for c, n in sorted(comp_counts.items(), key=lambda x: -x[1]):
            w.writerow([c, n])
    _log(f"   ✓ écrit rapport compétitions → {comp_report_path} "
         f"({len(comp_counts)} codes uniques)")

    # Top 30 console
    _log("\n>>> Top 30 compétitions rencontrées (à mapper vers tier+rating):")
    for c, n in sorted(comp_counts.items(), key=lambda x: -x[1])[:30]:
        _log(f"   {c:10s} : {n} joueurs")


if __name__ == "__main__":
    cli()
