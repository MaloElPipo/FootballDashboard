"""Phase 3 — xG totaux poules CDM + meilleurs 3emes ameliores.

Trois briques :

1. **xG par equipe sur phase de poule** : par equipe on calcule
   - xGF_pool_model = somme(lambda_h ou lambda_a) des 3 matchs simules
   - xGF_pool_market = somme(lambda_h ou lambda_a) issus de la triple inversion
     (lambda phase 1) sur les cotes des 3 matchs de poule.

2. **Recalibrage Elo nation (boucle B)** : si |xGF_market - xGF_model| > 0.5
   buts par match en moyenne, on ajuste l'Elo nation (skip nations forced).

3. **Meilleurs 3emes ameliores** : Poisson correle inter-matchs par equipe avec
   un facteur de forme partage sur les 3 matchs. Recalcul P(qualif R32 via 3eme)
   avec la nouvelle distribution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson


# ─────────────────────────────────────────────────────────────────────────────
# Brique 1 : xG poule par equipe (model + market)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class TeamPoolXG:
    team_id: str
    matches: list[dict]  # [{opp, lambda_h, lambda_a, home}]
    xgf_model: float
    xga_model: float
    xgf_market: float
    xga_market: float
    delta_xgf: float  # market - model (positif = on sous-estime l'attaque)
    delta_xga: float
    delta_per_match: float  # |xgf gap| per match, pour le test seuil 0.5


def compute_pool_xg(team_id: str, group_matches: list[dict]) -> TeamPoolXG:
    """Args:
    group_matches: liste de dicts avec :
        - opp: id adversaire
        - home: bool
        - lambda_model_h, lambda_model_a : modele actuel prod
        - lambda_market_h, lambda_market_a : sortie triple inversion phase 1
    """
    xgf_m = xga_m = xgf_mk = xga_mk = 0.0
    for m in group_matches:
        if m["home"]:
            xgf_m += m["lambda_model_h"]
            xga_m += m["lambda_model_a"]
            xgf_mk += m["lambda_market_h"]
            xga_mk += m["lambda_market_a"]
        else:
            xgf_m += m["lambda_model_a"]
            xga_m += m["lambda_model_h"]
            xgf_mk += m["lambda_market_a"]
            xga_mk += m["lambda_market_h"]
    n = max(len(group_matches), 1)
    return TeamPoolXG(
        team_id=team_id,
        matches=group_matches,
        xgf_model=xgf_m,
        xga_model=xga_m,
        xgf_market=xgf_mk,
        xga_market=xga_mk,
        delta_xgf=xgf_mk - xgf_m,
        delta_xga=xga_mk - xga_m,
        delta_per_match=abs(xgf_mk - xgf_m) / n,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Brique 2 : recalibrage Elo (boucle B)
# ─────────────────────────────────────────────────────────────────────────────


def adjust_elo_from_gap(
    elo_current: float,
    delta_per_match: float,
    forced: bool = False,
    sensitivity: float = 100.0,
    threshold: float = 0.5,
) -> tuple[float, str]:
    """Si gap moyen > threshold buts par match, on ajuste l'Elo.

    Returns (new_elo, reason).
    Skip si forced True.
    """
    if forced:
        return elo_current, "SKIP forced"
    if delta_per_match < threshold:
        return elo_current, f"NO_CHANGE gap={delta_per_match:.2f} < {threshold}"
    # market > model = attaque sous-estimee -> elo a la hausse
    # 0.5 buts/match approx 100 Elo (sensitivity ajustable)
    delta_elo = sensitivity * (delta_per_match / 0.5)
    return elo_current + delta_elo, f"ADJUST +{delta_elo:.0f} (gap={delta_per_match:.2f})"


# ─────────────────────────────────────────────────────────────────────────────
# Brique 3 : Poisson correle inter-matchs pour les meilleurs 3emes
# ─────────────────────────────────────────────────────────────────────────────


def simulate_team_pool_correlated(
    lambdas_for: list[float],
    lambdas_against: list[float],
    n_sims: int = 5000,
    form_sigma: float = 0.18,
    seed: int | None = None,
) -> np.ndarray:
    """Simule N tirages de 3 matchs avec facteur de forme partage.

    Modele : facteur f ~ LogNormal(0, form_sigma) tire 1x par sim.
    Tous les matchs de la sim sont scales par f sur l'attaque, 1/f sur la defense.
    Returns array (n_sims, 4) : [pts_total, gf_total, ga_total, won]

    pts : 3W + 1D
    """
    rng = np.random.default_rng(seed)
    n_matches = len(lambdas_for)
    factors = rng.lognormal(mean=0.0, sigma=form_sigma, size=n_sims)
    out = np.zeros((n_sims, 4))
    for s in range(n_sims):
        f = factors[s]
        pts = 0
        gf_tot = 0
        ga_tot = 0
        for i in range(n_matches):
            lh = lambdas_for[i] * f
            la = lambdas_against[i] / max(f, 1e-3)
            gf = rng.poisson(lh)
            ga = rng.poisson(la)
            gf_tot += gf
            ga_tot += ga
            if gf > ga:
                pts += 3
            elif gf == ga:
                pts += 1
        out[s, 0] = pts
        out[s, 1] = gf_tot
        out[s, 2] = ga_tot
        out[s, 3] = pts >= 7  # ~ qualif top 2 souvent
    return out


def best_thirds_distribution(
    team_pools: dict[str, dict],
    n_sims: int = 3000,
    form_sigma: float = 0.18,
    seed: int = 42,
) -> dict[str, dict]:
    """Pour chaque equipe (assumee 3e probable), distribution des points/diff.

    team_pools[team_id] = {lambdas_for: [..3..], lambdas_against: [..3..]}
    Return : team_id -> {pts_mean, pts_p25, pts_p50, pts_p75, diff_mean}
    """
    out = {}
    for tid, pool in team_pools.items():
        sims = simulate_team_pool_correlated(
            pool["lambdas_for"],
            pool["lambdas_against"],
            n_sims=n_sims,
            form_sigma=form_sigma,
            seed=seed,
        )
        pts = sims[:, 0]
        diff = sims[:, 1] - sims[:, 2]
        gf = sims[:, 1]
        out[tid] = {
            "pts_mean": float(pts.mean()),
            "pts_std": float(pts.std()),
            "pts_p25": float(np.percentile(pts, 25)),
            "pts_p50": float(np.percentile(pts, 50)),
            "pts_p75": float(np.percentile(pts, 75)),
            "diff_mean": float(diff.mean()),
            "gf_mean": float(gf.mean()),
            "p_4pts_plus": float((pts >= 4).mean()),
            "p_5pts_plus": float((pts >= 5).mean()),
        }
    return out


def prob_qualif_r32_as_third(
    team_dist: dict, ref_thresholds: dict | None = None
) -> float:
    """P(qualif R32 via 3eme) sachant la distribution simulee de l'equipe.

    Heuristique : pour CDM 26 (12 poules), les 8 meilleurs 3emes passent. Le
    seuil empirique est environ 4 pts + diff buts >= 0 + buts marques >= 3.
    On utilise ces seuils pour estimer la proba.
    """
    th = ref_thresholds or {"pts_min": 4, "diff_min": 0, "gf_min": 3}
    # Sans access aux sims directs ici, on derive depuis p_4pts_plus + bonus diff
    p_pts = team_dist.get("p_4pts_plus", 0.0)
    # ajustement diff/gf : si diff_mean > 0, bonus 1.1
    bonus = 1.0
    if team_dist.get("diff_mean", -1) > 0:
        bonus *= 1.05
    if team_dist.get("gf_mean", 0) >= th["gf_min"]:
        bonus *= 1.05
    # cap a 1.0
    return min(p_pts * bonus, 0.98)


# ─────────────────────────────────────────────────────────────────────────────
# Brique 4 : value bets O/U buts marques par equipe phase poule
# ─────────────────────────────────────────────────────────────────────────────


def value_bets_team_total_goals(
    team_dist: dict,
    market_odds: dict,
    edge_threshold: float = 0.04,
) -> list[dict]:
    """Identifie value bets vs Betclic/Unibet sur 'total buts marques equipe X'.

    market_odds : {threshold (float): {'over': odd, 'under': odd}}
    """
    out = []
    gf_mean = team_dist.get("gf_mean", 0.0)
    # approximation Poisson : P(GF >= k) pour calcul over/under
    # gf_total approx Poisson(gf_mean) (approximation suffisante pour value scan)
    for th, oddpair in market_odds.items():
        try:
            th_float = float(th)
        except (TypeError, ValueError):
            continue
        # over = strictly > th
        k_strict = int(math.floor(th_float)) + 1
        p_over = 1.0 - poisson.cdf(k_strict - 1, gf_mean)
        p_under = 1.0 - p_over
        for side, p, lbl in [(oddpair.get("over"), p_over, "OVER"), (oddpair.get("under"), p_under, "UNDER")]:
            if side is None:
                continue
            try:
                odd = float(side)
            except (TypeError, ValueError):
                continue
            ev = p * odd - 1.0
            if ev > edge_threshold:
                out.append({
                    "threshold": th_float,
                    "side": lbl,
                    "odd": odd,
                    "p_model": p,
                    "ev": ev,
                })
    return out
