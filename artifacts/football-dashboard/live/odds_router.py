"""Router odds 3 marchés (1X2 + O/U 2.5 + BTTS) avec cascade BSD → TheOddsAPI → Betclic.

Architecture validée 27/04/2026 :
- BSD `compareOdds` : 22+ bookmakers, 3 marchés, couvre 47 compétitions du catalogue BSD.
- TheOddsAPI : 53 compétitions soccer dont UECL ; pas de BTTS sur soccer (mode B = sans BTTS).
- Betclic : fallback du fallback (scrape ponctuel).

Sortie normalisée :
    {
      "1x2":   (home, draw, away),
      "ou25":  (over, under),                 # peut être None
      "btts":  (yes, no),                     # peut être None
      "source": "bsd_event"   (odds inline payload BSD)
              | "bsd_bet365"  (compareOdds, 100% Bet365 — λ équipe le plus précis)
              | "bsd_mix"     (compareOdds, mix Bet365 + best_odds)
              | "bsd"         (compareOdds, 100% best_odds tous bookmakers)
              | "theoddsapi"  (TheOddsAPI, 1X2+OU sans BTTS)
              | "betclic"     (scrape Betclic),
      "mode":   "A" (3 marchés) | "B" (1X2+OU) | "C" (1X2 seul),
      "fetched_at": iso timestamp,
    }

READ-ONLY : ce module ne modifie ni `predict_today.py`, ni `g2_engine.py`,
ni le scraping Betclic existant. Il les *utilise*.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

import requests

from live.leagues_config import LeagueConfig, get_by_bsd_id

ROOT = Path(__file__).resolve().parent
_CACHE_DIR = ROOT / "data"
_CACHE_FILE = _CACHE_DIR / "odds_router_cache.json"
CACHE_TTL_SECONDS = 30 * 60  # 30 min

THEODDSAPI_BASE = "https://api.the-odds-api.com/v4"
DEFAULT_TIMEOUT = 12


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
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CACHE_FILE)
    except Exception:
        pass


def _cache_key(bsd_event_id: int | None, league_slug: str,
               home: str | None, away: str | None) -> str:
    if bsd_event_id:
        return f"bsd:{bsd_event_id}"
    return f"meta:{league_slug}:{(home or '').lower()}:{(away or '').lower()}"


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


# --------------------------------------------------------------------- BSD source

def _try_bsd_event_inline(ev: dict | None) -> dict | None:
    """Essaye d'abord les odds inline du payload BSD event (format
    historique : odds_home/odds_draw/odds_away/odds_over_25/odds_under_25/...).
    Couvre Top 5 + UCL/UEL pour lesquels les odds sont déjà dans l'event detail.
    """
    if not ev:
        return None
    h, d, a = ev.get("odds_home"), ev.get("odds_draw"), ev.get("odds_away")
    if not (h and d and a):
        return None
    over, under = ev.get("odds_over_25"), ev.get("odds_under_25")
    btts_y, btts_n = ev.get("odds_btts_yes"), ev.get("odds_btts_no")
    has_ou = bool(over and under)
    has_bt = bool(btts_y and btts_n)
    return {
        "1x2": (float(h), float(d), float(a)),
        "ou25": (float(over), float(under)) if has_ou else None,
        "btts": (float(btts_y), float(btts_n)) if has_bt else None,
        "source": "bsd_event",
        "mode": "A" if (has_ou and has_bt) else ("B" if has_ou else "C"),
    }


PREFERRED_BOOKMAKER_PREFIXES = ("Bet365",)


def _bet365_odd(market: dict | None, selection_keys: list[str]) -> float | None:
    """Cherche la première cote d'un bookmaker préféré (Bet365 toutes variantes
    régionales) dans `market[sk]["bookmakers"]`.

    Renvoie None si Bet365 absent → l'appelant pourra fallback sur best_odds.
    """
    if not isinstance(market, dict):
        return None
    for sk in selection_keys:
        sel = market.get(sk)
        if not isinstance(sel, dict):
            continue
        bookmakers = sel.get("bookmakers") or {}
        if not isinstance(bookmakers, dict):
            continue
        for bm_name, bm_data in bookmakers.items():
            if not isinstance(bm_name, str):
                continue
            if not any(bm_name.startswith(pfx) for pfx in PREFERRED_BOOKMAKER_PREFIXES):
                continue
            v = (bm_data or {}).get("decimal") if isinstance(bm_data, dict) else None
            if isinstance(v, (int, float)) and v > 1.0:
                return float(v)
    return None


def _best_odd(market: dict | None, selection_keys: list[str]) -> float | None:
    """Meilleure cote tous bookmakers confondus (fallback historique)."""
    if not isinstance(market, dict):
        return None
    for sk in selection_keys:
        sel = market.get(sk)
        if isinstance(sel, dict):
            v = sel.get("best_odds")
            if isinstance(v, (int, float)) and v > 1.0:
                return float(v)
    return None


def _try_bsd_compare_via_helpers(bsd_event_id: int | None) -> dict | None:
    """Tente l'endpoint BSD compareOdds via REST direct (sans MCP).
    Format attendu : {"markets": {"1x2": {...}, "over_under_25": {...}, "btts": {...}}}.

    Stratégie : Bet365 prioritaire si disponible sur les 3 marchés (cohérence
    cross-market = λ équipe plus précis). Fallback sur best_odds par marché
    quand Bet365 manque. Le champ `source` reflète la source effective :
        "bsd_bet365"     → 3 marchés Bet365 (idéal)
        "bsd_mix"        → mix Bet365 + best_odds
        "bsd"            → aucun marché Bet365, 100 % best_odds
    """
    if not bsd_event_id:
        return None
    key = os.environ.get("BSD_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.get(
            f"https://sports.bzzoiro.com/api/events/{int(bsd_event_id)}/compare-odds/",
            headers={"Authorization": f"Token {key}"},
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        payload = r.json()
    except Exception:
        return None

    markets = payload.get("markets") or {}
    if not isinstance(markets, dict):
        return None

    m_1x2 = markets.get("1x2") or {}
    home_team = payload.get("home_team", "")
    away_team = payload.get("away_team", "")
    h_keys = [home_team, "1", "Home"]
    d_keys = ["Draw", "X", "draw"]
    a_keys = [away_team, "2", "Away"]

    m_ou = markets.get("over_under_25") or {}
    over_keys = ["Over 2.5", "over_2_5", "Plus de 2,5"]
    under_keys = ["Under 2.5", "under_2_5", "Moins de 2,5"]

    m_bt = markets.get("btts") or {}
    yes_keys = ["Yes", "yes", "Oui"]
    no_keys = ["No", "no", "Non"]

    bet365_used = 0
    fallback_used = 0

    def _pick(market: dict, keys: list[str]) -> float | None:
        nonlocal bet365_used, fallback_used
        v = _bet365_odd(market, keys)
        if v is not None:
            bet365_used += 1
            return v
        v = _best_odd(market, keys)
        if v is not None:
            fallback_used += 1
        return v

    h = _pick(m_1x2, h_keys)
    d = _pick(m_1x2, d_keys)
    a = _pick(m_1x2, a_keys)
    if not (h and d and a):
        return None

    over = _pick(m_ou, over_keys)
    under = _pick(m_ou, under_keys)
    btts_yes = _pick(m_bt, yes_keys)
    btts_no = _pick(m_bt, no_keys)

    has_ou = bool(over and under)
    has_bt = bool(btts_yes and btts_no)

    if bet365_used > 0 and fallback_used == 0:
        source = "bsd_bet365"
    elif bet365_used > 0 and fallback_used > 0:
        source = "bsd_mix"
    else:
        source = "bsd"

    return {
        "1x2": (h, d, a),
        "ou25": (over, under) if has_ou else None,
        "btts": (btts_yes, btts_no) if has_bt else None,
        "source": source,
        "mode": "A" if (has_ou and has_bt) else ("B" if has_ou else "C"),
    }


# --------------------------------------------------------------------- TheOddsAPI source

def _try_theoddsapi(league_cfg: LeagueConfig, home: str, away: str,
                    kickoff_iso: str | None) -> dict | None:
    """Récupère 1X2 + O/U via TheOddsAPI (mode B garanti ; pas de BTTS soccer).

    Match resolution = home_team + away_team substrings (tolérant accents).

    Stratégie bookmaker (cohérente avec la branche BSD compareOdds) :
    Bet365 prioritaire si disponible, fallback sur le premier bookmaker EU
    qui couvre chaque marché manquant. `source` reflète le résultat :
        "theoddsapi_bet365" → 1X2 + O/U entièrement Bet365
        "theoddsapi_mix"    → mix Bet365 + autre bookmaker
        "theoddsapi"        → aucun Bet365, tout fallback
    """
    if not league_cfg.theoddsapi_key:
        return None
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        return None

    try:
        r = requests.get(
            f"{THEODDSAPI_BASE}/sports/{league_cfg.theoddsapi_key}/odds",
            params={
                "regions": "eu",
                "markets": "h2h,totals",
                "oddsFormat": "decimal",
                "apiKey": api_key,
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        events = r.json()
    except Exception:
        return None

    if not isinstance(events, list) or not events:
        return None

    def _norm(s: str) -> str:
        import unicodedata
        if not s:
            return ""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        return s.lower().strip()

    nh, na = _norm(home), _norm(away)
    target = None
    for ev in events:
        eh, ea = _norm(ev.get("home_team", "")), _norm(ev.get("away_team", ""))
        if (nh in eh or eh in nh) and (na in ea or ea in na):
            target = ev
            break
    if target is None:
        return None

    home_norm = _norm(target.get("home_team", ""))
    away_norm = _norm(target.get("away_team", ""))

    def _is_bet365(bk: dict) -> bool:
        title = bk.get("title", "") or bk.get("key", "")
        title_l = title.lower()
        return any(p.lower() in title_l for p in PREFERRED_BOOKMAKER_PREFIXES)

    def _extract_1x2(bk: dict) -> tuple[float, float, float] | None:
        for mk in bk.get("markets", []):
            if mk.get("key") != "h2h":
                continue
            h = d = a = None
            for o in mk.get("outcomes", []):
                name = _norm(o.get("name", ""))
                try:
                    price = float(o["price"])
                except (TypeError, ValueError, KeyError):
                    continue
                if name == home_norm:
                    h = price
                elif name == away_norm:
                    a = price
                elif name in ("draw", "tie"):
                    d = price
            if h and d and a:
                return (h, d, a)
        return None

    def _extract_ou25(bk: dict) -> tuple[float, float] | None:
        for mk in bk.get("markets", []):
            if mk.get("key") != "totals":
                continue
            over = under = None
            for o in mk.get("outcomes", []):
                try:
                    if abs(float(o.get("point", 0)) - 2.5) > 0.01:
                        continue
                    price = float(o["price"])
                except (TypeError, ValueError, KeyError):
                    continue
                if o.get("name", "").lower() == "over":
                    over = price
                elif o.get("name", "").lower() == "under":
                    under = price
            if over and under:
                return (over, under)
        return None

    bookmakers = target.get("bookmakers", []) or []
    bet365_bks = [bk for bk in bookmakers if _is_bet365(bk)]
    other_bks = [bk for bk in bookmakers if not _is_bet365(bk)]

    h2h: tuple[float, float, float] | None = None
    h2h_from_bet365 = False
    for bk in bet365_bks:
        h2h = _extract_1x2(bk)
        if h2h:
            h2h_from_bet365 = True
            break
    if h2h is None:
        for bk in other_bks:
            h2h = _extract_1x2(bk)
            if h2h:
                break

    ou: tuple[float, float] | None = None
    ou_from_bet365 = False
    for bk in bet365_bks:
        ou = _extract_ou25(bk)
        if ou:
            ou_from_bet365 = True
            break
    if ou is None:
        for bk in other_bks:
            ou = _extract_ou25(bk)
            if ou:
                break

    if h2h is None:
        return None

    has_ou = ou is not None
    bet365_count = int(h2h_from_bet365) + (int(ou_from_bet365) if has_ou else 0)
    expected = 2 if has_ou else 1
    if bet365_count == expected:
        source = "theoddsapi_bet365"
    elif bet365_count > 0:
        source = "theoddsapi_mix"
    else:
        source = "theoddsapi"

    return {
        "1x2": h2h,
        "ou25": ou if has_ou else None,
        "btts": None,
        "source": source,
        "mode": "B" if has_ou else "C",
    }


# --------------------------------------------------------------------- Betclic source

def _try_betclic(league_cfg: LeagueConfig, betclic_matches: list[dict] | None,
                 home: str, away: str) -> dict | None:
    """Essaye de retrouver les odds 1X2 + O/U + BTTS dans le scrape Betclic
    déjà fait par predict_today.py (passé en argument).

    Note : `betclic_matches` provient de scrape_betclic_leagues() — chaque
    entrée a une `selections: list[dict]` avec market_type (`1x2_home`,
    `1x2_draw`, `1x2_away`, `total_over_2_5`, `total_under_2_5`,
    `btts_yes`, `btts_no`, ...).
    """
    if not betclic_matches:
        return None

    def _norm(s: str) -> str:
        import unicodedata
        if not s:
            return ""
        s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
        return s.lower().strip()

    nh, na = _norm(home), _norm(away)
    target = None
    for bm in betclic_matches:
        bh, ba = _norm(bm.get("home_team", "")), _norm(bm.get("away_team", ""))
        if (nh in bh or bh in nh) and (na in ba or ba in na):
            target = bm
            break
    if target is None:
        return None

    odds: dict[str, float] = {}
    for sel in target.get("selections", []):
        mt = sel.get("market_type", "")
        v = sel.get("odds")
        if isinstance(v, (int, float)) and v > 1.0:
            odds[mt] = float(v)

    h = odds.get("1x2_home")
    d = odds.get("1x2_draw")
    a = odds.get("1x2_away")
    if not (h and d and a):
        return None

    over = odds.get("total_over_2_5")
    under = odds.get("total_under_2_5")
    btts_y = odds.get("btts_yes")
    btts_n = odds.get("btts_no")
    has_ou = bool(over and under)
    has_bt = bool(btts_y and btts_n)
    return {
        "1x2": (h, d, a),
        "ou25": (over, under) if has_ou else None,
        "btts": (btts_y, btts_n) if has_bt else None,
        "source": "betclic",
        "mode": "A" if (has_ou and has_bt) else ("B" if has_ou else "C"),
    }


# --------------------------------------------------------------------- public API

def get_match_odds_3markets(
    bsd_event_id: int | None,
    league_cfg: LeagueConfig,
    home_team: str,
    away_team: str,
    kickoff_iso: str | None = None,
    bsd_event_payload: dict | None = None,
    betclic_matches: list[dict] | None = None,
) -> dict | None:
    """Cascade BSD inline → BSD compareOdds → TheOddsAPI → Betclic.
    Renvoie None si aucune source ne fournit au moins le 1X2.
    """
    cache_key = _cache_key(bsd_event_id, league_cfg.slug, home_team, away_team)
    cached = _cache_get(cache_key)
    if cached and cached.get("1x2"):
        cached["1x2"] = tuple(cached["1x2"])
        if cached.get("ou25"):
            cached["ou25"] = tuple(cached["ou25"])
        if cached.get("btts"):
            cached["btts"] = tuple(cached["btts"])
        return cached

    # 1) Inline BSD event (toujours essayé en premier si payload dispo)
    res = _try_bsd_event_inline(bsd_event_payload)
    if res and res["1x2"]:
        _cache_put(cache_key, res)
        return res

    # 2) BSD compareOdds (uniquement si on a un BSD event id)
    res = _try_bsd_compare_via_helpers(bsd_event_id)
    if res and res["1x2"]:
        _cache_put(cache_key, res)
        return res

    # 3) TheOddsAPI
    res = _try_theoddsapi(league_cfg, home_team, away_team, kickoff_iso)
    if res and res["1x2"]:
        _cache_put(cache_key, res)
        return res

    # 4) Betclic (fallback du fallback)
    res = _try_betclic(league_cfg, betclic_matches, home_team, away_team)
    if res and res["1x2"]:
        _cache_put(cache_key, res)
        return res

    return None


def to_predict_today_format(routed: dict | None) -> dict[str, float | None]:
    """Adapte la sortie du router au format que `predict_today.extract_odds`
    historique produit. Permet une intégration drop-in."""
    if not routed:
        return {
            "odds_h": None, "odds_d": None, "odds_a": None,
            "ou25_under": None, "ou25_over": None,
            "btts_yes": None, "btts_no": None,
        }
    h, d, a = routed["1x2"]
    over, under = (routed["ou25"] or (None, None))
    btts_y, btts_n = (routed["btts"] or (None, None))
    return {
        "odds_h": h, "odds_d": d, "odds_a": a,
        "ou25_under": under, "ou25_over": over,
        "btts_yes": btts_y, "btts_no": btts_n,
    }
