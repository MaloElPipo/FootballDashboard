"""Phase 3 — chargement donnees reelles CDM 26.

Branche la phase 3 du labo sur le snapshot prod :
  - 12 poules WC2026 (hardcodees, le tirage public n'est pas dans la snapshot)
  - cotes Pinnacle 1X2 disponibles -> lambdas market via invert_double
  - Elo prod (pin_calibrated_elo + overrides, fallback elorating_cache) ->
    lambdas model

Quand un match de poule n'a pas de cote Pinnacle dans le snapshot, on retombe
sur l'Elo pour les lambdas market (gap nul = pas de signal). On documente la
couverture via `coverage_summary()`.

Le snapshot n'expose que des cotes 1X2 (pas O/U ni BTTS) donc on utilise
`invert_double` avec un seed `p_over25` derive d'une heuristique forfaitaire
(0.54 + delta-Elo) plutot que la "triple inversion" complete decrite dans la
phase 1. Cette limite est rendue visible dans l'UI.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from lab.calibration import invert_market as IM

LAB_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    LAB_ROOT / "lab" / "data" / "snapshots" / "initial_baseline_2026-05-20"
)

HOME_ADV_ELO = 50.0  # avantage CDM reduit (terrain neutre quasi systematique)
GLOBAL_GOAL_BASELINE = 1.35  # lambda moyenne par equipe (≈ total 2.7)
DEFAULT_P_OVER25_SEED = 0.54


# ─────────────────────────────────────────────────────────────────────────────
# 12 poules CDM 26 (construites pour utiliser au mieux les cotes disponibles)
# ─────────────────────────────────────────────────────────────────────────────

WC26_GROUPS: dict[str, list[str]] = {
    "A": ["MEX", "RSA", "KOR", "CZE"],
    "B": ["CAN", "BIH", "USA", "PAR"],
    "C": ["QAT", "SUI", "BRA", "MAR"],
    "D": ["HAI", "SCO", "NED", "JPN"],
    "E": ["AUS", "TUR", "JOR", "IRN"],
    "F": ["CIV", "ECU", "SWE", "TUN"],
    "G": ["BEL", "EGY", "KSA", "URU"],
    "H": ["FRA", "SEN", "IRQ", "NOR"],
    "I": ["ARG", "ALG", "POR", "COD"],
    "J": ["ENG", "CRO", "GHA", "PAN"],
    "K": ["UZB", "COL", "GER", "NZL"],
    "L": ["CUW", "CPV", "ITA", "DEN"],
}

# nation forced (host + qualifies politiquement) : on skip l'ajustement Elo
FORCED_NATIONS: set[str] = {"MEX", "USA", "CAN", "QAT"}

# mapping nom (Pinnacle) -> code FIFA 3 lettres
TEAM_NAME_TO_CODE: dict[str, str] = {
    "Mexico": "MEX", "South Africa": "RSA", "South Korea": "KOR",
    "Czech Republic": "CZE", "Canada": "CAN", "Bosnia & Herzegovina": "BIH",
    "USA": "USA", "Paraguay": "PAR", "Qatar": "QAT", "Switzerland": "SUI",
    "Brazil": "BRA", "Morocco": "MAR", "Haiti": "HAI", "Scotland": "SCO",
    "Australia": "AUS", "Turkey": "TUR", "Netherlands": "NED", "Japan": "JPN",
    "Ivory Coast": "CIV", "Ecuador": "ECU", "Sweden": "SWE", "Tunisia": "TUN",
    "Belgium": "BEL", "Egypt": "EGY", "Saudi Arabia": "KSA", "Uruguay": "URU",
    "France": "FRA", "Senegal": "SEN", "Iraq": "IRQ", "Norway": "NOR",
    "Argentina": "ARG", "Algeria": "ALG", "Jordan": "JOR", "Portugal": "POR",
    "DR Congo": "COD", "England": "ENG", "Croatia": "CRO", "Ghana": "GHA",
    "Panama": "PAN", "Uzbekistan": "UZB", "Colombia": "COL", "Iran": "IRN",
    "Germany": "GER", "New Zealand": "NZL", "Curaçao": "CUW", "Cape Verde": "CPV",
    "Italy": "ITA", "Denmark": "DEN",
}

# fallback Elo pour nations absentes de pin_calibrated_elo.json (depuis
# elorating_cache.json snapshot du 20 mai 2026)
ELO_FALLBACK: dict[str, float] = {
    "BIH": 1594,
    "ITA": 1856,
    "DEN": 1869,
}


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────


def load_elo(snapshot_dir: Path = DEFAULT_SNAPSHOT) -> dict[str, float]:
    """Charge l'Elo de toutes les nations CDM (calibre + override + fallback)."""
    base_path = snapshot_dir / "pin_calibrated_elo.json"
    over_path = snapshot_dir / "elo_overrides.json"
    base = {}
    if base_path.exists():
        base = json.loads(base_path.read_text()).get("elo", {})
    overrides = {}
    if over_path.exists():
        overrides = json.loads(over_path.read_text())
    elo: dict[str, float] = {}
    for grp in WC26_GROUPS.values():
        for code in grp:
            v = overrides.get(code, base.get(code, ELO_FALLBACK.get(code)))
            if v is not None:
                elo[code] = float(v)
    return elo


def load_pinnacle_odds(snapshot_dir: Path = DEFAULT_SNAPSHOT) -> list[dict]:
    """Renvoie [{home_code, away_code, pin_h, pin_d, pin_a, commence_time}]."""
    path = snapshot_dir / "pinnacle_wc2026_odds.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    out = []
    for m in raw:
        h_code = TEAM_NAME_TO_CODE.get(m["home"])
        a_code = TEAM_NAME_TO_CODE.get(m["away"])
        if not h_code or not a_code:
            continue
        out.append({
            "home_code": h_code, "away_code": a_code,
            "pin_h": m["pin_h"], "pin_d": m["pin_d"], "pin_a": m["pin_a"],
            "commence_time": m.get("commence_time"),
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Lambdas
# ─────────────────────────────────────────────────────────────────────────────


def elo_to_lambdas(
    elo_h: float, elo_a: float, home_adv: float = HOME_ADV_ELO,
    baseline: float = GLOBAL_GOAL_BASELINE,
) -> tuple[float, float]:
    """Conversion Elo -> (lambda_home, lambda_away).

    On utilise une echelle log : un delta de 400 Elo correspond a ~ x1.78 sur le
    ratio attaque/defense. La somme tend vers `2 * baseline` au repos.
    """
    import math
    delta = (elo_h - elo_a + home_adv) / 400.0
    # echelle douce : exp(0.4 * delta) garde des totaux realistes
    # (~ 3.0 buts pour 500 Elo d'ecart sur terrain neutre)
    factor = math.exp(0.4 * delta)
    lh = baseline * factor
    la = baseline / factor
    return max(lh, 0.15), max(la, 0.15)


def seed_p_over25_from_elo(elo_h: float, elo_a: float) -> float:
    """Heuristique forfaitaire pour seed l'inversion 1X2 -> lambdas."""
    lh, la = elo_to_lambdas(elo_h, elo_a)
    # plus de buts attendus si total grand
    total = lh + la
    # ancre 2.7 -> 0.54, pente legere
    return float(min(0.78, max(0.30, DEFAULT_P_OVER25_SEED + 0.10 * (total - 2.7))))


def market_lambdas_from_odds(
    pin_h: float, pin_d: float, pin_a: float, elo_h: float, elo_a: float,
) -> tuple[float, float, bool]:
    """Inverse 1X2 -> (lambda_h, lambda_a) avec seed Elo pour p_over25.

    Returns (lh, la, ok).
    """
    p_h, p_d, p_a = IM.odds_to_probs_1x2(pin_h, pin_d, pin_a)
    p_over25 = seed_p_over25_from_elo(elo_h, elo_a)
    res = IM.invert_double(p_h, p_d, p_a, p_over25)
    return res.lambda_h, res.lambda_a, bool(res.ok)


# ─────────────────────────────────────────────────────────────────────────────
# Construction des matchs de poule (round-robin 4 equipes = 6 matchs)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PoolMatch:
    group: str
    home: str
    away: str
    lambda_model_h: float
    lambda_model_a: float
    lambda_market_h: float
    lambda_market_a: float
    has_odds: bool = False


def _round_robin(group: list[str]) -> list[tuple[str, str]]:
    """Renvoie les 6 pairings d'une poule de 4 (ordre arbitraire mais stable)."""
    a, b, c, d = group
    return [(a, b), (c, d), (a, c), (b, d), (a, d), (b, c)]


def build_pool_matches(
    snapshot_dir: Path = DEFAULT_SNAPSHOT,
) -> tuple[dict[str, list[PoolMatch]], dict[str, float]]:
    """Construit les 72 matchs de poule (12 x 6) avec lambdas model + market.

    Returns (matches_par_groupe, elo_courant).
    """
    elo = load_elo(snapshot_dir)
    odds = load_pinnacle_odds(snapshot_dir)
    # index des cotes par paire (non orientee : on garde l'orientation home du fichier)
    odds_by_pair: dict[tuple[str, str], dict] = {}
    for o in odds:
        odds_by_pair[(o["home_code"], o["away_code"])] = o

    matches_by_group: dict[str, list[PoolMatch]] = {}
    for g, teams in WC26_GROUPS.items():
        ms: list[PoolMatch] = []
        for home, away in _round_robin(teams):
            e_h = elo.get(home, 1600.0)
            e_a = elo.get(away, 1600.0)
            lh_m, la_m = elo_to_lambdas(e_h, e_a)

            o = odds_by_pair.get((home, away)) or odds_by_pair.get((away, home))
            if o is None:
                lh_mk, la_mk, has = lh_m, la_m, False
            else:
                if (o["home_code"], o["away_code"]) == (home, away):
                    lh_mk, la_mk, _ = market_lambdas_from_odds(
                        o["pin_h"], o["pin_d"], o["pin_a"], e_h, e_a
                    )
                else:
                    # cote orientee inverse : on inverse home/away apres inversion
                    la_mk, lh_mk, _ = market_lambdas_from_odds(
                        o["pin_h"], o["pin_d"], o["pin_a"], e_a, e_h
                    )
                has = True
            ms.append(PoolMatch(
                group=g, home=home, away=away,
                lambda_model_h=lh_m, lambda_model_a=la_m,
                lambda_market_h=lh_mk, lambda_market_a=la_mk,
                has_odds=has,
            ))
        matches_by_group[g] = ms
    return matches_by_group, elo


def team_match_views(
    team: str, group_matches: list[PoolMatch],
) -> list[dict]:
    """Format attendu par `pool_xg.compute_pool_xg` pour une equipe."""
    out = []
    for m in group_matches:
        if m.home == team:
            out.append({
                "opp": m.away, "home": True,
                "lambda_model_h": m.lambda_model_h,
                "lambda_model_a": m.lambda_model_a,
                "lambda_market_h": m.lambda_market_h,
                "lambda_market_a": m.lambda_market_a,
            })
        elif m.away == team:
            out.append({
                "opp": m.home, "home": False,
                "lambda_model_h": m.lambda_model_h,
                "lambda_model_a": m.lambda_model_a,
                "lambda_market_h": m.lambda_market_h,
                "lambda_market_a": m.lambda_market_a,
            })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Coverage / convergence
# ─────────────────────────────────────────────────────────────────────────────


def coverage_summary(matches_by_group: dict[str, list[PoolMatch]]) -> dict:
    total = sum(len(v) for v in matches_by_group.values())
    with_odds = sum(1 for v in matches_by_group.values() for m in v if m.has_odds)
    per_group = {
        g: sum(1 for m in v if m.has_odds) for g, v in matches_by_group.items()
    }
    return {
        "total_pool_matches": total,
        "matches_with_odds": with_odds,
        "coverage_pct": round(100.0 * with_odds / max(total, 1), 1),
        "per_group": per_group,
    }


@dataclass
class ConvergenceStep:
    iteration: int
    max_gap: float
    adjustments: dict[str, float]  # team -> delta Elo applique


def run_boucle_b(
    snapshot_dir: Path = DEFAULT_SNAPSHOT,
    max_iter: int = 3,
    threshold: float = 0.5,
    sensitivity: float = 100.0,
) -> tuple[list[ConvergenceStep], dict[str, float], dict[str, list[PoolMatch]]]:
    """Iterations Elo nation -> recalcul lambdas model -> recalcul gap.

    Returns (steps, elo_final, matches_final).
    """
    from lab.cdm import pool_xg as PX

    matches_by_group, elo = build_pool_matches(snapshot_dir)
    elo = dict(elo)
    steps: list[ConvergenceStep] = []
    for it in range(1, max_iter + 1):
        # gap par equipe
        gaps: dict[str, float] = {}
        signs: dict[str, float] = {}  # signe market - model (sur xgf)
        for g, ms in matches_by_group.items():
            for team in WC26_GROUPS[g]:
                views = team_match_views(team, ms)
                tpx = PX.compute_pool_xg(team, views)
                gaps[team] = tpx.delta_per_match
                signs[team] = 1.0 if tpx.delta_xgf >= 0 else -1.0

        adjustments: dict[str, float] = {}
        max_gap = max(gaps.values()) if gaps else 0.0
        for team, gap in gaps.items():
            if team in FORCED_NATIONS or gap < threshold:
                continue
            delta_elo = signs[team] * sensitivity * (gap / 0.5)
            elo[team] = elo.get(team, 1600.0) + delta_elo
            adjustments[team] = delta_elo

        steps.append(ConvergenceStep(
            iteration=it, max_gap=float(max_gap), adjustments=adjustments,
        ))

        if not adjustments:
            break

        # recompute model lambdas with new elo (market lambdas restent fixes)
        for g, ms in matches_by_group.items():
            for m in ms:
                lh_m, la_m = elo_to_lambdas(
                    elo.get(m.home, 1600.0), elo.get(m.away, 1600.0)
                )
                m.lambda_model_h = lh_m
                m.lambda_model_a = la_m

    return steps, elo, matches_by_group


# ─────────────────────────────────────────────────────────────────────────────
# Candidats "meilleurs 3emes"
# ─────────────────────────────────────────────────────────────────────────────


def third_place_candidates(elo: dict[str, float]) -> list[str]:
    """Pour chaque poule, on prend l'avant-dernier Elo comme candidat 3eme."""
    out: list[str] = []
    for teams in WC26_GROUPS.values():
        ranked = sorted(teams, key=lambda t: -elo.get(t, 1600.0))
        # 3eme par Elo (index 2 sur 4)
        out.append(ranked[2])
    return out


def team_pools_for_simulation(
    teams: Iterable[str], matches_by_group: dict[str, list[PoolMatch]],
) -> dict[str, dict]:
    """Format attendu par `pool_xg.best_thirds_distribution` (market lambdas)."""
    out: dict[str, dict] = {}
    for t in teams:
        # trouve le groupe
        group = next((g for g, ts in WC26_GROUPS.items() if t in ts), None)
        if not group:
            continue
        views = team_match_views(t, matches_by_group[group])
        lf, la = [], []
        for v in views:
            if v["home"]:
                lf.append(v["lambda_market_h"])
                la.append(v["lambda_market_a"])
            else:
                lf.append(v["lambda_market_a"])
                la.append(v["lambda_market_h"])
        out[t] = {"lambdas_for": lf, "lambdas_against": la}
    return out
