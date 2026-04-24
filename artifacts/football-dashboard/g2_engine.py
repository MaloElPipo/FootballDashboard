from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.stats import poisson


@dataclass
class G2Result:
    lambda_team: float
    lambda_opp: float
    xg_match: float
    prob_g2: float
    fair_odds: float
    poisson_matrix: np.ndarray
    method: str
    p0_team: float = 0.0
    p0_opp: float = 0.0


def remove_margin_proportional(odds_h: float, odds_d: float, odds_a: float) -> tuple[float, float, float]:
    n = 3
    margin = (1.0 / odds_h + 1.0 / odds_d + 1.0 / odds_a) - 1.0
    if margin <= 0:
        return odds_h, odds_d, odds_a
    fair_h = n * odds_h / (n - margin * odds_h)
    fair_d = n * odds_d / (n - margin * odds_d)
    fair_a = n * odds_a / (n - margin * odds_a)
    return fair_h, fair_d, fair_a


def remove_margin_2way(odds_a: float, odds_b: float) -> tuple[float, float]:
    n = 2
    margin = (1.0 / odds_a + 1.0 / odds_b) - 1.0
    if margin <= 0:
        return odds_a, odds_b
    fair_a = n * odds_a / (n - margin * odds_a)
    fair_b = n * odds_b / (n - margin * odds_b)
    return fair_a, fair_b


def _bisect_lambda_total_from_u25(p_u25: float) -> float:
    lo, hi = 0.05, 7.0
    for _ in range(40):
        mid = (lo + hi) / 2
        p_calc = math.exp(-mid) * (1 + mid + mid * mid / 2)
        if p_calc > p_u25:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _poisson_home_win(lh: float, la: float, max_g: int = 20) -> float:
    pw = 0.0
    for i in range(1, max_g + 1):
        pi = poisson.pmf(i, lh)
        if pi < 1e-12:
            continue
        for j in range(i):
            pw += pi * poisson.pmf(j, la)
    return pw


def _lambdas_analytical(ph: float, pa: float,
                        ou25_under: float, ou25_over: float,
                        btts_yes: float, btts_no: float) -> tuple[float, float, str]:
    """Mode A : formule fermée 1X2 + O/U 2.5 + BTTS (4 étapes)."""
    fu, fo = remove_margin_2way(ou25_under, ou25_over)
    p_u25 = 1.0 / fu
    fy, fn = remove_margin_2way(btts_yes, btts_no)
    p_btts_no = 1.0 / fn

    lambda_total = _bisect_lambda_total_from_u25(p_u25)
    p00 = math.exp(-lambda_total)
    s = p_btts_no + p00
    disc = s * s - 4 * p00
    if disc < 0:
        disc = 0.0
    sqrt_disc = math.sqrt(disc)
    u_small = max(min((s - sqrt_disc) / 2, 0.999), 1e-6)
    u_large = max(min((s + sqrt_disc) / 2, 0.999), 1e-6)

    if ph >= pa:
        lh = -math.log(u_small)
        la = -math.log(u_large)
    else:
        lh = -math.log(u_large)
        la = -math.log(u_small)
    return lh, la, "Analytique 1X2 + O/U 2.5 + BTTS"


def _lambdas_u25_only(ph: float, pa: float,
                     ou25_under: float, ou25_over: float) -> tuple[float, float, str]:
    """Mode B : λ_total via O/U 2.5 + ratio via bissection P(home_win)=ph_marché."""
    fu, fo = remove_margin_2way(ou25_under, ou25_over)
    p_u25 = 1.0 / fu
    lambda_total = _bisect_lambda_total_from_u25(p_u25)

    lo_r, hi_r = 0.10, 0.90
    for _ in range(25):
        r = (lo_r + hi_r) / 2
        lh_test = lambda_total * r
        la_test = lambda_total * (1 - r)
        pw_calc = _poisson_home_win(lh_test, la_test)
        if pw_calc < ph:
            lo_r = r
        else:
            hi_r = r
    r_final = (lo_r + hi_r) / 2
    lh = lambda_total * r_final
    la = lambda_total * (1 - r_final)
    return lh, la, "Bissection 1X2 + O/U 2.5"


def _lambdas_supremacy_heuristic(ph: float, pa: float) -> tuple[float, float, str]:
    """Mode C : 1X2 seul, heuristique simple."""
    if ph > 0.5:
        lh, la = 1.5, 1.0
    elif ph > 0.35:
        lh, la = 1.3, 1.2
    else:
        lh, la = 1.0, 1.5
    return lh, la, "Heuristique 1X2 seul"


def lambdas_buchdahl(
    odds_h: float,
    odds_d: float,
    odds_a: float,
    ou25_under: float | None = None,
    ou25_over: float | None = None,
    btts_yes: float | None = None,
    btts_no: float | None = None,
) -> tuple[float, float, str]:
    """
    Calcule (λ_home, λ_away, method) selon les marchés disponibles.
    - 1X2 + O/U 2.5 + BTTS → formule analytique fermée (méthode "G2+ adaptée")
    - 1X2 + O/U 2.5         → bissection λ_total + bissection ratio
    - 1X2 seul              → heuristique simple
    """
    fair_h, fair_d, fair_a = remove_margin_proportional(odds_h, odds_d, odds_a)
    ph, pa = 1.0 / fair_h, 1.0 / fair_a

    has_ou25 = (
        ou25_under is not None and ou25_under > 1.0
        and ou25_over is not None and ou25_over > 1.0
    )
    has_btts = (
        btts_yes is not None and btts_yes > 1.0
        and btts_no is not None and btts_no > 1.0
    )

    if has_ou25 and has_btts:
        return _lambdas_analytical(ph, pa, ou25_under, ou25_over, btts_yes, btts_no)
    if has_ou25:
        return _lambdas_u25_only(ph, pa, ou25_under, ou25_over)
    return _lambdas_supremacy_heuristic(ph, pa)


def build_poisson_matrix(
    lambda_team: float, lambda_opp: float, max_goals: int = 8
) -> np.ndarray:
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            matrix[i, j] = poisson.pmf(i, lambda_team) * poisson.pmf(j, lambda_opp)
    return matrix


def _led2_fraction(i: int, j: int) -> float:
    if i < 2:
        return 0.0
    if i >= j + 2:
        return 1.0
    return (i * (i - 1)) / ((j + 2) * (j + 1))


def prob_g2_fixed_fractions(
    lambda_team: float, lambda_opp: float, max_goals: int = 8,
    p_win_market: float | None = None,
) -> float:
    matrix = build_poisson_matrix(lambda_team, lambda_opp, max_goals)
    insurance = 0.0
    p_win_poisson = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            if i > j:
                p_win_poisson += matrix[i, j]
            else:
                frac = _led2_fraction(i, j)
                if frac > 0:
                    insurance += matrix[i, j] * frac
    p_win = p_win_market if p_win_market is not None else p_win_poisson
    return p_win + insurance


def compute_g2(
    odds_h: float,
    odds_d: float,
    odds_a: float,
    team_is_home: bool = True,
    ou25_under: float | None = None,
    ou25_over: float | None = None,
    btts_yes: float | None = None,
    btts_no: float | None = None,
    betclic_odds: float | None = None,
) -> G2Result:
    lam_home, lam_away, method = lambdas_buchdahl(
        odds_h, odds_d, odds_a,
        ou25_under=ou25_under,
        ou25_over=ou25_over,
        btts_yes=btts_yes,
        btts_no=btts_no,
    )

    if team_is_home:
        lambda_team, lambda_opp = lam_home, lam_away
    else:
        lambda_team, lambda_opp = lam_away, lam_home

    p0_team = math.exp(-lambda_team)
    p0_opp = math.exp(-lambda_opp)

    fair_h, fair_d, fair_a = remove_margin_proportional(odds_h, odds_d, odds_a)
    p_win_market = 1.0 / fair_h if team_is_home else 1.0 / fair_a

    matrix = build_poisson_matrix(lambda_team, lambda_opp)
    prob_g2 = prob_g2_fixed_fractions(lambda_team, lambda_opp, p_win_market=p_win_market)
    fair_odds = 1.0 / prob_g2 if prob_g2 > 0 else 999.0

    return G2Result(
        lambda_team=round(lambda_team, 4),
        lambda_opp=round(lambda_opp, 4),
        xg_match=round(lambda_team + lambda_opp, 4),
        prob_g2=round(prob_g2, 6),
        fair_odds=round(fair_odds, 3),
        poisson_matrix=matrix,
        method=method,
        p0_team=round(p0_team, 6),
        p0_opp=round(p0_opp, 6),
    )


def edge_percent(fair_odds: float, book_odds: float) -> float:
    if fair_odds <= 0:
        return 0.0
    return round(((1.0 / fair_odds) * book_odds - 1.0) * 100.0, 2)


def ev0(prob: float, book_odds: float) -> float:
    return round((prob * book_odds - 1.0) * 100.0, 2)
