"""Pipeline daily : pour chaque match Top 5 J/J+1, produit une prédiction
joueur (xG / xA / proba scorer / proba assist) + récupère les odds buteur/passeur
Betclic, puis append dans `data/forward_log.jsonl`.

Usage :
    python predict_today.py [--leagues bundesliga,ligue_1] [--days 2]
                            [--no-betclic]   # skip scraping (mode rapide)
                            [--dry-run]      # affiche sans écrire dans le log

Idempotent : un (event_id, player_id) déjà loggé n'est pas dupliqué.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
PARENT = ROOT.parent
sys.path.insert(0, str(PARENT))

from g2_engine import lambdas_buchdahl  # noqa: E402
from preview_player_odds._3_model_proxy import (  # noqa: E402  (import via proxy below)
    aggregate_player_pool,
    distribute_xg_to_players,
)
from live.bsd_helpers import (  # noqa: E402
    TOP5_LEAGUES,
    get_upcoming_events,
    get_event_detail,
    extract_odds,
    fetch_team_squads_parallel,
)
from live.file_lock import log_lock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("predict_today")


FORWARD_LOG = DATA_DIR / "forward_log.jsonl"
FORWARD_LOG_LOCK = DATA_DIR / "forward_log.lock"


# ---------------------------------------------------------------------------
# Utilitaires noms (matching Betclic ↔ BSD)
# ---------------------------------------------------------------------------
def norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def name_match_score(a: str, b: str) -> float:
    """Score 0-1 entre deux noms de joueurs (ou équipes)."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    jaccard = overlap / union
    # Bonus si le dernier token (souvent le nom de famille) match
    if a.split()[-1] == b.split()[-1]:
        jaccard = max(jaccard, 0.85)
    return jaccard


def find_betclic_match(ev: dict, betclic_matches: list[dict]) -> dict | None:
    """Trouve le BetclicMatch correspondant à un BSD event via fuzzy match équipes+date."""
    bsd_home = ev.get("home_team", "")
    bsd_away = ev.get("away_team", "")
    bsd_dt = ev.get("event_date", "")
    bsd_date = bsd_dt[:10] if bsd_dt else ""

    best, best_score = None, 0.0
    for bm in betclic_matches:
        sh = name_match_score(bsd_home, bm.get("home_team", ""))
        sa = name_match_score(bsd_away, bm.get("away_team", ""))
        if sh < 0.4 or sa < 0.4:
            continue
        # Bonus si même date kickoff
        bm_ko = bm.get("kickoff_utc")
        bm_date = bm_ko[:10] if bm_ko else ""
        date_bonus = 0.2 if bm_date == bsd_date else 0.0
        score = (sh + sa) / 2 + date_bonus
        if score > best_score:
            best, best_score = bm, score
    return best if best_score >= 0.6 else None


def find_betclic_player_odd(player_name: str, betclic_match: dict, market_type: str) -> float | None:
    """Cherche dans les selections Betclic du match un joueur donné pour un marché.
    market_type ∈ {'goalscorer', 'assist'}.
    """
    if not betclic_match:
        return None
    best, best_score = None, 0.0
    for sel in betclic_match.get("selections", []):
        if sel.get("market_type") != market_type:
            continue
        score = name_match_score(player_name, sel.get("selection_name", ""))
        if score > best_score:
            best, best_score = sel, score
    if best and best_score >= 0.7:
        return best.get("odds")
    return None


# ---------------------------------------------------------------------------
# Lineup (BSD prédite, fallback heuristique sur les 5 derniers matchs)
# ---------------------------------------------------------------------------
def build_lineup_fallback(team_id: int, team_side: str, pool: dict, n_starters: int = 11,
                          n_subs: int = 6) -> list[dict]:
    """Si BSD n'a pas de lineup, on prend les 17 joueurs ayant le plus de minutes dans la saison."""
    players = [(pid, p) for pid, p in pool.items() if p.get("team_id") == team_id]
    players.sort(key=lambda x: x[1].get("minutes_total", 0), reverse=True)
    out = []
    for i, (pid, p) in enumerate(players[:n_starters + n_subs]):
        out.append({
            "player_id": pid,
            "team_id": team_id,
            "side": team_side,
            "is_starter": i < n_starters,
            "position": "G" if p.get("is_gk") else None,
        })
    return out


def get_lineup_for_event(ev_detail: dict, home_id: int, away_id: int, pool: dict) -> list[dict]:
    """Retourne la lineup au format `get_lineup_players` du modèle, ou un fallback.
    Déduplique par player_id (BSD met parfois le même joueur dans starters ET subs)."""
    lineups = ev_detail.get("lineups") or {}
    out: list[dict] = []
    seen_pids: set[int] = set()

    def _add(pid, team_id, side, is_starter, position):
        if pid is None:
            return
        pid = int(pid)
        if pid in seen_pids:
            return
        seen_pids.add(pid)
        out.append({"player_id": pid, "team_id": team_id, "side": side,
                    "is_starter": is_starter, "position": position})

    for side, team_id in (("home", home_id), ("away", away_id)):
        side_block = lineups.get(side) if isinstance(lineups, dict) else None
        if not side_block:
            for lp in build_lineup_fallback(team_id, side, pool):
                _add(lp["player_id"], team_id, side, lp["is_starter"], lp.get("position"))
            continue
        starters = side_block.get("starters") or side_block.get("starting") or []
        subs = side_block.get("substitutes") or side_block.get("subs") or []
        for p in starters:
            if isinstance(p, dict):
                pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                _add(pid, team_id, side, True, p.get("position"))
        for p in subs:
            if isinstance(p, dict):
                pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                _add(pid, team_id, side, False, p.get("position"))
        if not any(lp["side"] == side for lp in out):
            for lp in build_lineup_fallback(team_id, side, pool):
                _add(lp["player_id"], team_id, side, lp["is_starter"], lp.get("position"))
    return out


# ---------------------------------------------------------------------------
# Pool joueurs
# ---------------------------------------------------------------------------
def assign_team_ids_via_squads(pool: dict, league_team_ids: list[int],
                                cache_path: Path) -> int:
    """Pour chaque équipe de la ligue, récupère l'effectif actuel via BSD
    `/players/?team={id}` et assigne `team_id` (résout transferts hiver).
    Cache 24h dans `{league}_squads.json`.
    """
    cache: dict[int, list[dict]] = {}
    use_cache = False
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 24:
            try:
                cache = {int(k): v for k, v in json.loads(cache_path.read_text()).items()}
                use_cache = True
            except Exception:
                cache = {}

    if not use_cache:
        log.info("  Fetch squads BSD pour %d équipes...", len(league_team_ids))
        cache = fetch_team_squads_parallel(league_team_ids)
        cache_path.write_text(json.dumps({str(k): v for k, v in cache.items()}))

    assigned = 0
    for team_id, squad in cache.items():
        for p in squad:
            pid = p.get("id")
            if pid is None:
                continue
            pid = int(pid)
            if pid in pool:
                # Squad = équipe actuelle, prioritaire sur tout
                if pool[pid].get("team_id") != team_id:
                    pool[pid]["team_id"] = team_id
                    assigned += 1
            else:
                # Joueur existe en squad mais pas (encore) dans le pool de stats :
                # on l'ajoute avec valeurs neutres pour qu'il puisse hériter du
                # prior quand il sera shrunk-per-90 (= prior).
                position = p.get("position")
                pool[pid] = {
                    "name": p.get("name") or p.get("short_name") or f"Player {pid}",
                    "team_id": team_id,
                    "is_gk": position == "G",
                    "minutes_total": 0,
                    "matches_played": 0,
                    "goals_total": 0,
                    "assists_total": 0,
                    "xg_total": 0.0,
                    "xa_total": 0.0,
                    "shots_total": 0,
                    "key_passes_total": 0,
                    "starts": 0,
                    "subs_in": 0,
                    "last_event_date": None,
                }
                assigned += 1
    return assigned


def load_pool(slug: str) -> dict:
    pool_file = DATA_DIR / f"{slug}_pool.json"
    if not pool_file.exists():
        log.warning("Pool manquant pour %s — exécute build_player_pool.py %s", slug, slug)
        return {}
    raw = json.loads(pool_file.read_text())
    pool = aggregate_player_pool(raw["by_event_stats"], raw["events"])

    # Récupère tous les team_ids de la ligue depuis les events
    team_ids = set()
    for ev in raw["events"].values():
        h = (ev.get("home_team_obj") or {}).get("id")
        a = (ev.get("away_team_obj") or {}).get("id")
        if h: team_ids.add(h)
        if a: team_ids.add(a)

    cache_path = DATA_DIR / f"{slug}_squads.json"
    n_assigned = assign_team_ids_via_squads(pool, sorted(team_ids), cache_path)
    n_with_team = sum(1 for p in pool.values() if p.get("team_id") is not None)
    log.info("Pool %s : %d joueurs (%d/%d ont team_id assigné via squads)",
             slug, len(pool), n_with_team, len(pool))
    return pool


# ---------------------------------------------------------------------------
# Betclic scraper async
# ---------------------------------------------------------------------------
LEAGUE_TO_BETCLIC_KEY = {
    "premier_league": "premier_league",
    "la_liga": "la_liga",
    "serie_a": "serie_a",
    "bundesliga": "bundesliga",
    "ligue_1": "ligue_1",
}


async def scrape_betclic_leagues(slugs: list[str]) -> dict[str, list[dict]]:
    from betclic_scraper import scrape_betclic
    comp_keys = [LEAGUE_TO_BETCLIC_KEY[s] for s in slugs if s in LEAGUE_TO_BETCLIC_KEY]
    if not comp_keys:
        return {}
    log.info("Scraping Betclic pour %d ligues : %s", len(comp_keys), ", ".join(comp_keys))
    res = await scrape_betclic(
        competitions=comp_keys,
        include_1x2=False,
        include_goalscorer=True,
        include_assist=True,
        include_outright=False,
    )
    by_slug: dict[str, list[dict]] = {}
    for comp_data in res:
        ck = comp_data.get("competition", "")
        slug = next((s for s, k in LEAGUE_TO_BETCLIC_KEY.items() if k == ck), ck)
        # Convertir BetclicMatch → dict
        ms = []
        for bm in comp_data.get("matches", []):
            ms.append({
                "home_team": bm.home_team,
                "away_team": bm.away_team,
                "match_id": bm.match_id,
                "kickoff_utc": bm.kickoff_utc.isoformat() if bm.kickoff_utc else None,
                "selections": [
                    {"market_type": s.market_type, "selection_name": s.selection_name,
                     "odds": s.odds, "market_name": s.market_name}
                    for s in bm.selections
                ],
            })
        by_slug[slug] = ms
        log.info("  %s : %d matchs scrapés", slug, len(ms))
    return by_slug


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def load_seen_keys() -> set[tuple[int, int]]:
    """Retourne l'ensemble des (event_id, player_id) déjà loggés (toutes dates)."""
    seen: set[tuple[int, int]] = set()
    if not FORWARD_LOG.exists():
        return seen
    with FORWARD_LOG.open() as f:
        for line in f:
            try:
                d = json.loads(line)
                seen.add((int(d["event_id"]), int(d["player_id"])))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return seen


def predict_one_event(ev: dict, slug: str, pool: dict,
                      betclic_matches: list[dict]) -> list[dict]:
    """Construit les lignes de log pour un match à venir."""
    ev_id = ev["id"]
    home_id = (ev.get("home_team_obj") or {}).get("id")
    away_id = (ev.get("away_team_obj") or {}).get("id")
    if not home_id or not away_id:
        return []

    odds = extract_odds(ev)
    if not (odds["odds_h"] and odds["odds_d"] and odds["odds_a"]):
        log.warning("Event %s : odds 1X2 manquantes", ev_id)
        return []

    try:
        xg_h, xg_a, method = lambdas_buchdahl(
            odds["odds_h"], odds["odds_d"], odds["odds_a"],
            odds["ou25_under"], odds["ou25_over"],
            odds["btts_yes"], odds["btts_no"],
        )
    except Exception as e:
        log.warning("Event %s : lambdas_buchdahl a échoué (%s)", ev_id, e)
        return []

    # Détail matche pour récupérer la lineup si dispo
    detail = get_event_detail(ev_id) or ev
    lineup_players = get_lineup_for_event(detail, home_id, away_id, pool)
    if not lineup_players:
        log.warning("Event %s : aucune lineup ni fallback possible", ev_id)
        return []

    # Distribution
    predictions = distribute_xg_to_players(xg_h, xg_a, home_id, away_id, lineup_players, pool)

    # Match Betclic (par équipes)
    bm = find_betclic_match(ev, betclic_matches)
    if bm:
        log.info("  Event %s : Betclic match trouvé (%d selections)",
                 ev_id, len(bm.get("selections", [])))

    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[dict] = []
    for pid, pred in predictions.items():
        bc_scorer = find_betclic_player_odd(pred["name"], bm or {}, "goalscorer")
        bc_assist = find_betclic_player_odd(pred["name"], bm or {}, "assist")

        edge_scorer = None
        if bc_scorer and pred["p_scorer"]:
            edge_scorer = pred["p_scorer"] * bc_scorer - 1.0
        edge_assist = None
        if bc_assist and pred["p_assist"]:
            edge_assist = pred["p_assist"] * bc_assist - 1.0

        lines.append({
            "logged_at": logged_at,
            "league_slug": slug,
            "league_name": TOP5_LEAGUES[slug]["name"],
            "event_id": ev_id,
            "match": f"{ev.get('home_team')} - {ev.get('away_team')}",
            "kickoff": ev.get("event_date"),
            "player_id": pid,
            "player_name": pred["name"],
            "team_id": pred["team_id"],
            "team_side": pred["team_side"],
            "is_starter": pred.get("is_starter"),
            "is_gk": pred.get("is_gk"),
            "minutes_expected": pred.get("minutes_expected"),
            "xg_team_home": xg_h,
            "xg_team_away": xg_a,
            "lambdas_method": method,
            "xg_player": pred["xg_calibrated"],
            "xa_player": pred["xa_calibrated"],
            "p_model_scorer": pred["p_scorer"],
            "p_model_assist": pred["p_assist"],
            "fair_odd_scorer": pred["odd_scorer"],
            "fair_odd_assist": pred["odd_assist"],
            "betclic_odd_scorer": bc_scorer,
            "betclic_odd_assist": bc_assist,
            "edge_scorer": edge_scorer,
            "edge_assist": edge_assist,
            # Champs à remplir post-match
            "outcome_scored": None,
            "outcome_assisted": None,
            "outcome_minutes_played": None,
            "enriched_at": None,
        })
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="all",
                    help="Comma-separated slugs (default: all top 5)")
    ap.add_argument("--days", type=int, default=2,
                    help="Nombre de jours à venir à scanner (default: 2)")
    ap.add_argument("--no-betclic", action="store_true",
                    help="Skip scraping Betclic (utile en debug)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche sans écrire dans forward_log.jsonl")
    args = ap.parse_args()

    if args.leagues == "all":
        slugs = list(TOP5_LEAGUES.keys())
    else:
        slugs = [s.strip() for s in args.leagues.split(",") if s.strip() in TOP5_LEAGUES]
    if not slugs:
        log.error("Aucune ligue valide")
        return

    today = date.today()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=args.days)).isoformat()

    # 1. Pools (1× par ligue)
    pools = {slug: load_pool(slug) for slug in slugs}
    for slug, pool in pools.items():
        log.info("Pool %s : %d joueurs", slug, len(pool))

    # 2. Events upcoming (déduplication par event_id pour blinder contre BSD doublons)
    all_events: list[tuple[dict, str]] = []
    seen_event_ids: set[int] = set()
    for slug in slugs:
        evs = get_upcoming_events(TOP5_LEAGUES[slug]["bsd_id"], date_from, date_to)
        log.info("%s : %d matchs entre %s et %s", slug, len(evs), date_from, date_to)
        for ev in evs:
            try:
                eid = int(ev["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if eid in seen_event_ids:
                continue
            seen_event_ids.add(eid)
            all_events.append((ev, slug))

    if not all_events:
        log.info("Aucun match upcoming — rien à faire.")
        return

    # 3. Scrape Betclic en parallèle (1 fois pour toutes les ligues)
    betclic_by_slug: dict[str, list[dict]] = {}
    if not args.no_betclic:
        try:
            betclic_by_slug = asyncio.run(scrape_betclic_leagues(slugs))
        except Exception as e:
            log.warning("Scraping Betclic a échoué : %s — on continue sans odds book", e)

    # 4. Pipeline event par event
    # Le calcul (sans I/O log) reste hors lock pour ne pas bloquer enrich.
    candidate_lines: list[dict] = []
    for ev, slug in all_events:
        ev_id = ev["id"]
        bc_matches = betclic_by_slug.get(slug, [])
        try:
            lines = predict_one_event(ev, slug, pools.get(slug, {}), bc_matches)
        except Exception as e:
            log.exception("Event %s : pipeline error : %s", ev_id, e)
            continue
        candidate_lines.extend(lines)
        log.info("Event %s (%s) : %d lignes candidates (xG team %.2f - %.2f, %s)",
                 ev_id, ev.get("home_team", "")[:18] + " - " + ev.get("away_team", "")[:18],
                 len(lines),
                 lines[0]["xg_team_home"] if lines else 0,
                 lines[0]["xg_team_away"] if lines else 0,
                 lines[0]["lambdas_method"] if lines else "-")

    if args.dry_run:
        log.info("DRY-RUN : %d lignes candidates (non écrites)", len(candidate_lines))
        for ln in candidate_lines[:5]:
            print(json.dumps(ln, indent=2, ensure_ascii=False))
        return

    if not candidate_lines:
        log.info("Aucune ligne candidate.")
        return

    # Section critique : recharge seen sous lock + filtre + append en une seule
    # transaction → résiste aux runs concurrents (2× clic UI / cron+manuel).
    with log_lock(FORWARD_LOG_LOCK, timeout=30.0):
        seen = load_seen_keys()
        new_lines: list[dict] = []
        local_seen: set[tuple[int, int]] = set()
        for ln in candidate_lines:
            key = (int(ln["event_id"]), int(ln["player_id"]))
            if key in seen or key in local_seen:
                continue
            local_seen.add(key)
            new_lines.append(ln)

        if not new_lines:
            log.info("Aucune nouvelle prédiction à logger (toutes déjà présentes).")
            return

        with FORWARD_LOG.open("a") as f:
            for ln in new_lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        log.info("✅ %d lignes appendées dans %s (%d candidates filtrées)",
                 len(new_lines), FORWARD_LOG, len(candidate_lines) - len(new_lines))


if __name__ == "__main__":
    main()
