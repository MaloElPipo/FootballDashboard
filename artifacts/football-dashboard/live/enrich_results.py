"""Pour chaque ligne de forward_log.jsonl non-enrichie dont le match est fini,
récupère les vrais buteurs/passeurs via BSD player-stats et incidents, et écrit
les colonnes outcome_*.

Idempotent : ne re-traite jamais une ligne déjà enrichie.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PARENT = ROOT.parent
sys.path.insert(0, str(PARENT))

from live.bsd_helpers import get_event_detail, get_event_player_stats  # noqa: E402
from live.file_lock import log_lock, atomic_rewrite  # noqa: E402
from live.career_stats import (  # noqa: E402
    load_career_cache, save_cache, apply_event_increment,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("enrich_results")

FORWARD_LOG = DATA_DIR / "forward_log.jsonl"
FORWARD_LOG_LOCK = DATA_DIR / "forward_log.lock"


def _load_lines() -> list[dict]:
    out: list[dict] = []
    if not FORWARD_LOG.exists():
        return out
    with FORWARD_LOG.open() as f:
        for ln in f:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return out


def get_event_outcomes(event_id: int) -> dict[int, dict]:
    """Pour un match terminé, retourne {player_id: {scored, assisted, minutes_played}}.

    Source primaire : BSD player-stats (champs goals, goal_assist, minutes_played).
    Fallback secondaire si stats vides : incidents (champs goal_player, assist_player).
    """
    outcomes: dict[int, dict] = {}

    stats = get_event_player_stats(event_id)
    for s in stats:
        p = s.get("player")
        pid = p.get("id") if isinstance(p, dict) else p
        if pid is None:
            continue
        outcomes[int(pid)] = {
            "scored": (s.get("goals") or 0) > 0,
            "assisted": (s.get("goal_assist") or 0) > 0,
            "minutes_played": float(s.get("minutes_played") or 0),
            "source": "player_stats",
        }

    if not outcomes:
        # Fallback incidents
        detail = get_event_detail(event_id) or {}
        incidents = detail.get("incidents") or []
        scored_set, assisted_set = set(), set()
        for inc in incidents:
            if inc.get("incident_type") in ("goal", "Goal"):
                gp = inc.get("goal_player") or inc.get("player")
                if isinstance(gp, dict):
                    gp = gp.get("id")
                if gp:
                    scored_set.add(int(gp))
                ap = inc.get("assist_player") or inc.get("assist1_player")
                if isinstance(ap, dict):
                    ap = ap.get("id")
                if ap:
                    assisted_set.add(int(ap))
        for pid in scored_set | assisted_set:
            outcomes[pid] = {
                "scored": pid in scored_set,
                "assisted": pid in assisted_set,
                "minutes_played": None,
                "source": "incidents",
            }

    return outcomes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not FORWARD_LOG.exists():
        log.info("Pas de forward_log à enrichir.")
        return

    # 1. Snapshot initial (sans lock) — sert juste à identifier les events à enrichir
    snapshot = _load_lines()
    events_to_check: set[int] = set()
    for ln in snapshot:
        if not ln.get("enriched_at"):
            try:
                events_to_check.add(int(ln["event_id"]))
            except (KeyError, ValueError):
                continue

    if not events_to_check:
        log.info("Toutes les lignes sont déjà enrichies (%d lignes).", len(snapshot))
        return

    log.info("Events candidats à enrichir : %d", len(events_to_check))

    # 2. Fetch outcomes pour les matchs terminés (réseau, hors lock)
    outcomes_by_event: dict[int, dict[int, dict]] = {}
    for ev_id in events_to_check:
        detail = get_event_detail(ev_id) or {}
        if detail.get("status") not in ("finished", "Ended", "FINISHED"):
            continue
        out = get_event_outcomes(ev_id)
        if not out:
            log.warning("Event %s : aucun outcome récupéré (skip)", ev_id)
            continue
        outcomes_by_event[ev_id] = out

    if not outcomes_by_event:
        log.info("Aucun match nouvellement terminé.")
        return

    if args.dry_run:
        total = sum(
            1 for ln in snapshot
            if not ln.get("enriched_at") and int(ln["event_id"]) in outcomes_by_event
        )
        log.info("DRY-RUN : %d lignes seraient enrichies (%d events finis)",
                 total, len(outcomes_by_event))
        return

    # 3. Section critique : reload frais + apply + atomic rewrite, sous lock
    enriched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with log_lock(FORWARD_LOG_LOCK, timeout=30.0):
        lines = _load_lines()
        enriched_count = 0
        for ln in lines:
            if ln.get("enriched_at"):
                continue
            try:
                ev_id = int(ln["event_id"])
                pid = int(ln["player_id"])
            except (KeyError, ValueError):
                continue
            outcomes = outcomes_by_event.get(ev_id)
            if outcomes is None:
                continue
            o = outcomes.get(pid)
            if o is None:
                ln["outcome_scored"] = False
                ln["outcome_assisted"] = False
                ln["outcome_minutes_played"] = 0.0
            else:
                ln["outcome_scored"] = bool(o["scored"])
                ln["outcome_assisted"] = bool(o["assisted"])
                ln["outcome_minutes_played"] = o.get("minutes_played")
            ln["enriched_at"] = enriched_at
            enriched_count += 1

        if enriched_count == 0:
            log.info("Aucune ligne à enrichir au moment du lock.")
            return

        atomic_rewrite(
            FORWARD_LOG,
            [json.dumps(ln, ensure_ascii=False) for ln in lines],
        )
        log.info("✅ %d lignes enrichies dans %s (atomic rewrite)",
                 enriched_count, FORWARD_LOG)

    # 4. T005 — MAJ incrémentale carrière (sans re-fetcher : on a déjà les
    # outcomes_by_event, mais ils ne contiennent pas tous les joueurs du match.
    # On utilise donc get_event_player_stats à nouveau ; idempotent grâce à
    # events_seen côté career_stats).
    update_career_cache_for_finished_events(list(outcomes_by_event.keys()))


def update_career_cache_for_finished_events(event_ids: list[int]) -> None:
    """Pour chaque event terminé, ajoute les stats joueurs (minutes/goals/...)
    au cache career via `apply_event_increment` (idempotent par event_id).
    """
    if not event_ids:
        return
    cache = load_career_cache()
    if not cache:
        log.warning("MAJ carrière : cache absent (lance `python -m live.career_stats build`)")
        return

    total_updated = 0
    events_processed = 0
    for eid in event_ids:
        try:
            stats = get_event_player_stats(eid)
        except Exception as e:
            log.warning("MAJ carrière event=%s : fetch stats fail (%s)", eid, e)
            continue
        if not stats:
            continue
        n = apply_event_increment(cache, eid, stats)
        total_updated += n
        events_processed += 1

    if events_processed:
        save_cache(cache)
        log.info("✅ MAJ carrière : %d events traités, %d player-rows incrémentées",
                 events_processed, total_updated)


if __name__ == "__main__":
    main()
