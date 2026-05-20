"""Wrapper BSD API avec cache disque TTL.

Utilisé uniquement par le labo. Ne touche jamais au cache prod.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

BSD_BASE = "https://sports.bzzoiro.com/api"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "bsd_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_TTL = 24 * 3600


def _headers() -> dict[str, str]:
    key = os.environ.get("BSD_API_KEY", "")
    if not key:
        raise RuntimeError("BSD_API_KEY manquant dans l'environnement")
    return {"Authorization": f"Token {key}"}


def _cache_path(endpoint: str, params: dict[str, Any] | None) -> Path:
    payload = json.dumps({"e": endpoint, "p": params or {}}, sort_keys=True)
    digest = hashlib.sha1(payload.encode()).hexdigest()[:16]
    safe = endpoint.replace("/", "_").strip("_")
    return CACHE_DIR / f"{safe}_{digest}.json"


def bsd_get(
    endpoint: str,
    params: dict[str, Any] | None = None,
    ttl: int = DEFAULT_TTL,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """GET sur l'API BSD avec cache disque TTL.

    Args:
        endpoint: chemin relatif (ex: 'v2/standings/', 'v2/odds/compare/')
        params: query params
        ttl: secondes avant invalidation cache (24h par defaut)
        force_refresh: bypasser le cache pour recharger
    """
    cache_file = _cache_path(endpoint, params)
    if cache_file.exists() and not force_refresh:
        age = time.time() - cache_file.stat().st_mtime
        if age < ttl:
            return json.loads(cache_file.read_text())

    url = f"{BSD_BASE}/{endpoint.lstrip('/')}"
    resp = requests.get(url, headers=_headers(), params=params or {}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    cache_file.write_text(json.dumps(data, ensure_ascii=False))
    return data


def cache_stats() -> dict[str, Any]:
    """Stats simples sur le cache disque pour affichage labo."""
    files = list(CACHE_DIR.glob("*.json"))
    total_bytes = sum(f.stat().st_size for f in files)
    ages = [time.time() - f.stat().st_mtime for f in files]
    return {
        "count": len(files),
        "size_kb": round(total_bytes / 1024, 1),
        "oldest_hours": round(max(ages) / 3600, 1) if ages else 0,
        "newest_hours": round(min(ages) / 3600, 1) if ages else 0,
    }


def clear_cache() -> int:
    """Vide le cache labo. Retourne le nombre de fichiers supprimes."""
    files = list(CACHE_DIR.glob("*.json"))
    for f in files:
        f.unlink()
    return len(files)
