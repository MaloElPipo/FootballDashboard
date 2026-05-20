"""Mapping Sofascore player_id -> BSD player_id.

Le forward log prod stocke des IDs Sofascore. La Phase 4 du labo a besoin de
l'ID BSD equivalent pour comparer les stats. Ce module resout (nom + club) ->
bsd_player_id via l'endpoint BSD `players/?search=...` et cache le mapping sur
disque dans `lab/data/player_id_mapping.json`.

Le mapping est volontairement simple : pas d'overrides manuels ni de fuzzy
matching aggressif. On normalise les accents, on filtre par team_id BSD si
fourni, sinon on prend le meilleur match exact sur le nom. Les echecs sont
traces avec une raison pour pouvoir auditer la couverture.
"""
from __future__ import annotations

import json
import threading
import unicodedata
from pathlib import Path
from typing import Any

from . import bsd_client


CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "player_id_mapping.json"
_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Cache disque
# ─────────────────────────────────────────────────────────────────────────────


def _load_cache() -> dict[str, dict[str, Any]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(CACHE_PATH)


def load_mapping() -> dict[str, dict[str, Any]]:
    """Renvoie une copie du mapping cache (clef = str(sofascore_id))."""
    with _LOCK:
        return dict(_load_cache())


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation noms
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_ = "".join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_.lower().strip()


def _name_matches(query: str, candidate: str) -> bool:
    q = _normalize(query)
    c = _normalize(candidate)
    if not q or not c:
        return False
    if q == c:
        return True
    q_parts = set(q.split())
    c_parts = set(c.split())
    if not q_parts or not c_parts:
        return False
    return q_parts.issubset(c_parts) or c_parts.issubset(q_parts)


# ─────────────────────────────────────────────────────────────────────────────
# Recherche BSD
# ─────────────────────────────────────────────────────────────────────────────


def _search_bsd(name: str, team_id: int | None = None) -> list[dict[str, Any]]:
    """Appel `players/?search=<nom>` (+ team filter optionnel)."""
    params: dict[str, Any] = {"search": name}
    if team_id is not None:
        params["team"] = team_id
    candidates = [
        "v2/players/",
        "players/",
    ]
    for ep in candidates:
        try:
            data = bsd_client.bsd_get(ep, params=params)
        except Exception:
            continue
        rows = _extract_players(data)
        if rows:
            return rows
    return []


def _extract_players(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("results", "players", "data", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def _pick_best(rows: list[dict[str, Any]], name: str, team_id: int | None) -> dict[str, Any] | None:
    if not rows:
        return None
    name_hits = [r for r in rows if _name_matches(name, r.get("name") or r.get("full_name") or "")]
    pool = name_hits or rows
    if team_id is not None:
        team_hits = [
            r for r in pool
            if int((r.get("team") or {}).get("id", 0) or r.get("team_id") or 0) == int(team_id)
        ]
        if team_hits:
            return team_hits[0]
    return pool[0] if name_hits else None


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────


def resolve_player(
    sofascore_id: int,
    name: str,
    team_id: int | None = None,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Resout le BSD player_id pour un joueur du forward log.

    Retourne un dict {bsd_player_id, source, status, ...}.
    status ∈ {"cached", "resolved", "ambiguous", "not_found", "error"}.
    Met a jour le cache disque.
    """
    key = str(int(sofascore_id))
    with _LOCK:
        cache = _load_cache()
        if not force_refresh and key in cache:
            entry = dict(cache[key])
            entry["source"] = "cache"
            return entry

    record: dict[str, Any] = {
        "sofascore_id": int(sofascore_id),
        "name": name,
        "team_id": team_id,
        "bsd_player_id": None,
        "matched_name": None,
        "status": "not_found",
        "source": "search",
    }
    try:
        rows = _search_bsd(name, team_id=team_id)
    except Exception as e:
        record["status"] = "error"
        record["error"] = str(e)[:200]
        return record

    best = _pick_best(rows, name, team_id)
    if best is None:
        record["status"] = "not_found"
        record["n_candidates"] = len(rows)
    else:
        bsd_id = best.get("id") or best.get("player_id")
        if bsd_id is None:
            record["status"] = "not_found"
        else:
            record["bsd_player_id"] = int(bsd_id)
            record["matched_name"] = best.get("name") or best.get("full_name")
            record["status"] = "resolved" if len(rows) <= 3 else "ambiguous"

    with _LOCK:
        cache = _load_cache()
        cache[key] = {k: v for k, v in record.items() if k != "source"}
        _save_cache(cache)
    return record


def resolve_many(players: list[dict[str, Any]], *, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Resout une liste de joueurs.

    `players` : [{player_id, name, team_id?}, ...] (player_id = Sofascore ID).
    """
    out = []
    for p in players:
        sofa = p.get("player_id") or p.get("sofascore_id")
        if sofa is None:
            continue
        out.append(
            resolve_player(
                int(sofa),
                str(p.get("name") or p.get("player_name") or ""),
                team_id=p.get("team_id"),
                force_refresh=force_refresh,
            )
        )
    return out


def coverage_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compte le taux de mapping reussi (status in {resolved, ambiguous, cached})."""
    n = len(records)
    resolved = sum(1 for r in records if r.get("bsd_player_id"))
    not_found = sum(1 for r in records if r.get("status") == "not_found")
    errors = sum(1 for r in records if r.get("status") == "error")
    return {
        "total": n,
        "resolved": resolved,
        "not_found": not_found,
        "errors": errors,
        "coverage_pct": round(100 * resolved / max(n, 1), 1),
    }
