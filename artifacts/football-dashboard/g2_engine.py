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


def lambdas_cascade(
    lay_1x2_team: float,
    ou25_under_mid: float | None = None,
    btts_yes_mid: float | None = None,
    ou05_under_mid: float | None = None,
    cs_mids: dict[tuple[int, int], float] | None = None,
) -> tuple[float, float, str]:
    p_win = 1.0 / lay_1x2_team

    has_ou25 = ou25_under_mid is not None and ou25_under_mid > 1.0
    has_btts = btts_yes_mid is not None and btts_yes_mid > 1.0
    has_ou05 = ou05_under_mid is not None and ou05_under_mid > 1.0
    has_cs = cs_mids is not None and len(cs_mids) >= 3

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

        total = 0.0

        pw = _poisson_win_prob(lt, lo)
        total += 10.0 * (pw - p_win) ** 2

        if has_ou25:
            s = lt + lo
            pu25 = math.exp(-s) * (1 + s + s * s / 2)
            total += 50.0 * (pu25 - 1.0 / ou25_under_mid) ** 2

        if has_btts:
            pbtts = (1 - math.exp(-lt)) * (1 - math.exp(-lo))
            total += 30.0 * (pbtts - 1.0 / btts_yes_mid) ** 2

        if has_ou05:
            pu05 = math.exp(-(lt + lo))
            total += 20.0 * (pu05 - 1.0 / ou05_under_mid) ** 2

        if has_cs and cs_norm:
            ll = 0.0
            for (gi, gj), p_mkt in cs_norm.items():
                p_model = poisson.pmf(gi, lt) * poisson.pmf(gj, lo)
                if p_model > 1e-20:
                    ll += p_mkt * math.log(p_model)
            total += 5.0 * (-ll)

        return total

    if has_ou25:
        p_u25 = 1.0 / ou25_under_mid
        lo_t, hi_t = 0.5, 7.0
        for _ in range(60):
            mid_t = (lo_t + hi_t) / 2
            p = math.exp(-mid_t) * (1 + mid_t + mid_t ** 2 / 2)
            if p > p_u25:
                lo_t = mid_t
            else:
                hi_t = mid_t
        total_xg = (lo_t + hi_t) / 2
        if p_win > 0.5:
            ratio = min(0.65, 0.5 + (p_win - 0.5) * 0.5)
        elif p_win > 0.35:
            ratio = 0.5
        else:
            ratio = max(0.35, 0.5 - (0.35 - p_win) * 0.5)
        init = [total_xg * ratio, total_xg * (1 - ratio)]
    else:
        if p_win > 0.5:
            init = [1.5, 1.0]
        elif p_win > 0.35:
            init = [1.3, 1.2]
        else:
            init = [1.0, 1.5]

    res = minimize(
        objective,
        np.array(init),
        method="Nelder-Mead",
        options={"maxiter": 15000, "xatol": 1e-8, "fatol": 1e-12},
    )
    lt_opt = max(0.1, float(res.x[0]))
    lo_opt = max(0.1, float(res.x[1]))

    parts = ["1X2 Lay"]
    if has_ou25:
        parts.append("O/U 2.5")
    if has_btts:
        parts.append("BTTS")
    if has_ou05:
        parts.append("O/U 0.5")
    if has_cs:
        parts.append(f"CS({len(cs_norm)})")

    return lt_opt, lo_opt, " + ".join(parts)


def lambdas_from_betfair(
    lay_1x2: float,
    lay_u05_team: float,
    odds_00: float,
    ou25_under_mid: float | None = None,
    btts_yes_mid: float | None = None,
) -> tuple[float, float, str]:
    p0_team = 1.0 / lay_u05_team
    lam_t_init = -math.log(max(p0_team, 0.01))

    p00 = 1.0 / odds_00
    p0_opp = p00 / max(p0_team, 0.01)
    p0_opp = max(0.01, min(0.99, p0_opp))
    lam_o_init = -math.log(p0_opp)

    p_win_target = 1.0 / lay_1x2

    has_ou25 = ou25_under_mid is not None and ou25_under_mid > 1.0
    has_btts = btts_yes_mid is not None and btts_yes_mid > 1.0

    def objective(params: np.ndarray) -> float:
        lt, lo = params
        if lt <= 0 or lo <= 0:
            return 1e10
        p0_t = math.exp(-lt)
        p0_o = math.exp(-lo)
        err_u05 = (p0_t - p0_team) ** 2
        err_00 = (p0_t * p0_o - p00) ** 2
        p_win = _poisson_win_prob(lt, lo)
        err_win = (p_win - p_win_target) ** 2
        total = err_u05 * 100 + err_00 * 100 + err_win * 10
        if has_ou25:
            s = lt + lo
            pu25 = math.exp(-s) * (1 + s + s * s / 2)
            total += 50.0 * (pu25 - 1.0 / ou25_under_mid) ** 2
        if has_btts:
            pbtts = (1 - math.exp(-lt)) * (1 - math.exp(-lo))
            total += 30.0 * (pbtts - 1.0 / btts_yes_mid) ** 2
        return total

    res = minimize(objective, np.array([lam_t_init, lam_o_init]),
                   method="Nelder-Mead",
                   options={"maxiter": 15000, "xatol": 1e-8, "fatol": 1e-12})
    lt_opt, lo_opt = float(res.x[0]), float(res.x[1])
    if lt_opt <= 0 or lo_opt <= 0:
        lt_opt, lo_opt = lam_t_init, lam_o_init

    parts = ["BF P(0)team", "BF 0-0", "BF 1X2"]
    if has_ou25:
        parts.append("BF O/U 2.5")
    if has_btts:
        parts.append("BF BTTS")
    return lt_opt, lo_opt, " + ".join(parts)


def lambdas_mle_from_scores(
    exact_score_odds: dict[tuple[int, int], float],
    lambda_init: tuple[float, float] | None = None,
) -> tuple[float, float]:
    if not exact_score_odds:
        raise ValueError("No exact score odds provided")

    scores = list(exact_score_odds.keys())
    probs_market = np.array([1.0 / exact_score_odds[s] for s in scores])
    probs_market = probs_market / probs_market.sum()

    def neg_log_likelihood(params: np.ndarray) -> float:
        lam_t, lam_o = params
        if lam_t <= 0 or lam_o <= 0:
            return 1e10
        ll = 0.0
        for (i, j), p_mkt in zip(scores, probs_market):
            p_model = poisson.pmf(i, lam_t) * poisson.pmf(j, lam_o)
            if p_model > 0:
                ll += p_mkt * math.log(p_model)
        return -ll

    init = np.array(lambda_init if lambda_init else [1.3, 1.0])
    res = minimize(neg_log_likelihood, init, method="Nelder-Mead",
                   bounds=[(0.05, 5.0), (0.05, 5.0)])
    return float(res.x[0]), float(res.x[1])


def build_poisson_matrix(
    lambda_team: float, lambda_opp: float, max_goals: int = 8
) -> np.ndarray:
    matrix = np.zeros((max_goals + 1, max_goals + 1))
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            matrix[i, j] = poisson.pmf(i, lambda_team) * poisson.pmf(j, lambda_opp)
    return matrix


_LED2_FRACTIONS: dict[tuple[int, int], float] = {}

for _i in range(9):
    for _j in range(9):
        _LED2_FRACTIONS[(_i, _j)] = 0.0

for _i in range(2, 9):
    _LED2_FRACTIONS[(_i, 0)] = 1.0
for _i in range(9):
    for _j in range(9):
        if _i >= _j + 2:
            _LED2_FRACTIONS[(_i, _j)] = 1.0

_LED2_FRACTIONS[(2, 1)] = 1.0 / 3.0
_LED2_FRACTIONS[(3, 2)] = 1.0 / 3.0
_LED2_FRACTIONS[(4, 3)] = 1.0 / 3.0
_LED2_FRACTIONS[(5, 4)] = 1.0 / 3.0
_LED2_FRACTIONS[(6, 5)] = 1.0 / 3.0

_LED2_FRACTIONS[(2, 2)] = 1.0 / 6.0
_LED2_FRACTIONS[(3, 3)] = 1.0 / 6.0
_LED2_FRACTIONS[(4, 4)] = 1.0 / 6.0
_LED2_FRACTIONS[(5, 5)] = 1.0 / 6.0


def prob_g2_fixed_fractions(
    lambda_team: float, lambda_opp: float, max_goals: int = 8
) -> float:
    matrix = build_poisson_matrix(lambda_team, lambda_opp, max_goals)
    total = 0.0
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            if i > j:
                total += matrix[i, j]
            else:
                frac = _LED2_FRACTIONS.get((i, j), 0.0)
                if frac > 0:
                    total += matrix[i, j] * frac
    return total


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
    lay_1x2: float,
    ou25_under_mid: float | None = None,
    btts_yes_mid: float | None = None,
    ou05_under_mid: float | None = None,
    cs_mids: dict[tuple[int, int], float] | None = None,
    betclic_odds: float | None = None,
    n_sims: int = 50_000,
    bf_u05_team: float | None = None,
    bf_00: float | None = None,
) -> G2Result:
    has_betfair_p0 = (
        bf_u05_team is not None and bf_u05_team > 1.0
        and bf_00 is not None and bf_00 > 1.0
    )

    if has_betfair_p0:
        lambda_team, lambda_opp, method = lambdas_from_betfair(
            lay_1x2, bf_u05_team, bf_00,
            ou25_under_mid=ou25_under_mid,
            btts_yes_mid=btts_yes_mid,
        )
    else:
        lambda_team, lambda_opp, method = lambdas_cascade(
            lay_1x2, ou25_under_mid, btts_yes_mid, ou05_under_mid, cs_mids
        )

    p0_team = math.exp(-lambda_team)
    p0_opp = math.exp(-lambda_opp)

    matrix = build_poisson_matrix(lambda_team, lambda_opp)
    prob_mc = simulate_g2_monte_carlo(lambda_team, lambda_opp, n_sims=n_sims)
    prob_frac = prob_g2_fixed_fractions(lambda_team, lambda_opp)

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
