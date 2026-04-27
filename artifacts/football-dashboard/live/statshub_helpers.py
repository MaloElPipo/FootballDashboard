"""StatsHub.com integration — read-only complement to BSD MCP.

Provides predicted team lineups (visual) and per-match data discovered via
exploration on 2026-04-27. See `.local/notes/statshub-mapping-2026-04-27.md`
for the full endpoint mapping.

Design contract:
- READ-ONLY: never modifies BSD pipeline, model 4.1, or Betclic scraping.
- GRACEFUL FALLBACK: every public function returns None / empty on any error;
  the UI must keep working if StatsHub is down.
- CACHE: local JSON cache (TTL 30 min) keyed by BSD event id to avoid
  hammering StatsHub.
- NO AUTH: StatsHub exposes a public JSON API; no key required.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://www.statshub.com"
DEFAULT_TIMEOUT = 8
CACHE_TTL_SECONDS = 30 * 60  # 30 minutes
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": f"{BASE_URL}/",
}

# Cache file lives next to manual_positions.json (live/data/)
_CACHE_DIR = Path(__file__).parent / "data"
_CACHE_FILE = _CACHE_DIR / "statshub_match_cache.json"

# Top 5 league mapping: BSD slug → StatsHub uniqueTournamentId
LEAGUE_MAP_BSD_TO_STATSHUB_UTID: dict[str, int] = {
    "premier_league": 17,
    "la_liga": 8,
    "serie_a": 23,
    "bundesliga": 35,
    "ligue_1": 34,
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
    """Best-effort write — uses tmp+rename for atomicity. Cache failure is never fatal."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(_CACHE_FILE.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CACHE_FILE)
    except Exception:
        pass


def _cache_get(key: str) -> dict | None:
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("_fetched_at", 0) > CACHE_TTL_SECONDS:
        return None
    return entry


def _cache_put(key: str, payload: dict) -> None:
    cache = _load_cache()
    payload = dict(payload)
    payload["_fetched_at"] = time.time()
    cache[key] = payload
    _save_cache(cache)


# --------------------------------------------------------------------- HTTP

def _get(path: str) -> dict | list | None:
    """Safe GET returning JSON or None on any error."""
    try:
        r = requests.get(BASE_URL + path, headers=_HEADERS, timeout=DEFAULT_TIMEOUT)
        if r.status_code != 200:
            return None
        ct = r.headers.get("content-type", "")
        if "json" not in ct:
            return None
        return r.json()
    except Exception:
        return None


# --------------------------------------------------------------------- match resolution

def _normalize(name: str) -> str:
    """Lowercase + strip diacritics-ish noise + drop common suffixes."""
    if not name:
        return ""
    n = name.lower().strip()
    for noise in [" fc", " cf", " ac", " sc", " afc", " united", " utd"]:
        # keep short forms but normalize
        pass
    # collapse common variants
    n = n.replace("manchester united", "man utd").replace("manchester utd", "man utd")
    n = n.replace("paris saint germain", "psg").replace("paris saint-germain", "psg")
    n = n.replace("atletico madrid", "atletico").replace("atlético madrid", "atletico")
    n = n.replace(".", "").replace("-", " ").replace("'", "")
    n = " ".join(n.split())
    return n


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


@dataclass
class MatchResolution:
    external_id: int
    internal_id: int | None
    slug: str
    home_team_name: str
    away_team_name: str
    kickoff_ts: int
    score: float  # 0..1 confidence


def find_event_id_for_match(
    home_team: str,
    away_team: str,
    kickoff_ts: int | None = None,
    league_slug: str | None = None,
) -> MatchResolution | None:
    """Resolve a BSD match to its StatsHub external (Sportradar) id.

    Uses /api/search?q= and fuzzy-matches home/away names + kickoff date.
    Returns None if no acceptable match found.

    `kickoff_ts` is a unix timestamp (seconds). If provided, candidates whose
    StatsHub `matchTime` is more than ±36h away are rejected.
    """
    if not home_team or not away_team:
        return None

    # Search by home team name (most discriminative, BSD usually uses English names for Top 5)
    payload = _get(f"/api/search?q={requests.utils.quote(home_team)}")
    if not isinstance(payload, dict):
        return None
    fixtures = payload.get("fixtures") or []
    if not fixtures:
        # Fallback: search by combined string
        payload = _get(f"/api/search?q={requests.utils.quote(home_team + ' vs ' + away_team)}")
        if isinstance(payload, dict):
            fixtures = payload.get("fixtures") or []
    if not fixtures:
        return None

    best: MatchResolution | None = None
    for fx in fixtures:
        if not isinstance(fx, dict):
            continue
        ext_id = fx.get("id") or fx.get("eventId")
        if not ext_id:
            continue
        # Field names in /api/search fixtures vary; try multiple
        h = (fx.get("homeTeam") or {}).get("name") or fx.get("homeTeamName") or ""
        a = (fx.get("awayTeam") or {}).get("name") or fx.get("awayTeamName") or ""
        ts = fx.get("startTimestamp") or fx.get("timeStartTimestamp") or fx.get("matchTime") or 0

        # Date filter
        if kickoff_ts and ts:
            try:
                if abs(int(ts) - int(kickoff_ts)) > 36 * 3600:
                    continue
            except (TypeError, ValueError):
                pass

        sh = _name_similarity(h, home_team)
        sa = _name_similarity(a, away_team)
        score = (sh + sa) / 2.0
        if score < 0.55:
            continue
        if best is None or score > best.score:
            best = MatchResolution(
                external_id=int(ext_id),
                internal_id=fx.get("internalId"),
                slug=fx.get("slug", ""),
                home_team_name=h,
                away_team_name=a,
                kickoff_ts=int(ts) if ts else 0,
                score=score,
            )
    return best


# --------------------------------------------------------------------- predicted lineup

def fetch_predicted_lineup(external_event_id: int) -> dict | None:
    """Fetch StatsHub's predicted team lineup for a given external id.

    Returns dict with shape:
        {
          "home": {"data": [ {playerId, playerInternalId, name, jerseyNo,
                              position, confidenceScore, predictionSource,
                              predictionType}, ... ]},
          "away": {"data": [...]},
        }
    or None if not available.
    """
    if not external_event_id:
        return None
    payload = _get(f"/api/event/{int(external_event_id)}/predicted-teams-lineup")
    if not isinstance(payload, dict):
        return None
    home = payload.get("homeTeam") or {}
    away = payload.get("awayTeam") or {}
    home_data = home.get("data") if isinstance(home, dict) else None
    away_data = away.get("data") if isinstance(away, dict) else None
    if not (isinstance(home_data, list) and home_data) and not (isinstance(away_data, list) and away_data):
        return None
    return {
        "home": {"data": home_data or []},
        "away": {"data": away_data or []},
    }


def get_predicted_lineup_for_bsd_event(
    bsd_event_id: int,
    home_team: str,
    away_team: str,
    kickoff_ts: int | None = None,
    league_slug: str | None = None,
) -> dict | None:
    """High-level entry point: cache → resolve → fetch.

    Returns None on any failure (caller MUST handle None gracefully).
    The returned dict has shape:
        {
          "external_id": int,
          "slug": str,
          "match_score": float,
          "home": [ {playerId, playerInternalId, name, jerseyNo, position, ...}, ... ],
          "away": [ ... ],
          "source": "statshub",
        }
    """
    cache_key = f"bsd:{bsd_event_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached if cached.get("home") or cached.get("away") else None

    resolution = find_event_id_for_match(home_team, away_team, kickoff_ts, league_slug)
    if resolution is None:
        # Cache the negative result briefly to avoid retrying every render
        _cache_put(cache_key, {"home": [], "away": [], "_negative": True})
        return None

    lineup = fetch_predicted_lineup(resolution.external_id)
    if lineup is None:
        _cache_put(cache_key, {"home": [], "away": [], "_negative": True})
        return None

    result = {
        "external_id": resolution.external_id,
        "slug": resolution.slug,
        "match_score": resolution.score,
        "home": lineup.get("home", {}).get("data", []),
        "away": lineup.get("away", {}).get("data", []),
        "source": "statshub",
    }
    _cache_put(cache_key, result)
    return result
