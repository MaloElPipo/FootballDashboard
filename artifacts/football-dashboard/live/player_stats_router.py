"""Router stats joueur via StatsHub /performance + fallback Excel Maison.

Endpoint principal : `/api/player/{externalId}/performance?limit=200`
qui expose 47 stats par match × 3-4 saisons. Filtrable par tournamentId
domestique pour ne garder que les matchs du championnat (et exclure UCL/UEL,
qui jouent souvent un rôle parasite dans les agrégats).

Sortie de `get_player_stats(...)` :
    {
      "player_id": int,
      "external_id": int,
      "name": str,
      "league_slug": str,
      "season": str,
      "samples": int,                  # nb matchs trouvés
      "minutes_total": float,
      "goals_total": float,
      "assists_total": float,
      "xg_total": float,
      "xa_total": float,
      "shots_total": float,
      "shots_on_target_total": float,
      "key_pass_total": float,
      "xg_per_90": float,
      "xa_per_90": float,
      "goals_per_90": float,
      "assists_per_90": float,
      "shots_per_90": float,
      "shots_on_target_per_90": float,
      "avg_mins_when_starter": float,
      "starts": int,
      "matches_played": int,
      "source": "statshub" | "excel_fallback",
      "fetched_at": iso,
    }

Cache disque 24h (clé : externalId + utid + season).

Fallback Excel : si StatsHub vide, on tente le fichier maison
`Buteurs_Maison_4.1.xlsx` (déjà extrait dans `live/data/manual_positions.json`
+ stats annexes — l'Excel a goals/games par joueur, pas xG fin).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests

ROOT = Path(__file__).resolve().parent
_CACHE_DIR = ROOT / "data"
_CACHE_FILE = _CACHE_DIR / "player_stats_cache.json"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24h

STATSHUB_BASE = "https://www.statshub.com"
DEFAULT_TIMEOUT = 8

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": f"{STATSHUB_BASE}/",
}


# --------------------------------------------------------------------- cache

def _load_cache() -> dict[str, Any]:
    if not _CACHE_FILE.exists():
        return {}
    try:
        with _CACHE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict[str, Any]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(_CACHE_FILE.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, _CACHE_FILE)
    except Exception:
        pass


def _cache_get(key: str) -> dict | None:
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("fetched_ts", 0) > CACHE_TTL_SECONDS:
        return None
    return entry


def _cache_put(key: str, payload: dict) -> None:
    cache = _load_cache()
    payload = dict(payload)
    payload["fetched_ts"] = time.time()
    cache[key] = payload
    _save_cache(cache)


# --------------------------------------------------------------------- HTTP helper

def _get(path: str) -> dict | list | None:
    try:
        r = requests.get(STATSHUB_BASE + path, headers=_HEADERS, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return None
        if "json" not in r.headers.get("content-type", ""):
            return None
        return r.json()
    except Exception:
        return None


# --------------------------------------------------------------------- StatsHub /performance

# Mapping des clés statistiques retournées par StatsHub (47 stats observées).
# Documenté dans .local/notes/statshub-mapping-2026-04-27.md.
_SH_STAT_FIELDS = {
    "minutes_played": "minutesPlayed",
    "goals": "goals",
    "assists": "assists",
    "expected_goals": "expectedGoals",
    "expected_assists": "expectedAssists",
    "total_shots": "totalShots",
    "shots_on_target": "shotsOnTarget",
    "key_pass": "keyPasses",
}


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _aggregate_performance_payload(payload: dict, tournament_id: int | None,
                                   season_id: int | None) -> dict:
    """Réduit un payload `/performance` à un dict d'agrégats compatibles avec
    le format de `aggregate_player_pool`.

    Si tournament_id fourni → ne garde que les matchs de ce tournoi.
    Si season_id fourni → idem pour la saison.
    """
    matches = []
    if isinstance(payload, dict):
        # Plusieurs formats observés : performance.matches OU performance.events
        # OU directement une liste sous "matches".
        for key in ("matches", "events", "performance", "data"):
            blk = payload.get(key)
            if isinstance(blk, dict):
                for sub in ("matches", "events", "data"):
                    if isinstance(blk.get(sub), list):
                        matches = blk[sub]
                        break
                if matches:
                    break
            elif isinstance(blk, list):
                matches = blk
                break

    if not matches:
        # Format alternatif : payload est lui-même la liste
        matches = payload if isinstance(payload, list) else []

    samples = 0
    minutes_total = 0.0
    goals_total = 0.0
    assists_total = 0.0
    xg_total = 0.0
    xa_total = 0.0
    shots_total = 0.0
    shots_on_target_total = 0.0
    key_pass_total = 0.0
    starts = 0
    starter_minutes_sum = 0.0

    for m in matches:
        if not isinstance(m, dict):
            continue
        # Filtre tournoi si demandé
        if tournament_id is not None:
            mt_id = (
                m.get("tournamentId")
                or (m.get("tournament") or {}).get("uniqueTournamentId")
                or (m.get("tournament") or {}).get("id")
            )
            if mt_id and int(mt_id) != int(tournament_id):
                continue
        if season_id is not None:
            ms_id = m.get("seasonId") or (m.get("season") or {}).get("id")
            if ms_id and int(ms_id) != int(season_id):
                continue

        stats = m.get("statistics") or m.get("stats") or m
        mins = _safe_float(
            stats.get(_SH_STAT_FIELDS["minutes_played"])
            or stats.get("minutes_played")
        )
        if mins <= 0:
            continue

        samples += 1
        minutes_total += mins
        if mins >= 60:
            starts += 1
            starter_minutes_sum += mins

        goals_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["goals"]) or stats.get("goals")
        )
        assists_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["assists"])
            or stats.get("goal_assist")
            or stats.get("assists")
        )
        xg_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["expected_goals"])
            or stats.get("expected_goals")
        )
        xa_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["expected_assists"])
            or stats.get("expected_assists")
        )
        shots_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["total_shots"])
            or stats.get("total_shots")
        )
        shots_on_target_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["shots_on_target"])
            or stats.get("shots_on_target")
        )
        key_pass_total += _safe_float(
            stats.get(_SH_STAT_FIELDS["key_pass"]) or stats.get("key_pass")
        )

    if minutes_total > 0:
        factor = 90.0 / minutes_total
        xg_per_90 = xg_total * factor
        xa_per_90 = xa_total * factor
        goals_per_90 = goals_total * factor
        assists_per_90 = assists_total * factor
        shots_per_90 = shots_total * factor
        shots_on_target_per_90 = shots_on_target_total * factor
    else:
        xg_per_90 = xa_per_90 = goals_per_90 = assists_per_90 = 0.0
        shots_per_90 = shots_on_target_per_90 = 0.0

    avg_mins_when_starter = (
        starter_minutes_sum / starts if starts > 0 else 85.0
    )

    return {
        "samples": samples,
        "minutes_total": minutes_total,
        "matches_played": samples,
        "starts": starts,
        "goals_total": goals_total,
        "assists_total": assists_total,
        "xg_total": xg_total,
        "xa_total": xa_total,
        "shots_total": shots_total,
        "shots_on_target_total": shots_on_target_total,
        "key_pass_total": key_pass_total,
        "xg_per_90": xg_per_90,
        "xa_per_90": xa_per_90,
        "goals_per_90": goals_per_90,
        "assists_per_90": assists_per_90,
        "shots_per_90": shots_per_90,
        "shots_on_target_per_90": shots_on_target_per_90,
        "avg_mins_when_starter": avg_mins_when_starter,
    }


# --------------------------------------------------------------------- public API

def get_player_stats(
    player_external_id: int,
    league_slug: str,
    statshub_utid: int | None,
    season_id: int | None = None,
    player_name: str | None = None,
) -> dict | None:
    """Récupère les stats roulées d'un joueur via StatsHub /performance,
    filtrées sur son championnat domestique (`statshub_utid`).

    Retourne None si :
      - external_id invalide
      - StatsHub renvoie 404 / vide
      - aucun match trouvé dans le tournoi demandé

    L'appelant doit alors basculer sur le fallback (Excel maison ou squad BSD).
    """
    if not player_external_id:
        return None

    cache_key = f"{int(player_external_id)}:{statshub_utid or 'all'}:{season_id or 'all'}"
    cached = _cache_get(cache_key)
    if cached:
        if cached.get("samples", 0) > 0 or cached.get("_negative"):
            return cached if not cached.get("_negative") else None

    payload = _get(f"/api/player/{int(player_external_id)}/performance?limit=200")
    if payload is None:
        # Cache négatif court (24h reste raisonnable, 404 stable)
        _cache_put(cache_key, {"_negative": True, "samples": 0})
        return None

    agg = _aggregate_performance_payload(payload, statshub_utid, season_id)
    if agg["samples"] == 0:
        _cache_put(cache_key, {"_negative": True, "samples": 0})
        return None

    result = {
        "external_id": int(player_external_id),
        "name": player_name,
        "league_slug": league_slug,
        "statshub_utid": statshub_utid,
        "season_id": season_id,
        "source": "statshub",
        **agg,
    }
    _cache_put(cache_key, result)
    return result


def get_player_stats_with_fallback(
    player_external_id: int | None,
    league_slug: str,
    statshub_utid: int | None,
    excel_pool: dict | None = None,
    player_name: str | None = None,
    season_id: int | None = None,
) -> dict | None:
    """Variante avec fallback : si StatsHub n'a rien, tente l'Excel maison.

    `excel_pool` : dict {(name_lower, country): {"goals":..., "assists":..., "minutes":...}}
    pré-extrait par `live/extract_manual_positions.py` (ou un nouveau script
    dédié `extract_excel_player_stats.py`).
    """
    res = None
    if player_external_id:
        res = get_player_stats(
            player_external_id, league_slug, statshub_utid,
            season_id=season_id, player_name=player_name,
        )
    if res is not None:
        return res

    # Fallback Excel maison
    if excel_pool and player_name:
        key = player_name.lower().strip()
        entry = excel_pool.get(key)
        if entry and entry.get("minutes_total", 0) > 0:
            mins = entry["minutes_total"]
            factor = 90.0 / mins
            return {
                "external_id": None,
                "name": player_name,
                "league_slug": league_slug,
                "statshub_utid": statshub_utid,
                "season_id": season_id,
                "source": "excel_fallback",
                "samples": entry.get("matches_played", 0),
                "minutes_total": mins,
                "matches_played": entry.get("matches_played", 0),
                "starts": entry.get("starts", 0),
                "goals_total": entry.get("goals", 0.0),
                "assists_total": entry.get("assists", 0.0),
                "xg_total": entry.get("xg", entry.get("goals", 0.0)),
                "xa_total": entry.get("xa", entry.get("assists", 0.0)),
                "shots_total": entry.get("shots", 0.0),
                "shots_on_target_total": entry.get("shots_on_target", 0.0),
                "key_pass_total": entry.get("key_pass", 0.0),
                "xg_per_90": entry.get("xg", entry.get("goals", 0.0)) * factor,
                "xa_per_90": entry.get("xa", entry.get("assists", 0.0)) * factor,
                "goals_per_90": entry.get("goals", 0.0) * factor,
                "assists_per_90": entry.get("assists", 0.0) * factor,
                "shots_per_90": entry.get("shots", 0.0) * factor,
                "shots_on_target_per_90": entry.get("shots_on_target", 0.0) * factor,
                "avg_mins_when_starter": 85.0,
            }
    return None
