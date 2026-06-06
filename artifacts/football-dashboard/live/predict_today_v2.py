"""Pipeline daily V2 — étend `predict_today.py` aux ligues hors Top 5
(UCL/UEL/UECL + ~25 championnats secondaires).

Garde-fou strict : `predict_today.py` n'est PAS modifié. Ce script importe
ses helpers (load_pool, get_lineup_for_event, distribute_xg_to_players,
log_lock, ...) tels quels et ne réimplémente que la boucle principale +
predict_one_event_v2 (qui utilise le router odds en cascade BSD →
TheOddsAPI → Betclic).

Usage :
    python live/predict_today_v2.py [--leagues all|champions_league,bundesliga]
                                    [--days 2] [--no-betclic] [--dry-run]
                                    [--include-tier2]

Idempotent : partage le même `forward_log.jsonl` que predict_today.py
(upsert atomique sous file lock, jamais d'écrasement post-match).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

# Réutilisation TOTALE du moteur Buteurs Maison 4.1 via les helpers existants.
import live.predict_today as pt  # noqa: E402
from live.bsd_helpers import (  # noqa: E402
    get_upcoming_events,
    get_event_detail,
    extract_odds,
)
from live.file_lock import log_lock  # noqa: E402
from live.bsd_player_id_resolver import resolve_bsd_player_id  # noqa: E402
from live.leagues_config import LEAGUES, get_active_leagues, get_by_slug  # noqa: E402
from live.odds_router import (  # noqa: E402
    get_match_odds_3markets,
    to_predict_today_format,
)
from g2_engine import lambdas_buchdahl  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("predict_today_v2")

FORWARD_LOG = pt.FORWARD_LOG
FORWARD_LOG_LOCK = pt.FORWARD_LOG_LOCK


# ---------------------------------------------------------------------
# Préparation : étend la table TOP5_LEAGUES de predict_today (in-memory)
# avec les nouvelles ligues du registre. Évite que les helpers internes
# (qui font `pt.TOP5_LEAGUES[slug]["name"]`) ne plantent.
# Cette mutation est locale au process (pas de side-effect persistant).
# ---------------------------------------------------------------------
def _extend_top5_with_registry() -> None:
    for slug, cfg in LEAGUES.items():
        if not cfg.bsd_id:
            continue  # ligues sans BSD id (ex: UECL) — pas via le pool BSD
        if slug not in pt.TOP5_LEAGUES:
            pt.TOP5_LEAGUES[slug] = {
                "bsd_id": cfg.bsd_id,
                "name": cfg.name,
                "country": cfg.country,
            }
        # Étend aussi LEAGUE_TO_COUNTRY (pour resolve_detailed_position via
        # manual_positions.json, qui ne couvre que le Top 5 — fallback no-op
        # pour les ligues hors-Top5 : pas de manual override, cascade BSD seule).
        if slug not in pt.LEAGUE_TO_COUNTRY:
            iso3 = (cfg.country or "")[:3].upper()
            pt.LEAGUE_TO_COUNTRY[slug] = iso3
        # Étend LEAGUE_TO_BETCLIC_KEY si betclic_slug existe
        if cfg.betclic_slug and slug not in pt.LEAGUE_TO_BETCLIC_KEY:
            # Nom de la clé Betclic dans betclic_scraper.COMPETITIONS
            # On suppose un mapping 1:1 slug ↔ key (ce qui est le cas pour
            # champions_league, europa_league, et le Top 5).
            pt.LEAGUE_TO_BETCLIC_KEY[slug] = slug


# ---------------------------------------------------------------------
# Variant predict_one_event qui injecte le router odds en cascade
# ---------------------------------------------------------------------
def predict_one_event_v2(ev: dict, slug: str, league_cfg, pool: dict,
                         betclic_matches: list[dict]) -> list[dict]:
    """Variante V2 de pt.predict_one_event :
    - Si BSD inline odds incomplètes → tente le router (TheOddsAPI / Betclic).
    - Tout le reste (lineups, distribute_xg_to_players, post-process forward
      log row) est strictement identique au moteur original.
    """
    ev_id = ev["id"]
    home_id = (ev.get("home_team_obj") or {}).get("id")
    away_id = (ev.get("away_team_obj") or {}).get("id")
    if not home_id or not away_id:
        return []

    home_team = ev.get("home_team", "")
    away_team = ev.get("away_team", "")
    kickoff_iso = ev.get("event_date")

    # 1) Cascade odds : BSD inline → BSD compareOdds → TheOddsAPI → Betclic
    odds = extract_odds(ev)
    has_1x2 = bool(odds.get("odds_h") and odds.get("odds_d") and odds.get("odds_a"))
    if not has_1x2:
        routed = get_match_odds_3markets(
            bsd_event_id=ev_id,
            league_cfg=league_cfg,
            home_team=home_team,
            away_team=away_team,
            kickoff_iso=kickoff_iso,
            bsd_event_payload=ev,
            betclic_matches=betclic_matches,
        )
        if not routed:
            log.warning("Event %s (%s) : aucune source odds 1X2 trouvée — skip",
                        ev_id, slug)
            return []
        odds = to_predict_today_format(routed)
        odds_source = routed.get("source", "?")
        odds_mode = routed.get("mode", "?")
        log.info("Event %s : odds via router=%s (mode %s)",
                 ev_id, odds_source, odds_mode)
    else:
        odds_source = "bsd_event"
        odds_mode = "A" if (odds.get("ou25_over") and odds.get("btts_yes")) else (
            "B" if odds.get("ou25_over") else "C"
        )

    # 2) Lambdas via Buchdahl (moteur 4.1 INTACT)
    try:
        xg_h, xg_a, method = lambdas_buchdahl(
            odds["odds_h"], odds["odds_d"], odds["odds_a"],
            odds.get("ou25_under"), odds.get("ou25_over"),
            odds.get("btts_yes"), odds.get("btts_no"),
        )
    except Exception as e:
        log.warning("Event %s : lambdas_buchdahl a échoué (%s)", ev_id, e)
        return []

    # 3) Lineup + distribute (réutilisation directe des helpers originaux)
    detail = get_event_detail(ev_id) or ev
    lineup_players, confirmed_by_side, excluded = pt.get_lineup_for_event(
        detail, home_id, away_id, pool)
    if not lineup_players:
        log.warning("Event %s : aucune lineup ni fallback possible — skip", ev_id)
        return []

    if excluded:
        log.info("  Event %s : %d joueurs exclus (blessure/suspension)",
                 ev_id, len(excluded))

    from preview_player_odds._3_model_proxy import distribute_xg_to_players
    predictions = distribute_xg_to_players(
        xg_h, xg_a, home_id, away_id, lineup_players, pool,
        lineup_confirmed=confirmed_by_side,
    )

    home_confirmed = bool(confirmed_by_side.get("home"))
    away_confirmed = bool(confirmed_by_side.get("away"))
    lineup_confirmed = home_confirmed or away_confirmed
    lineup_conf = pt.compute_lineup_confidence(lineup_players, pool)

    # 4) Match Betclic pour buteurs/passeurs
    bm = pt.find_betclic_match(ev, betclic_matches)
    if bm:
        log.info("  Event %s : Betclic match trouvé (%d selections)",
                 ev_id, len(bm.get("selections", [])))

    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[dict] = []
    for pid, pred in predictions.items():
        bc_scorer = pt.find_betclic_player_odd(pred["name"], bm or {}, "goalscorer")
        bc_assist = pt.find_betclic_player_odd(pred["name"], bm or {}, "assist")

        edge_scorer = (pred["p_scorer"] * bc_scorer - 1.0) if (bc_scorer and pred["p_scorer"]) else None
        edge_assist = (pred["p_assist"] * bc_assist - 1.0) if (bc_assist and pred["p_assist"]) else None

        pool_p = pool.get(pid, {})
        lines.append({
            "logged_at": logged_at,
            "league_slug": slug,
            "league_name": league_cfg.name,
            "league_region": league_cfg.region,
            "event_id": ev_id,
            "match": f"{home_team} - {away_team}",
            "kickoff": kickoff_iso,
            "player_id": pid,
            "bsd_player_id": resolve_bsd_player_id(pid, pred.get("name"), pred.get("team_id")),
            "player_name": pred["name"],
            "team_id": pred["team_id"],
            "team_side": pred["team_side"],
            "is_starter": pred.get("is_starter") if confirmed_by_side.get(pred["team_side"]) else None,
            "is_presumed_starter": (
                pred.get("is_starter")
                if not confirmed_by_side.get(pred["team_side"]) else None
            ),
            "start_rate": pool_p.get("start_rate"),
            "is_gk": pred.get("is_gk"),
            "lineup_confirmed": lineup_confirmed,
            "home_lineup_confirmed": home_confirmed,
            "away_lineup_confirmed": away_confirmed,
            "lineup_confidence_home": lineup_conf.get("home"),
            "lineup_confidence_away": lineup_conf.get("away"),
            "position": pt.resolve_detailed_position(pool_p, pred.get("position_used")),
            "availability": pool_p.get("availability") or "available",
            "is_unavailable": bool(pred.get("is_unavailable", False)),
            "injury_type": pool_p.get("injury_type") or None,
            "minutes_expected": pred.get("minutes_expected"),
            "xg_team_home": xg_h,
            "xg_team_away": xg_a,
            "lambdas_method": method,
            "xg_player": pred["xg_calibrated"],
            "xa_player": pred["xa_calibrated"],
            "xg_per_90_used": pred.get("xg_per_90_used"),
            "xa_per_90_used": pred.get("xa_per_90_used"),
            "expected_shots": pred.get("expected_shots"),
            "expected_shots_on_target": pred.get("expected_shots_on_target"),
            "shots_per_90_used": pred.get("shots_per_90_used"),
            "shots_on_target_per_90_used": pred.get("shots_on_target_per_90_used"),
            "confidence_ratio": pred.get("confidence_ratio", 0.0),
            "career_used": bool(pred.get("career_used", False)),
            "career_minutes": pred.get("career_minutes", 0.0),
            "career_goals": pred.get("career_goals", 0.0),
            "p_model_scorer": pred["p_scorer"],
            "p_model_assist": pred["p_assist"],
            "fair_odd_scorer": pred["odd_scorer"],
            "fair_odd_assist": pred["odd_assist"],
            "p_scorer_if_starter": pred.get("p_scorer_if_starter"),
            "p_assist_if_starter": pred.get("p_assist_if_starter"),
            "fair_odd_scorer_if_starter": pred.get("odd_scorer_if_starter"),
            "fair_odd_assist_if_starter": pred.get("odd_assist_if_starter"),
            "model_version": "t009_90min_theoretical",
            "pricing_mode": "90min_theoretical",
            # T017 — nouveaux champs traçabilité multi-source
            "odds_source": odds_source,
            "odds_mode": odds_mode,
            "betclic_odd_scorer": bc_scorer,
            "betclic_odd_assist": bc_assist,
            "edge_scorer": edge_scorer,
            "edge_assist": edge_assist,
            "outcome_scored": None,
            "outcome_assisted": None,
            "outcome_minutes_played": None,
            "enriched_at": None,
        })
    return lines


# ---------------------------------------------------------------------
# Pipeline principal V2
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="all",
                    help="Comma-separated slugs (default: all active in registry)")
    ap.add_argument("--days", type=int, default=2,
                    help="Nombre de jours à venir à scanner (default: 2)")
    ap.add_argument("--no-betclic", action="store_true",
                    help="Skip scraping Betclic")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche sans écrire dans forward_log.jsonl")
    ap.add_argument("--refresh-squads", action="store_true",
                    help="Force refetch squads BSD (bypass cache 24h)")
    ap.add_argument("--include-tier2", action="store_true",
                    help="Inclut les ligues Tier 2 (backup, données limitées)")
    ap.add_argument("--skip-pool-build", action="store_true",
                    help="Skip ligues sans pool pré-construit (au lieu de log warning)")
    args = ap.parse_args()

    _extend_top5_with_registry()

    # 1) Sélection ligues
    if args.leagues == "all":
        active = get_active_leagues(include_tier2=args.include_tier2)
    else:
        wanted = {s.strip() for s in args.leagues.split(",") if s.strip()}
        active = [c for c in LEAGUES.values() if c.slug in wanted]

    # On ne pipeline que les ligues ayant un BSD id (les pools sont buildés via BSD).
    # Les ligues sans BSD id (UECL) sont skippées avec un log explicite.
    active_with_bsd = [c for c in active if c.bsd_id]
    active_no_bsd = [c for c in active if not c.bsd_id]
    for c in active_no_bsd:
        log.warning("⏭ %s : pas d'id BSD — pipeline non supporté en V2 "
                    "(reportez-vous à la roadmap T018 StatsHub /performance)",
                    c.slug)

    if not active_with_bsd:
        log.error("Aucune ligue active avec BSD id — rien à faire.")
        return

    log.info("Pipeline V2 sur %d ligue(s) : %s",
             len(active_with_bsd),
             ", ".join(c.slug for c in active_with_bsd))

    today = date.today()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=args.days)).isoformat()

    # 2) Pools (1× par ligue) — réutilise pt.load_pool qui sait déjà cacher
    # Les ligues sans pool pré-construit déclenchent build (lent la 1ère fois).
    pools: dict[str, dict] = {}
    for cfg in active_with_bsd:
        pool_path = pt.DATA_DIR / f"{cfg.slug}_pool.json"
        if not pool_path.exists():
            if args.skip_pool_build:
                log.warning("⏭ %s : pool inexistant (%s) — skip", cfg.slug, pool_path.name)
                continue
            log.warning("⚠ %s : pool inexistant — il faudra lancer "
                        "`python live/build_player_pool.py --leagues %s` "
                        "(peut prendre plusieurs minutes la 1ère fois)",
                        cfg.slug, cfg.slug)
            continue
        try:
            pools[cfg.slug] = pt.load_pool(cfg.slug, refresh_squads=args.refresh_squads)
            log.info("Pool %s : %d joueurs", cfg.slug, len(pools[cfg.slug]))
        except Exception as e:
            log.exception("Pool %s : load_pool a échoué (%s)", cfg.slug, e)

    if not pools:
        log.error("Aucun pool chargé — rien à faire.")
        return

    # 3) Events upcoming (déduplication par event_id)
    all_events: list[tuple[dict, str]] = []
    seen_event_ids: set[int] = set()
    for cfg in active_with_bsd:
        if cfg.slug not in pools:
            continue
        try:
            evs = get_upcoming_events(cfg.bsd_id, date_from, date_to)
        except Exception as e:
            log.warning("BSD upcoming events %s a échoué : %s", cfg.slug, e)
            continue
        log.info("%s : %d matchs entre %s et %s", cfg.slug, len(evs), date_from, date_to)
        for ev in evs:
            try:
                eid = int(ev["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if eid in seen_event_ids:
                continue
            seen_event_ids.add(eid)
            all_events.append((ev, cfg.slug))

    if not all_events:
        log.info("Aucun match upcoming — rien à faire.")
        return

    # 4) Scrape Betclic pour les ligues qui ont un betclic_slug configuré
    betclic_by_slug: dict[str, list[dict]] = {}
    if not args.no_betclic:
        scrape_slugs = [
            cfg.slug for cfg in active_with_bsd
            if cfg.slug in pools and cfg.slug in pt.LEAGUE_TO_BETCLIC_KEY
        ]
        if scrape_slugs:
            try:
                betclic_by_slug = asyncio.run(pt.scrape_betclic_leagues(scrape_slugs))
            except Exception as e:
                log.warning("Scraping Betclic a échoué : %s — on continue sans odds book", e)

    # 5) Pipeline event par event
    candidate_lines: list[dict] = []
    for ev, slug in all_events:
        cfg = get_by_slug(slug)
        if cfg is None:
            continue
        bc_matches = betclic_by_slug.get(slug, [])
        try:
            lines = predict_one_event_v2(ev, slug, cfg, pools.get(slug, {}), bc_matches)
        except Exception as e:
            log.exception("Event %s : pipeline V2 error : %s", ev.get("id"), e)
            continue
        candidate_lines.extend(lines)
        if lines:
            log.info("Event %s (%s) : %d lignes (xG team %.2f - %.2f, %s, source=%s)",
                     ev.get("id"), slug, len(lines),
                     lines[0]["xg_team_home"], lines[0]["xg_team_away"],
                     lines[0]["lambdas_method"], lines[0].get("odds_source", "?"))

    if args.dry_run:
        log.info("DRY-RUN : %d lignes candidates (non écrites)", len(candidate_lines))
        for ln in candidate_lines[:3]:
            print(json.dumps(ln, indent=2, ensure_ascii=False))
        return

    if not candidate_lines:
        log.info("Aucune ligne candidate.")
        return

    # 6) Écriture atomique sous lock — réutilise EXACTEMENT la logique de
    # purge orphelins / upsert pré-kickoff de predict_today.main pour rester
    # compatible avec les invariants du forward_log.
    with log_lock(FORWARD_LOG_LOCK, timeout=30.0):
        rows, index = pt.load_existing_log()

        fresh_by_event: dict[int, set[int]] = {}
        local_seen: set[tuple[int, int]] = set()
        deduped: list[dict] = []
        for ln in candidate_lines:
            key = (int(ln["event_id"]), int(ln["player_id"]))
            if key in local_seen:
                continue
            local_seen.add(key)
            fresh_by_event.setdefault(int(ln["event_id"]), set()).add(int(ln["player_id"]))
            deduped.append(ln)

        MIN_FRESH_PLAYERS_TO_PURGE = 10
        events_safe_to_purge = {
            eid for eid, pids in fresh_by_event.items()
            if len(pids) >= MIN_FRESH_PLAYERS_TO_PURGE
        }

        n_purged = 0
        kept_rows: list[dict] = []
        for r in rows:
            try:
                eid = int(r.get("event_id"))
                pid = int(r.get("player_id"))
            except (TypeError, ValueError):
                kept_rows.append(r)
                continue
            if eid in events_safe_to_purge \
                    and pid not in fresh_by_event[eid] \
                    and r.get("outcome_scored") is None:
                n_purged += 1
                continue
            kept_rows.append(r)
        rows = kept_rows
        index = {(int(r["event_id"]), int(r["player_id"])): i
                 for i, r in enumerate(rows)
                 if r.get("event_id") is not None and r.get("player_id") is not None}

        n_protected = n_upserted = n_inserted = 0
        for ln in deduped:
            key = (int(ln["event_id"]), int(ln["player_id"]))
            if key in index:
                existing = rows[index[key]]
                if existing.get("outcome_scored") is not None:
                    n_protected += 1
                    continue
                rows[index[key]] = ln
                n_upserted += 1
            else:
                index[key] = len(rows)
                rows.append(ln)
                n_inserted += 1

        if not (n_upserted or n_inserted or n_purged):
            log.info("Forward log inchangé (%d candidates protégées post-match).",
                     n_protected)
            return

        tmp_path = FORWARD_LOG.with_suffix(".jsonl.tmp")
        with tmp_path.open("w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp_path.replace(FORWARD_LOG)
        log.info("✅ Forward log V2 : +%d insertions, %d upserts, %d purgés, %d protégées.",
                 n_inserted, n_upserted, n_purged, n_protected)


if __name__ == "__main__":
    main()
