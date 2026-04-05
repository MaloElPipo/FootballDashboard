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


def _poisson_win_prob(lam_t: float, lam_o: float, max_g: int = 10) -> float:
    total = 0.0
    for i in range(max_g + 1):
        for j in range(i):
            total += poisson.pmf(i, lam_t) * poisson.pmf(j, lam_o)
    return total


def lambdas_from_betfair(
    lay_1x2: float,
    lay_u05_team: float,
    odds_00: float,
) -> tuple[float, float]:
    p0_team = 1.0 / lay_u05_team
    lam_t_init = -math.log(max(p0_team, 0.01))

    p00 = 1.0 / odds_00
    p0_opp = p00 / max(p0_team, 0.01)
    p0_opp = max(0.01, min(0.99, p0_opp))
    lam_o_init = -math.log(p0_opp)

    p_win_target = 1.0 / lay_1x2

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
        return err_u05 * 100 + err_00 * 100 + err_win * 10

    res = minimize(objective, np.array([lam_t_init, lam_o_init]),
                   method="Nelder-Mead")
    lt_opt, lo_opt = float(res.x[0]), float(res.x[1])
    if lt_opt <= 0 or lo_opt <= 0:
        return lam_t_init, lam_o_init
    return lt_opt, lo_opt


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
    lay_u05_team: float,
    odds_00: float,
    betclic_odds: float | None = None,
    exact_score_odds: dict[tuple[int, int], float] | None = None,
    n_sims: int = 50_000,
) -> G2Result:
    lambda_team, lambda_opp = lambdas_from_betfair(lay_1x2, lay_u05_team, odds_00)
    method = "Betfair (P(0) + 0-0)"

    if exact_score_odds and len(exact_score_odds) >= 3:
        try:
            lt_mle, lo_mle = lambdas_mle_from_scores(
                exact_score_odds, (lambda_team, lambda_opp)
            )
            lambda_team, lambda_opp = lt_mle, lo_mle
            method = f"MLE ({len(exact_score_odds)} scores exacts)"
        except Exception:
            pass

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
    )


def edge_percent(fair_odds: float, book_odds: float) -> float:
    if fair_odds <= 0:
        return 0.0
    return round(((1.0 / fair_odds) * book_odds - 1.0) * 100.0, 2)


def ev0(prob: float, book_odds: float) -> float:
    return round((prob * book_odds - 1.0) * 100.0, 2)
