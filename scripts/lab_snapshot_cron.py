"""Cron bi-quotidien — snapshot des cotes Pinnacle pour le forward log ouvert (Phase 5).

Usage:
    python scripts/lab_snapshot_cron.py [--markets 1x2,over_under_25,btts]
                                        [--limit N] [--alert-threshold 50]

Variables d'env requises:
    BSD_API_KEY     clef API BSD (cotes compareOdds)

Sortie:
    - append-only dans artifacts/football-lab/lab/data/movement_history.jsonl
    - logs lisibles GH Actions (groupes, comptes OK / KO)
    - exit code 0 normalement
    - exit code 2 si > N events ouverts n'ont reçu aucun snapshot sur la
      fenêtre 24h (alerte sharp tracker cassé)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Permet d'importer `lab.calibration.*` depuis n'importe quel cwd
REPO_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = REPO_ROOT / "artifacts" / "football-lab"
PROD_DIR = REPO_ROOT / "artifacts" / "football-dashboard"
sys.path.insert(0, str(LAB_ROOT))

from lab.calibration import track_movement as TM  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("lab_snapshot_cron")


def _events_recently_snapshotted(within_hours: int) -> set[int]:
    """event_ids vus dans movement_history.jsonl sur la fenêtre [now - within_hours, now]."""
    if not TM.HISTORY_PATH.exists():
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    seen: set[int] = set()
    with TM.HISTORY_PATH.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("snapshot_at", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt >= cutoff:
                eid = rec.get("event_id")
                if eid is not None:
                    try:
                        seen.add(int(eid))
                    except (TypeError, ValueError):
                        continue
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--markets",
        default="1x2",
        help="Marchés à snapshot (CSV). Défaut: 1x2",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limite max d'events à snapshot (0 = tous les events ouverts)",
    )
    parser.add_argument(
        "--alert-threshold",
        type=int,
        default=50,
        help="Alerte (exit 2) si > N events ouverts sans snapshot sur 24h",
    )
    args = parser.parse_args()

    if not os.environ.get("BSD_API_KEY"):
        log.error("BSD_API_KEY manquant — abandon")
        return 1

    markets = [m.strip() for m in args.markets.split(",") if m.strip()]
    log.info("Markets: %s | alerte threshold: %d", markets, args.alert_threshold)

    open_events = TM.load_open_forward_log_events(PROD_DIR)
    log.info("Forward log ouvert: %d events", len(open_events))
    if not open_events:
        log.warning("Aucun event ouvert — rien à snapshot")
        return 0

    targets = open_events if args.limit <= 0 else open_events[: args.limit]
    log.info("Snapshot ciblé sur %d events", len(targets))

    ok_events = 0
    ko_events = 0
    total_rows = 0

    for i, eid in enumerate(targets, start=1):
        wrote_any = False
        for market in markets:
            try:
                recs = TM.snapshot_event_odds(eid, market=market)
            except Exception as exc:  # noqa: BLE001
                log.warning("event=%s market=%s ERREUR %s", eid, market, exc)
                continue
            if not recs:
                continue
            n = TM.append_snapshot(recs)
            total_rows += n
            wrote_any = True
            log.info("[%d/%d] event=%s market=%s -> %d lignes",
                     i, len(targets), eid, market, n)
        if wrote_any:
            ok_events += 1
        else:
            ko_events += 1

    log.info(
        "Bilan: %d events OK / %d KO / %d lignes écrites",
        ok_events, ko_events, total_rows,
    )

    # Alerte: combien d'events ouverts n'ont *aucun* snapshot sur 24h glissantes ?
    recently = _events_recently_snapshotted(within_hours=24)
    stale = [eid for eid in open_events if eid not in recently]
    log.info(
        "Events ouverts sans snapshot < 24h: %d (sur %d ouverts)",
        len(stale), len(open_events),
    )
    if len(stale) > args.alert_threshold:
        log.error(
            "ALERTE sharp tracker: %d events ouverts sans snapshot 24h (> seuil %d). "
            "Exemples: %s",
            len(stale), args.alert_threshold, stale[:10],
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
