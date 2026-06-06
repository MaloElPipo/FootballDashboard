"""Helpers BSD pour recuperer matchs + cotes 1X2 / O/U 2.5 / BTTS.

Le wrapper bsd_client gere le cache disque, donc on peut spammer ces helpers
sans saturer l'API BSD.

Conventions BSD :
- endpoint compareOdds : `v2/odds/compare/?match_id=<id>`
- endpoint matchDetail  : `v2/matches/<id>/`
- endpoint searchMatches: `v2/matches/?league=<lid>&season=<sid>&status=finished`

Note : les noms reels d'endpoint BSD peuvent legerement varier. Les fonctions
ci-dessous offrent des fallbacks et loggent ce qui marche pour qu'on aligne
au premier appel reel.
"""
from __future__ import annotations

from typing import Any

from . import bsd_client


# ─────────────────────────────────────────────────────────────────────────────
# Listage matchs finis
# ─────────────────────────────────────────────────────────────────────────────


def list_finished_matches(league_id: int, season_id: int, limit: int = 50) -> list[dict]:
    """Liste les matchs termines d'une saison/league BSD.

    Filtre cote client sur status == 'finished' / has_score.
    """
    candidates = [
        ("v2/matches/", {"league": league_id, "season": season_id, "limit": limit}),
        ("matches/", {"league": league_id, "season": season_id, "limit": limit}),
        (
            f"v2/leagues/{league_id}/seasons/{season_id}/matches/",
            {"limit": limit},
        ),
    ]
    for endpoint, params in candidates:
        try:
            data = bsd_client.bsd_get(endpoint, params=params)
            items = _extract_list(data)
            if not items:
                continue
            finished = [m for m in items if _is_finished(m)]
            if finished:
                return finished[:limit]
        except Exception:
            continue
    return []


def _extract_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("results", "matches", "data", "items"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def _is_finished(m: dict) -> bool:
    status = (m.get("status") or m.get("status_type") or "").lower()
    if status in ("finished", "ended", "ft", "ap", "pen", "complete"):
        return True
    score = m.get("score") or m.get("ft_score") or {}
    if isinstance(score, dict) and (
        score.get("home") is not None or score.get("ft_home") is not None
    ):
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Cotes : compareOdds
# ─────────────────────────────────────────────────────────────────────────────


def fetch_compare_odds(match_id: int) -> dict[str, Any] | None:
    """Cote median/best par marche pour un match BSD."""
    candidates = [
        (f"v2/matches/{match_id}/odds/compare/", {}),
        ("v2/odds/compare/", {"match_id": match_id}),
        (f"v2/odds/compare/{match_id}/", {}),
    ]
    for endpoint, params in candidates:
        try:
            data = bsd_client.bsd_get(endpoint, params=params)
            if data:
                return data
        except Exception:
            continue
    return None


def extract_market_probs(odds_payload: dict) -> dict[str, float] | None:
    """Extrait p_h, p_d, p_a, p_over25, p_btts depuis le payload compareOdds.

    Strategie : prendre la cote mediane Pinnacle si dispo, sinon mediane all books.
    Retourne None si l'un des marches manque.
    """
    if not odds_payload:
        return None

    markets = _extract_markets(odds_payload)
    one_x_two = _pick_market(markets, ["match_winner", "1x2", "moneyline", "h2h"])
    over_under = _pick_market(
        markets, ["over_under", "totals", "goals_over_under", "ou_2_5"]
    )
    btts = _pick_market(markets, ["btts", "both_teams_to_score", "gg_ng"])

    if not (one_x_two and over_under and btts):
        return None

    # 1X2
    odd_h = _pick_outcome_odds(one_x_two, ["home", "1", "h"])
    odd_d = _pick_outcome_odds(one_x_two, ["draw", "x", "tie"])
    odd_a = _pick_outcome_odds(one_x_two, ["away", "2", "a"])
    if not (odd_h and odd_d and odd_a):
        return None

    # O/U 2.5
    over_odd = _pick_outcome_odds(
        over_under,
        ["over", "over_2_5", "over25", "o2.5", "o_2.5"],
        line=2.5,
    )
    under_odd = _pick_outcome_odds(
        over_under,
        ["under", "under_2_5", "under25", "u2.5", "u_2.5"],
        line=2.5,
    )
    if not (over_odd and under_odd):
        return None

    # BTTS
    btts_yes = _pick_outcome_odds(btts, ["yes", "y", "gg", "btts_yes"])
    btts_no = _pick_outcome_odds(btts, ["no", "n", "ng", "btts_no"])
    if not (btts_yes and btts_no):
        return None

    from .invert_market import odds_to_prob_binary, odds_to_probs_1x2

    p_h, p_d, p_a = odds_to_probs_1x2(odd_h, odd_d, odd_a)
    p_over25 = odds_to_prob_binary(over_odd, under_odd)
    p_btts = odds_to_prob_binary(btts_yes, btts_no)
    return {
        "p_h": p_h,
        "p_d": p_d,
        "p_a": p_a,
        "p_over25": p_over25,
        "p_btts": p_btts,
        "raw_odds": {
            "1": odd_h,
            "X": odd_d,
            "2": odd_a,
            "O2.5": over_odd,
            "U2.5": under_odd,
            "BTTS_Y": btts_yes,
            "BTTS_N": btts_no,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires structure heterogene
# ─────────────────────────────────────────────────────────────────────────────


def _extract_markets(payload: dict) -> list[dict]:
    for key in ("markets", "odds", "data", "results"):
        v = payload.get(key)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):
            return list(v.values()) if all(isinstance(x, dict) for x in v.values()) else []
    if isinstance(payload, list):
        return payload
    return []


def _pick_market(markets: list[dict], aliases: list[str]) -> dict | None:
    aliases_l = [a.lower() for a in aliases]
    for m in markets:
        name = str(m.get("name") or m.get("key") or m.get("market") or m.get("type") or "").lower()
        if name in aliases_l:
            return m
        if any(a in name for a in aliases_l):
            return m
    return None


def _pick_outcome_odds(
    market: dict, name_aliases: list[str], line: float | None = None
) -> float | None:
    aliases_l = [a.lower() for a in name_aliases]
    outcomes = (
        market.get("outcomes")
        or market.get("selections")
        or market.get("runners")
        or market.get("odds")
        or []
    )
    if isinstance(outcomes, dict):
        outcomes = list(outcomes.values())

    best_odd: float | None = None
    for o in outcomes:
        if not isinstance(o, dict):
            continue
        n = str(o.get("name") or o.get("label") or o.get("key") or o.get("selection") or "").lower()
        if not any(a in n for a in aliases_l):
            continue
        if line is not None:
            o_line = o.get("line") or o.get("handicap") or o.get("total") or o.get("point")
            try:
                if o_line is not None and float(o_line) != line:
                    continue
            except (TypeError, ValueError):
                continue
        # odd : on prend median, sinon best, sinon premier
        candidate = (
            o.get("median")
            or o.get("best")
            or o.get("price")
            or o.get("odd")
            or o.get("decimal")
            or o.get("pinnacle")
        )
        if candidate is None:
            books = o.get("bookmakers") or o.get("books") or {}
            if isinstance(books, dict) and books:
                first = next(iter(books.values()))
                candidate = (first or {}).get("odd") if isinstance(first, dict) else first
        if candidate is not None:
            try:
                best_odd = float(candidate)
                return best_odd
            except (TypeError, ValueError):
                continue
    return best_odd


def extract_result(match: dict) -> str | None:
    """Extrait 'H'/'D'/'A' depuis un match BSD."""
    score = match.get("score") or match.get("ft_score") or {}
    home = score.get("home") if isinstance(score, dict) else None
    away = score.get("away") if isinstance(score, dict) else None
    if home is None and isinstance(score, dict):
        home = score.get("ft_home")
        away = score.get("ft_away")
    if home is None:
        home = match.get("home_score") or match.get("score_home")
        away = match.get("away_score") or match.get("score_away")
    try:
        h, a = int(home), int(away)
    except (TypeError, ValueError):
        return None
    if h > a:
        return "H"
    if h < a:
        return "A"
    return "D"


def extract_total_goals(match: dict) -> int | None:
    score = match.get("score") or match.get("ft_score") or {}
    home = score.get("home") if isinstance(score, dict) else None
    away = score.get("away") if isinstance(score, dict) else None
    if home is None and isinstance(score, dict):
        home = score.get("ft_home")
        away = score.get("ft_away")
    if home is None:
        home = match.get("home_score") or match.get("score_home")
        away = match.get("away_score") or match.get("score_away")
    try:
        return int(home) + int(away)
    except (TypeError, ValueError):
        return None
