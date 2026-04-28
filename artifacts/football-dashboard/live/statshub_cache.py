"""Reader pour le cache StatsHub massif construit par `build_statshub_cache.py`.

Lecture purement disque (zéro réseau). Utilisé par `predict_today_v2` pour
servir les stats joueur sans rappel StatsHub.

Layout cache :
    live/data/statshub_players_index.json
        → { "<bsd_player_id>": { sh_external_id, sh_internal_id, sh_slug,
                                  sh_country_slug, sh_name, last_resolved_ts,
                                  resolution_score, source_squad_league } }
    live/data/statshub_performance/<external_id>.json
        → raw payload de /api/player/{id}/performance?limit=200

Garde-fous :
- Aucun appel réseau dans ce module
- Aucun import de predict_today / g2_engine / model 4.1
- Retourne None proprement si cache miss
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
_DATA_DIR = ROOT / "data"
_INDEX_FILE = _DATA_DIR / "statshub_players_index.json"
_PERF_DIR = _DATA_DIR / "statshub_performance"


# --------------------------------------------------------------------- index

@lru_cache(maxsize=1)
def _load_index() -> dict[str, dict]:
    if not _INDEX_FILE.exists():
        return {}
    try:
        with _INDEX_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def reload_index() -> None:
    """Force re-read of the index file (after a builder run)."""
    _load_index.cache_clear()


def get_external_id_for_bsd_player(bsd_player_id: int | str) -> int | None:
    """Returns the StatsHub external id for a given BSD player id, or None."""
    idx = _load_index()
    entry = idx.get(str(bsd_player_id))
    if not entry:
        return None
    return entry.get("sh_external_id")


def get_index_entry(bsd_player_id: int | str) -> dict | None:
    """Returns the full index entry (with resolution score, country, etc.)."""
    return _load_index().get(str(bsd_player_id))


def index_size() -> int:
    return len(_load_index())


def index_summary() -> dict[str, Any]:
    idx = _load_index()
    resolved = sum(1 for e in idx.values() if e.get("sh_external_id"))
    by_league: dict[str, int] = {}
    for e in idx.values():
        lg = e.get("source_squad_league", "?")
        by_league[lg] = by_league.get(lg, 0) + 1
    return {
        "total_players": len(idx),
        "resolved": resolved,
        "unresolved": len(idx) - resolved,
        "by_league": by_league,
    }


# --------------------------------------------------------------------- performance

@lru_cache(maxsize=256)
def get_performance_raw(external_id: int) -> dict | None:
    """Loads the raw /performance payload for a StatsHub external id, or None.

    LRU-cached (maxsize=256) because this is a hot path during prediction
    runs where 22+ players per match are looked up. Cache files are only
    rewritten by the offline builder (`build_statshub_cache.py`), so reading
    a stale-in-process value is safe — call `reload_performance_cache()` if
    you ever need to invalidate it after a fresh build inside the same
    process.
    """
    if not external_id:
        return None
    fp = _PERF_DIR / f"{int(external_id)}.json"
    if not fp.exists():
        return None
    try:
        with fp.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def reload_performance_cache() -> None:
    """Force re-read of all cached performance payloads from disk."""
    get_performance_raw.cache_clear()


def has_performance(external_id: int) -> bool:
    if not external_id:
        return False
    return (_PERF_DIR / f"{int(external_id)}.json").exists()


def performance_count_on_disk() -> int:
    if not _PERF_DIR.exists():
        return 0
    return sum(1 for _ in _PERF_DIR.glob("*.json"))


# --------------------------------------------------------------------- aggregates

def aggregate_performance(
    external_id: int,
    tournament_utid: int | None = None,
    season_id: int | None = None,
) -> dict | None:
    """Aggregate cached performance, filtered by competition / season.

    Reuses `player_stats_router._aggregate_performance_payload` to avoid
    duplicating the agg logic.
    """
    payload = get_performance_raw(external_id)
    if payload is None:
        return None

    # Lazy import to avoid cycles
    from .player_stats_router import _aggregate_performance_payload

    return _aggregate_performance_payload(payload, tournament_utid, season_id)


def get_history_by_competition(
    external_id: int,
    competition_utids: list[int] | None = None,
) -> dict[int, dict]:
    """Returns {utid: aggregated_stats} for each competition the player has data in.

    If `competition_utids` is None, aggregates per *every* tournament found in
    the cached payload.
    """
    payload = get_performance_raw(external_id)
    if payload is None:
        return {}

    # Discover which tournaments are present
    found_utids: set[int] = set()
    matches: list[dict] = []
    if isinstance(payload, dict):
        for key in ("matches", "events", "performance", "data"):
            blk = payload.get(key)
            if isinstance(blk, list):
                matches = blk
                break
            if isinstance(blk, dict):
                for sub in ("matches", "events", "data"):
                    if isinstance(blk.get(sub), list):
                        matches = blk[sub]
                        break
                if matches:
                    break
    if not matches and isinstance(payload, list):
        matches = payload

    for m in matches:
        if not isinstance(m, dict):
            continue
        ut = (
            m.get("tournamentId")
            or (m.get("tournament") or {}).get("uniqueTournamentId")
            or (m.get("tournament") or {}).get("id")
            or (m.get("events") or {}).get("uniqueTournamentId")
        )
        if ut:
            try:
                found_utids.add(int(ut))
            except (TypeError, ValueError):
                pass

    targets = competition_utids or sorted(found_utids)
    out: dict[int, dict] = {}
    from .player_stats_router import _aggregate_performance_payload
    for utid in targets:
        agg = _aggregate_performance_payload(payload, utid, None)
        if agg.get("samples", 0) > 0:
            out[utid] = agg
    return out
