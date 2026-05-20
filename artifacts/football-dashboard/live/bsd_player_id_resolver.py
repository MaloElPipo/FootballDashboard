"""Resolveur Sofascore player_id -> BSD player_id (cote prod).

Le forward log stocke historiquement des IDs Sofascore. Pour pouvoir migrer la
collecte de stats joueurs vers BSD getPlayerStats sans dependre du labo, on
resout l'ID BSD a l'ecriture (predict_today / predict_today_v2) et on backfill
les lignes existantes via `backfill_bsd_player_id.py`.

Strategie :
  1. Lookup dans le cache disque local `live/data/bsd_player_id_cache.json`
  2. Sinon, lookup dans le cache labo `lab/data/player_id_mapping.json` (s'il
     est present a cote du repo) pour beneficier de la couverture deja resolue
  3. Sinon, appel `players/?search=<name>` BSD et persistance dans le cache
     local

Toutes les erreurs reseau sont catchees : on n'echoue jamais l'ecriture du
forward log si BSD ne repond pas, on stocke simplement `bsd_player_id=None`.
"""
from __future__ import annotations

import json
import os
import threading
import unicodedata
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_PATH = DATA_DIR / "bsd_player_id_cache.json"

# Cache labo (lecture seule, fallback de couverture historique).
# parents : [0]=live, [1]=football-dashboard, [2]=artifacts, [3]=repo root.
_LAB_CACHE_PATH = (
    Path(__file__).resolve().parents[2] / "football-lab" / "lab" / "data" / "player_id_mapping.json"
)

BSD_BASE = "https://sports.bzzoiro.com/api"
DEFAULT_TIMEOUT = 15

_LOCK = threading.Lock()
_LAB_CACHE_MEM: dict[str, dict[str, Any]] | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Cache disque local
# ─────────────────────────────────────────────────────────────────────────────


def _load_cache() -> dict[str, dict[str, Any]]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(CACHE_PATH)


def _load_lab_cache() -> dict[str, dict[str, Any]]:
    global _LAB_CACHE_MEM
    if _LAB_CACHE_MEM is not None:
        return _LAB_CACHE_MEM
    if not _LAB_CACHE_PATH.exists():
        _LAB_CACHE_MEM = {}
        return _LAB_CACHE_MEM
    try:
        _LAB_CACHE_MEM = json.loads(_LAB_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        _LAB_CACHE_MEM = {}
    return _LAB_CACHE_MEM


# ─────────────────────────────────────────────────────────────────────────────
# Normalisation noms
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(name: str) -> str:
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def _name_matches(query: str, candidate: str) -> bool:
    q, c = _normalize(query), _normalize(candidate)
    if not q or not c:
        return False
    if q == c:
        return True
    qp, cp = set(q.split()), set(c.split())
    if not qp or not cp:
        return False
    return qp.issubset(cp) or cp.issubset(qp)


# ─────────────────────────────────────────────────────────────────────────────
# Recherche BSD
# ─────────────────────────────────────────────────────────────────────────────


def _bsd_headers() -> dict[str, str] | None:
    key = os.environ.get("BSD_API_KEY", "")
    if not key:
        return None
    return {"Authorization": f"Token {key}"}


def _search_bsd(name: str, team_id: int | None) -> list[dict[str, Any]]:
    headers = _bsd_headers()
    if headers is None:
        return []
    params: dict[str, Any] = {"search": name}
    if team_id is not None:
        params["team"] = team_id
    for ep in ("v2/players/", "players/"):
        try:
            r = requests.get(
                f"{BSD_BASE}/{ep}",
                params=params,
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            data = r.json()
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


def resolve_bsd_player_id(
    sofascore_id: int | None,
    name: str | None,
    team_id: int | None = None,
    *,
    allow_network: bool = True,
) -> int | None:
    """Resout l'ID BSD pour un joueur. Retourne None si introuvable / erreur.

    Cache local > cache labo > recherche BSD (si `allow_network`).
    """
    if sofascore_id is None:
        return None
    key = str(int(sofascore_id))

    with _LOCK:
        cache = _load_cache()
        if key in cache:
            return cache[key].get("bsd_player_id")

    lab_cache = _load_lab_cache()
    if key in lab_cache:
        bsd_id = lab_cache[key].get("bsd_player_id")
        record = {
            "sofascore_id": int(sofascore_id),
            "name": name,
            "team_id": team_id,
            "bsd_player_id": int(bsd_id) if bsd_id is not None else None,
            "matched_name": lab_cache[key].get("matched_name"),
            "status": lab_cache[key].get("status") or ("resolved" if bsd_id else "not_found"),
            "source": "lab_cache",
        }
        with _LOCK:
            cache = _load_cache()
            cache[key] = record
            _save_cache(cache)
        return record["bsd_player_id"]

    if not allow_network or not name:
        return None

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
        rows = _search_bsd(name, team_id)
    except Exception as e:
        record["status"] = "error"
        record["error"] = str(e)[:200]
        with _LOCK:
            cache = _load_cache()
            cache[key] = record
            _save_cache(cache)
        return None

    best = _pick_best(rows, name, team_id)
    if best is not None:
        bsd_id = best.get("id") or best.get("player_id")
        if bsd_id is not None:
            record["bsd_player_id"] = int(bsd_id)
            record["matched_name"] = best.get("name") or best.get("full_name")
            record["status"] = "resolved" if len(rows) <= 3 else "ambiguous"
    with _LOCK:
        cache = _load_cache()
        cache[key] = record
        _save_cache(cache)
    return record["bsd_player_id"]
