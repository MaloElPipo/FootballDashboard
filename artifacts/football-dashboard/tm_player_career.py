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
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import tm_waf
from collection_metadata import start_attempt, complete_attempt, fail_attempt
from career_export_transaction import export_transaction
from tm_career_checkpoints import Checkpoints, valid_payload

# ============================================================
# Config
# ============================================================
BASE_URL = "https://www.transfermarkt.com"
CEAPI_PATH = "/ceapi/performance-game/{pid}"

TM_HEADERS = {
    # UA aligné sur celui utilisé par le navigateur pour obtenir le token WAF
    # (le WAF lie le cookie à l'empreinte du client — cf. tm_waf).
    "User-Agent": tm_waf.WAF_USER_AGENT,
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.transfermarkt.com/",
    "Accept-Encoding": "gzip",
}

TIMEOUT = 30
PAUSE_MIN = 1.0
PAUSE_MAX = 1.5
DEFAULT_WORKERS = 2

# Fenêtre matches récents : max(N derniers matchs, M derniers mois)
RECENT_MATCHES_N = 10
RECENT_MATCHES_DAYS = 90  # 3 mois

# ============================================================
# HTTP
# ============================================================
_print_lock = threading.Lock()
_blocked = threading.Event()
_recovery_lock = threading.Lock()
_pace_lock = threading.Lock()
_recovery_used = False
# Contract with scrape-weekly.yml: never retry this exit in a fresh process.
BLOCKED_EXIT_CODE = 75
BUDGET_EXIT_CODE = 76
TEMPORARY_EXIT_CODE = 77
_temporary_failure = threading.Event()
_deadline = None
_budget_expired = threading.Event()


def _within_budget():
    if _deadline is not None and time.monotonic() >= _deadline:
        _budget_expired.set()
        return False
    return True


def _log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def _polite_pause() -> None:
    # One shared pace, not one independent burst per worker.
    with _pace_lock:
        if not _blocked.is_set() and _within_budget():
            time.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))


def _fetch_json_once(
    url: str, timeout: int = TIMEOUT, *, token_provider=None, open_request=None
) -> tuple[dict | None, int | None, str | None, bool, str | None]:
    """Un seul GET JSON. Returns (json, status, error, is_challenge, token_used).

    ``is_challenge`` signale une réponse de challenge AWS WAF (202 corps vide
    ou header ``x-amzn-waf-action: challenge``), qui justifie un refresh + retry.
    ``token_used`` est le token WAF employé (pour un refresh ciblé « stale »).
    """
    headers = dict(TM_HEADERS)
    if not _within_budget():
        return None, None, "budget exhausted", False, None
    try:
        token = (token_provider() if token_provider else
                 tm_waf.get_waf_token(deadline=_deadline) if _deadline is not None
                 else tm_waf.get_waf_token())
    except tm_waf.AccessRefused:
        _blocked.set()
        return None, 403, "Access refused", False, None
    if token:
        headers["Cookie"] = f"aws-waf-token={token}"
    if not _within_budget():
        return None, None, "budget exhausted", False, token
    if _deadline is not None:
        timeout = min(timeout, max(0.01, _deadline - time.monotonic()))
    req = urllib.request.Request(url, headers=headers)
    try:
        with (open_request or urllib.request.urlopen)(req, timeout=timeout) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            waf_action = r.headers.get("x-amzn-waf-action")
            if (waf_action or "").lower() == "captcha":
                return None, r.status, "WAF captcha", False, token
            if tm_waf.is_challenge_response(r.status, len(data), waf_action):
                return None, r.status, "WAF challenge", True, token
            text = data.decode("utf-8", errors="replace")
            try:
                return json.loads(text), r.status, None, False, token
            except json.JSONDecodeError as e:
                return None, r.status, f"JSON decode: {e}", False, token
    except urllib.error.HTTPError as e:
        # 202/403 peuvent aussi remonter ici selon la config WAF.
        action = (e.headers.get("x-amzn-waf-action") or "").lower()
        if action == "captcha" and e.code != 405:
            return None, e.code, "WAF captcha", False, token
        is_ch = tm_waf.is_challenge_response(e.code, 0, action)
        if e.code == 405:
            # Only log allowlisted classifications, never cookies or response bodies.
            content_type = e.headers.get("Content-Type", "").lower()
            kind = "html" if "html" in content_type else "json" if "json" in content_type else "other"
            action = action if action in ("challenge", "captcha") else "unspecified"
            return None, 405, f"HTTP 405; waf={action}; body={kind}", False, token
        return None, e.code, f"HTTP {e.code}", is_ch, token
    except urllib.error.URLError as e:
        return None, None, f"URL error: {e.reason}", False, token
    except TimeoutError:
        return None, None, "timeout", False, token
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}", False, token


def _fetch_json(
    url: str, timeout: int = TIMEOUT
) -> tuple[dict | None, int | None, str | None]:
    """GET JSON avec gzip + cookie WAF. Retente une fois après refresh du token
    si un challenge AWS WAF est détecté.

    Returns (parsed_json, status, error). En cas de succès : (dict, 200, None).
    """
    global _recovery_used
    if _blocked.is_set():
        return None, 405, "Circuit ouvert : collecte globale arrêtée"
    payload, status, err, is_challenge, token_used = _fetch_json_once(url, timeout)
    if "captcha" in (err or "").lower():
        _blocked.set()
        _log("   ! CAPTCHA demandé : arrêt sans tentative de résolution automatique.")
        return None, status, err
    if status in (403, 405, 429):
        _blocked.set()
        return None, status, err
    if payload is None and (status is None or status >= 500):
        _temporary_failure.set()
    if payload is None and is_challenge:
        with _recovery_lock:
            if _blocked.is_set() or not _within_budget():
                return None, status, err
            _log(f"   ! Diagnostic Transfermarkt : {err}")
            if not _recovery_used:
                _recovery_used = True
                options = {"deadline": _deadline} if _deadline is not None else {}
                try:
                    tm_waf.get_waf_token(force_refresh=True, stale=token_used, **options)
                except tm_waf.AccessRefused:
                    _blocked.set()
                    return None, 403, "Access refused"
            if _blocked.is_set():
                return None, status, err
            # One recovery only, shared by challenges and HTTP refusals.
            # Concurrent workers may use it, never create another session.
            payload, status, err, is_challenge, _ = _fetch_json_once(url, timeout)
            if payload is None and (status is None or status >= 500):
                _temporary_failure.set()
            # A failed recovery is not necessarily a persistent refusal:
            # timeouts, 5xx and invalid JSON remain ordinary retryable failures.
            if payload is None and (
                is_challenge or status in (403, 405, 429)
                or "captcha" in (err or "").lower()
            ):
                _blocked.set()
                _log(f"   ! Reprise refusée ({err}) : arrêt réseau global, anciens CSV conservés.")
            return payload, status, err
    return payload, status, err


def fetch_player_career(player_id: str) -> dict | None:
    """GET ceapi/performance-game/{pid}. Retourne le dict 'data' ou None."""
    url = BASE_URL + CEAPI_PATH.format(pid=player_id)
    payload, status, err = _fetch_json(url)
    if payload is None:
        _log(f"   ! échec player_id={player_id}: status={status} err={err}")
        return None
    if not isinstance(payload, dict) or payload.get("success") is not True:
        _log(f"   ! API non-success player_id={player_id}")
        return None
    data = payload.get("data")
    return data if valid_payload(data) else None


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


def max_season_in_csv(csv_path: str) -> int:
    """Retourne la saison max présente dans un CSV effectifs (0 si aucune)."""
    smax = 0
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                s = int(r.get("season") or 0)
            except ValueError:
                s = 0
            if s > smax:
                smax = s
    return smax


def load_player_meta_from_league_csv(
    csv_path: str, season_filter: set[int] | None = None
) -> dict[str, dict]:
    """Lit un CSV produit par tm_league_scraper.py et indexe sur player_id.

    Si plusieurs lignes par joueur (cas normal: plusieurs saisons), garde la
    plus récente (saison max). Si season_filter (ensemble de saisons), ne
    garde que les player_id présents dans AU MOINS une de ces saisons
    (= effectif actif).
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
            if season_filter is not None and s not in season_filter:
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
    checkpoints=None,
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
    storage_failed = threading.Event()

    def _process(pid_meta: tuple[str, dict]):
        pid, meta = pid_meta
        name = meta.get("player_name") or f"player_{pid}"
        record = checkpoints.get(pid) if checkpoints else None
        if record:
            return pid, aggregate_player(pid, name, meta, record["data"])
        if checkpoints and checkpoints.error:
            storage_failed.set()
        if _blocked.is_set() or storage_failed.is_set() or not _within_budget():
            return pid, None
        _polite_pause()
        if _blocked.is_set() or storage_failed.is_set() or not _within_budget():
            return pid, None
        data = fetch_player_career(pid)
        if not valid_payload(data):
            return pid, None
        result = aggregate_player(pid, name, meta, data)
        if checkpoints:
            try:
                checkpoints.put(pid, data)
            except Exception:
                storage_failed.set()
                raise
        return pid, result

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

    if storage_failed.is_set():
        raise RuntimeError("Checkpoint persistence failed; collection stopped")
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
        "--season-filter", type=int, default=-1,
        help="N'inclut que les joueurs présents dans l'effectif de cette saison. "
             "-1 (défaut) = AUTO : saison max du CSV + la précédente (robuste "
             "aux ligues dont la nouvelle saison n'est pas encore scrapée ou "
             "aux clubs dont le refresh a échoué). 0 = toutes saisons.",
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
    parser.add_argument("--campaign", default=os.getenv("TM_CAMPAIGN_ID"))
    parser.add_argument("--checkpoint-dir", default="live/data/tm_checkpoints")
    parser.add_argument("--checkpoint-remote", action="store_true",
                        default=os.getenv("TM_CHECKPOINT_REMOTE") == "github")
    parser.add_argument("--budget-seconds", type=float, default=240,
                        help="Budget réseau par tentative, maximum 1200 s (défaut 240 s)")
    args = parser.parse_args()
    if not 0 < args.budget_seconds <= 1200:
        parser.error("--budget-seconds must be > 0 and <= 1200")
    args.campaign = args.campaign or uuid.uuid4().hex

    # A durable incomplete attempt also covers process timeouts/interruptions.
    # Test/custom/explicit-season exports must never certify a full collection.
    args.record_collection = bool(
        args.league and not args.player_ids and not args.test
        and args.season_filter == -1
    )
    return collect(args)


def collect(args):
    label = "custom" if args.player_ids else args.league
    if not label:
        raise SystemExit("Il faut --league ou --player-ids")
    with export_transaction(args.out_dir, label) as transaction:
        if args.record_collection:
            start_attempt(args.out_dir, args.league)
        return _collect(args, transaction)


def _record_failure(args, reason):
    if args.record_collection:
        try:
            fail_attempt(args.out_dir, args.league, reason)
        except OSError:
            # A full/unwritable disk may also prevent recording the cause.
            # Keep the durable incomplete marker and the original exception.
            _log("   ! Cause de l'échec non enregistrée.")


def _collect(args, transaction):
    global _deadline
    _budget_expired.clear()
    _temporary_failure.clear()
    # Construit la liste des joueurs
    if args.player_ids:
        ids = [s.strip() for s in args.player_ids.split(",") if s.strip()]
        player_meta_by_id = {pid: {} for pid in ids}
        league_label = "custom"
    elif args.league:
        src = f"live/data/tm_scrap/{args.league}.csv"
        if not os.path.exists(src):
            _record_failure(args, "missing_squad")
            _log(f"   ! introuvable: {src}")
            sys.exit(1)
        if args.season_filter == -1:
            # AUTO : effectif actif = saison max du CSV + la précédente.
            # Capte les recrues/promus (saison N) sans perdre un club entier
            # dont le refresh saison N aurait échoué (encore présent en N-1).
            smax = max_season_in_csv(src)
            season_filter = {smax, smax - 1} if smax > 0 else None
        elif args.season_filter > 0:
            season_filter = {args.season_filter}
        else:
            season_filter = None
        player_meta_by_id = load_player_meta_from_league_csv(src, season_filter)
        league_label = args.league
        _log(
            f"   chargé {len(player_meta_by_id)} joueurs depuis {src} "
            f"(saison filter={sorted(season_filter) if season_filter else None})"
        )
    else:
        raise SystemExit("Il faut --league ou --player-ids")

    if args.test:
        n = min(args.test_n, len(player_meta_by_id))
        player_meta_by_id = dict(list(player_meta_by_id.items())[:n])
        _log(f"   MODE TEST: limité à {len(player_meta_by_id)} joueurs")

    if not player_meta_by_id:
        _record_failure(args, "missing_squad")
        raise SystemExit(1)

    checkpoints = Checkpoints(
        getattr(args, "checkpoint_dir", "live/data/tm_checkpoints"),
        getattr(args, "campaign", None) or uuid.uuid4().hex,
        getattr(args, "checkpoint_remote", False),
    )
    # Local inventory is not source traffic and must not exhaust its budget.
    inventory_started = time.monotonic()
    missing = [pid for pid in player_meta_by_id if not checkpoints.get(pid)]
    _log("TM_PHASE " + json.dumps({
        "phase": "prepare", "league": league_label,
        "restore_seconds": round(checkpoints.restore_seconds, 3),
        "inventory_seconds": round(time.monotonic() - inventory_started, 3),
        "players": len(player_meta_by_id),
        "reused": len(player_meta_by_id) - len(missing), "missing": len(missing),
    }))
    _deadline = time.monotonic() + getattr(args, "budget_seconds", 240)
    warmup_started = time.monotonic()
    try:
        if missing and _within_budget():
            tm_waf.warm_up(deadline=_deadline)
    except tm_waf.AccessRefused:
        _blocked.set()
        _record_failure(args, "access_blocked")
        sys.exit(BLOCKED_EXIT_CODE)
    except Exception:
        _deadline = None
        _record_failure(args, "player_requests_failed")
        raise
    _log("TM_PHASE " + json.dumps({
        "phase": "warmup", "league": league_label,
        "seconds": round(time.monotonic() - warmup_started, 3),
    }))

    # Scrape
    _log(f"\n>>> Scraping carrière {league_label} ({len(player_meta_by_id)} joueurs, "
         f"{args.workers} workers)...\n")
    t0 = time.time()
    try:
        with checkpoints.periodic_flush():
            summary, career, matches, comp_counts, failed = scrape_players(
                player_meta_by_id, workers=args.workers, checkpoints=checkpoints
            )
    except Exception:
        _record_failure(args, "player_requests_failed")
        raise
    finally:
        _within_budget()
        _deadline = None
        # Even on failure, persist every validated success before exiting.
        flush_started = time.monotonic()
        checkpoints.flush()
        _log("TM_PHASE " + json.dumps({
            "phase": "final_flush", "league": league_label,
            "seconds": round(time.monotonic() - flush_started, 3),
        }))
    elapsed = time.time() - t0
    _log(f"\n>>> Terminé en {elapsed:.0f}s. Échecs: {len(failed)}")
    if failed:
        _log(f"   IDs en échec: {failed[:20]}{' ...' if len(failed) > 20 else ''}")

    # Une réponse partielle ne doit jamais remplacer un export complet.
    # Même un seul joueur réussi masquait auparavant un blocage quasi total.
    # Toute erreur conserve les CSV précédents et rend la ligue éligible au retry.
    total_players = len(player_meta_by_id)
    if _blocked.is_set():
        _record_failure(args, "access_blocked")
        _log("   ! Blocage persistant : arrêt global demandé, fichiers existants préservés.")
        sys.exit(BLOCKED_EXIT_CODE)
    if failed or not summary:
        _record_failure(args, "budget_exhausted" if _budget_expired.is_set()
                        else "player_requests_failed")
        fail_pct = 100 * len(failed) / total_players if total_players else 0
        _log(
            f"\n>>> ALERTE : {fail_pct:.0f}% d'échecs ({len(failed)}/{total_players}), "
            f"{len(summary)} joueur(s) produit(s) — export incomplet refusé."
        )
        _log("   Écriture annulée — fichiers existants préservés.")
        sys.exit(BUDGET_EXIT_CODE if _budget_expired.is_set()
                 else TEMPORARY_EXIT_CODE if _temporary_failure.is_set() else 1)

    # Écrit les CSV
    out = args.out_dir
    def prepare_exports(staging):
        write_csv(f"{staging}/{league_label}_summary.csv", summary, SUMMARY_COLS)
        write_csv(f"{staging}/{league_label}_career.csv", career, CAREER_COLS)
        write_csv(f"{staging}/{league_label}_matches.csv", matches, MATCHES_COLS)
        with open(staging / f"{league_label}_competitions_seen.csv",
                  "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["competition_id", "n_players_with_match"])
            for c, n in sorted(comp_counts.items(), key=lambda x: -x[1]):
                w.writerow([c, n])

    try:
        evidence = checkpoints.evidence(player_meta_by_id) if args.record_collection else None
        transaction.write(prepare_exports)
        if args.record_collection:
            complete_attempt(out, league_label, evidence=evidence)
    except Exception:
        _record_failure(args, "write_failed")
        raise
    comp_report_path = f"{out}/{league_label}_competitions_seen.csv"
    _log(f"   ✓ écrit rapport compétitions → {comp_report_path} "
         f"({len(comp_counts)} codes uniques)")

    # Top 30 console
    _log("\n>>> Top 30 compétitions rencontrées (à mapper vers tier+rating):")
    for c, n in sorted(comp_counts.items(), key=lambda x: -x[1])[:30]:
        _log(f"   {c:10s} : {n} joueurs")


if __name__ == "__main__":
    cli()
