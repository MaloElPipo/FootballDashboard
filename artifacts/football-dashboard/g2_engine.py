from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson


@dataclass
class G2Result:
    lambda_team: float
    lambda_opp: float
    xg_match: float
    prob_g2_mc: float
    prob_g2_fractions: float
    fair_odds_mc: float
    fair_odds_fractions: float
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


def _poisson_win_prob(lam_t: float, lam_o: float, max_g: int = 15) -> float:
    total = 0.0
    for i in range(max_g + 1):
        for j in range(i):
            total += poisson.pmf(i, lam_t) * poisson.pmf(j, lam_o)
    return total


def _poisson_probs_full(lt: float, lo: float, max_g: int = 10):
    pw, pd, pl, pu25 = 0.0, 0.0, 0.0, 0.0
    for i in range(max_g):
        pi = poisson.pmf(i, lt)
        for j in range(max_g):
            pj = poisson.pmf(j, lo)
            p = pi * pj
            if i > j:
                pw += p
            elif i == j:
                pd += p
            else:
                pl += p
            if i + j <= 2:
                pu25 += p
    pbtts = (1 - math.exp(-lt)) * (1 - math.exp(-lo))
    return pw, pd, pl, pu25, pbtts


def lambdas_buchdahl(
    odds_h: float,
    odds_d: float,
    odds_a: float,
    ou25_under: float | None = None,
    ou25_over: float | None = None,
    btts_yes: float | None = None,
    btts_no: float | None = None,
    cs_mids: dict[tuple[int, int], float] | None = None,
) -> tuple[float, float, str]:
    fair_h, fair_d, fair_a = remove_margin_proportional(odds_h, odds_d, odds_a)
    ph, pd_mkt, pa = 1.0 / fair_h, 1.0 / fair_d, 1.0 / fair_a

    has_ou25 = (
        ou25_under is not None and ou25_under > 1.0
        and ou25_over is not None and ou25_over > 1.0
    )
    has_btts = (
        btts_yes is not None and btts_yes > 1.0
        and btts_no is not None and btts_no > 1.0
    )
    has_cs = cs_mids is not None and len(cs_mids) >= 3

    p_u25 = None
    if has_ou25:
        fu, fo = remove_margin_2way(ou25_under, ou25_over)
        p_u25 = 1.0 / fu

    p_btts = None
    if has_btts:
        fy, fn = remove_margin_2way(btts_yes, btts_no)
        p_btts = 1.0 / fy

    cs_norm = None
    if has_cs:
        total_p = sum(1.0 / v for v in cs_mids.values() if v > 1)
        if total_p > 0:
            cs_norm = {k: (1.0 / v) / total_p for k, v in cs_mids.items() if v > 1}
        else:
            has_cs = False

    def objective(params):
        lt, lo = params
        if lt < 0.05 or lo < 0.05 or lt > 6 or lo > 6:
            return 1e10

        pw, pd_v, pl, pu25_v, pbtts_v = _poisson_probs_full(lt, lo)

        total = 0.0
        total += 100.0 * ((pw - ph) ** 2 + (pd_v - pd_mkt) ** 2 + (pl - pa) ** 2)

        if has_ou25 and p_u25 is not None:
            total += 50.0 * (pu25_v - p_u25) ** 2

        if has_btts and p_btts is not None:
            total += 30.0 * (pbtts_v - p_btts) ** 2

        if has_cs and cs_norm:
            ll = 0.0
            for (gi, gj), p_mkt in cs_norm.items():
                p_model = poisson.pmf(gi, lt) * poisson.pmf(gj, lo)
                if p_model > 1e-20:
                    ll += p_mkt * math.log(p_model)
            total += 20.0 * (-ll)

        return total

    if has_ou25 and p_u25 is not None:
        lo_t, hi_t = 0.5, 7.0
        for _ in range(60):
            mid_t = (lo_t + hi_t) / 2
            p = math.exp(-mid_t) * (1 + mid_t + mid_t ** 2 / 2)
            if p > p_u25:
                lo_t = mid_t
            else:
                hi_t = mid_t
        total_xg = (lo_t + hi_t) / 2
        if ph > 0.5:
            ratio = min(0.65, 0.5 + (ph - 0.5) * 0.5)
        elif ph > 0.35:
            ratio = 0.5
        else:
            ratio = max(0.35, 0.5 - (0.35 - ph) * 0.5)
        init = [total_xg * ratio, total_xg * (1 - ratio)]
    else:
        if ph > 0.5:
            init = [1.5, 1.0]
        elif ph > 0.35:
            init = [1.3, 1.2]
        else:
            init = [1.0, 1.5]

    res = minimize(
        objective,
        np.array(init),
        method="Nelder-Mead",
        options={"maxiter": 50000, "xatol": 1e-10, "fatol": 1e-14},
    )
    lt_opt = max(0.1, float(res.x[0]))
    lo_opt = max(0.1, float(res.x[1]))

    parts = ["Buchdahl 1X2"]
    if has_ou25:
        parts.append("O/U 2.5")
    if has_btts:
        parts.append("BTTS")
    if has_cs:
        parts.append(f"CS({len(cs_norm)})")

    return lt_opt, lo_opt, " + ".join(parts)


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


def simulate_g2_monte_carlo(
    lambda_team: float,
    lambda_opp: float,
    n_sims: int = 50_000,
    n_minutes: int = 90,
    seed: int | None = None,
) -> float:
    rng = np.random.default_rng(seed)
    rate_team = lambda_team / n_minutes
    rate_opp = lambda_opp / n_minutes

    goals_team = rng.poisson(rate_team, size=(n_sims, n_minutes))
    goals_opp = rng.poisson(rate_opp, size=(n_sims, n_minutes))

    cum_team = np.cumsum(goals_team, axis=1)
    cum_opp = np.cumsum(goals_opp, axis=1)

    lead = cum_team - cum_opp
    led_by_2 = np.any(lead >= 2, axis=1)
    final_team = cum_team[:, -1]
    final_opp = cum_opp[:, -1]
    team_wins = final_team > final_opp

    g2_wins = led_by_2 | team_wins
    return float(g2_wins.mean())


def compute_g2(
    odds_h: float,
    odds_d: float,
    odds_a: float,
    team_is_home: bool = True,
    ou25_under: float | None = None,
    ou25_over: float | None = None,
    btts_yes: float | None = None,
    btts_no: float | None = None,
    cs_mids: dict[tuple[int, int], float] | None = None,
    betclic_odds: float | None = None,
    n_sims: int = 50_000,
) -> G2Result:
    lam_home, lam_away, method = lambdas_buchdahl(
        odds_h, odds_d, odds_a,
        ou25_under=ou25_under,
        ou25_over=ou25_over,
        btts_yes=btts_yes,
        btts_no=btts_no,
        cs_mids=cs_mids,
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
    prob_mc = simulate_g2_monte_carlo(lambda_team, lambda_opp, n_sims=n_sims)
    prob_frac = prob_g2_fixed_fractions(lambda_team, lambda_opp, p_win_market=p_win_market)

    fair_mc = 1.0 / prob_mc if prob_mc > 0 else 999.0
    fair_frac = 1.0 / prob_frac if prob_frac > 0 else 999.0

    return G2Result(
        lambda_team=round(lambda_team, 4),
        lambda_opp=round(lambda_opp, 4),
        xg_match=round(lambda_team + lambda_opp, 4),
        prob_g2_mc=round(prob_mc, 6),
        prob_g2_fractions=round(prob_frac, 6),
        fair_odds_mc=round(fair_mc, 3),
        fair_odds_fractions=round(fair_frac, 3),
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
