"""Backfill `bsd_player_id` dans les lignes historiques de `forward_log.jsonl`.

Pour chaque ligne sans `bsd_player_id`, on tente :
  1. Lookup cache local `live/data/bsd_player_id_cache.json`
  2. Lookup cache labo `lab/data/player_id_mapping.json`
  3. Recherche BSD `players/?search=<name>` (sauf si --offline)

Atomique sous file lock, idempotent : ne touche jamais aux lignes deja
enrichies (`bsd_player_id` deja present, meme null si --keep-null).

Usage :
    python -m live.backfill_bsd_player_id [--offline] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PARENT = ROOT.parent
sys.path.insert(0, str(PARENT))

from live.bsd_player_id_resolver import resolve_bsd_player_id  # noqa: E402
from live.file_lock import log_lock, atomic_rewrite  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("backfill_bsd_player_id")

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true",
                    help="Ne pas appeler BSD : utilise uniquement les caches disque.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not FORWARD_LOG.exists():
        log.info("Pas de forward_log a backfiller.")
        return

    # 1. Snapshot pour identifier les player_id a resoudre (1x par sofa_id).
    snapshot = _load_lines()
    todo: dict[int, dict] = {}
    for ln in snapshot:
        if "bsd_player_id" in ln and ln["bsd_player_id"] is not None:
            continue
        pid = ln.get("player_id")
        if pid is None:
            continue
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_int in todo:
            continue
        todo[pid_int] = {
            "name": ln.get("player_name"),
            "team_id": ln.get("team_id"),
        }

    if not todo:
        log.info("Toutes les lignes ont deja un bsd_player_id (%d lignes).", len(snapshot))
        return

    log.info("Joueurs distincts a resoudre : %d", len(todo))

    # 2. Resolution (hors lock, network OK).
    resolved: dict[int, int | None] = {}
    for sofa_id, meta in todo.items():
        bsd_id = resolve_bsd_player_id(
            sofa_id, meta["name"], meta["team_id"],
            allow_network=not args.offline,
        )
        resolved[sofa_id] = bsd_id

    n_found = sum(1 for v in resolved.values() if v is not None)
    log.info("Mapping : %d/%d resolus", n_found, len(resolved))

    if args.dry_run:
        sample = [(s, b) for s, b in list(resolved.items())[:10]]
        log.info("DRY-RUN sample : %s", sample)
        return

    # 3. Reload frais sous lock, applique et rewrite atomiquement.
    with log_lock(FORWARD_LOG_LOCK, timeout=30.0):
        lines = _load_lines()
        n_touched = 0
        per_status: dict[str, int] = defaultdict(int)
        for ln in lines:
            if "bsd_player_id" in ln and ln["bsd_player_id"] is not None:
                per_status["already"] += 1
                continue
            pid = ln.get("player_id")
            try:
                pid_int = int(pid) if pid is not None else None
            except (TypeError, ValueError):
                pid_int = None
            bsd_id = resolved.get(pid_int) if pid_int is not None else None
            ln["bsd_player_id"] = bsd_id
            n_touched += 1
            per_status["resolved" if bsd_id is not None else "null"] += 1

        if n_touched == 0:
            log.info("Aucune ligne a backfiller au moment du lock.")
            return

        atomic_rewrite(
            FORWARD_LOG,
            [json.dumps(ln, ensure_ascii=False) for ln in lines],
        )
        log.info("Backfill ecrit : %d lignes touchees (%s)",
                 n_touched, dict(per_status))


if __name__ == "__main__":
    main()
