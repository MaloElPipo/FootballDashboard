"""Construit / rafraîchit le pool joueurs pour les ligues Top 5.

Pour chaque ligue : récupère tous les matchs terminés de la saison en cours, puis
les stats joueur par match. Sauvegarde dans live/data/{league_slug}_pool.json
pour qu'`aggregate_player_pool` puisse être appelé sans re-télécharger.

Usage :
    python -m artifacts.football-dashboard.live.build_player_pool
    # ou directement :
    python live/build_player_pool.py [--leagues bundesliga,ligue_1] [--season-start 2025-08-01]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Permet d'importer depuis le parent (g2_engine, preview_player_odds)
sys.path.insert(0, str(ROOT.parent))

from live.bsd_helpers import (  # noqa: E402
    TOP5_LEAGUES,
    get_finished_events,
    fetch_events_player_stats_parallel,
)


def build_pool_for_league(slug: str, season_start: str, season_end: str) -> dict:
    cfg = TOP5_LEAGUES[slug]
    print(f"\n=== {cfg['name']} ({cfg['country']}) — saison {season_start} → {season_end} ===")
    t0 = time.time()

    print("  [1/2] Liste des matchs terminés...")
    events = get_finished_events(cfg["bsd_id"], season_start, season_end)
    print(f"        {len(events)} matchs terminés")
    if not events:
        return {"league": cfg["name"], "events": {}, "by_event_stats": {}}

    matches_by_id = {str(e["id"]): e for e in events}

    print(f"  [2/2] Stats joueurs par match (parallèle x12)...")
    event_ids = [e["id"] for e in events]
    stats_by_eid = fetch_events_player_stats_parallel(event_ids, max_workers=12)
    total_rows = sum(len(v) for v in stats_by_eid.values())
    print(f"        {total_rows} lignes stats récupérées en {time.time() - t0:.1f}s")

    return {
        "league": cfg["name"],
        "league_id": cfg["bsd_id"],
        "season_start": season_start,
        "season_end": season_end,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_matches": len(events),
        "n_stat_rows": total_rows,
        "events": matches_by_id,
        "by_event_stats": {
            str(eid): {"event_id": eid, "stats": rows}
            for eid, rows in stats_by_eid.items()
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="all",
                    help="Comma-separated slugs (default: all top 5)")
    ap.add_argument("--season-start", default="2025-08-01")
    ap.add_argument("--season-end", default="2026-06-30")
    args = ap.parse_args()

    if args.leagues == "all":
        slugs = list(TOP5_LEAGUES.keys())
    else:
        slugs = [s.strip() for s in args.leagues.split(",")]

    for slug in slugs:
        if slug not in TOP5_LEAGUES:
            print(f"⚠️ Ligue inconnue : {slug} (skip)")
            continue
        pool = build_pool_for_league(slug, args.season_start, args.season_end)
        out_path = DATA_DIR / f"{slug}_pool.json"
        out_path.write_text(json.dumps(pool, ensure_ascii=False))
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"✅ {out_path.name} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
