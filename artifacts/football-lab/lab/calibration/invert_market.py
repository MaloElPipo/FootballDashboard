"""Inversion du marche : extraire (lambda_home, lambda_away, rho) depuis les cotes.

Deux methodes :

  invert_double(p_h, p_d, p_a, p_over25)
      Methode actuelle prod : Poisson independants, 2 parametres.
      Le marche BTTS n'est pas utilise comme contrainte.

  invert_triple(p_h, p_d, p_a, p_over25, p_btts)
      Nouvelle methode : Dixon-Coles 3 parametres avec terme de correlation rho
      sur les bas scores. Utilise les 5 contraintes du marche (surdetermine).

Sortie : un dict {lambda_h, lambda_a, rho, residuals, ok} ou ok=False si
l'optimiseur n'a pas converge.

Le terme tau de Dixon-Coles ajuste les 4 cellules 0-0, 0-1, 1-0, 1-1 :

    tau(0,0) = 1 - lambda_h * lambda_a * rho
    tau(0,1) = 1 + lambda_h * rho
    tau(1,0) = 1 + lambda_a * rho
    tau(1,1) = 1 - rho
    tau(x,y) = 1                          sinon

PMF jointe : P(x,y) = tau(x,y) * Pois(x; lambda_h) * Pois(y; lambda_a)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

MAX_GOALS = 12  # tronquer la sommation Poisson


@dataclass
class InversionResult:
    lambda_h: float
    lambda_a: float
    rho: float
    residuals: dict[str, float] = field(default_factory=dict)
    ok: bool = True
    method: str = ""
    cost: float = 0.0

    def to_dict(self) -> dict:
        return {
            "lambda_h": round(self.lambda_h, 4),
            "lambda_a": round(self.lambda_a, 4),
            "rho": round(self.rho, 4),
            "residuals": {k: round(v, 4) for k, v in self.residuals.items()},
            "ok": self.ok,
            "method": self.method,
            "cost": round(self.cost, 6),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers PMF Dixon-Coles
# ─────────────────────────────────────────────────────────────────────────────


def _tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1.0 - lh * la * rho
    if x == 0 and y == 1:
        return 1.0 + lh * rho
    if x == 1 and y == 0:
        return 1.0 + la * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def joint_matrix(
    lambda_h: float, lambda_a: float, rho: float = 0.0, max_goals: int = MAX_GOALS
) -> np.ndarray:
    """Matrice (max_goals+1, max_goals+1) des probas P(home=x, away=y).

    Si rho=0 c'est du Poisson independant pur. Sinon Dixon-Coles.
    """
    xs = np.arange(max_goals + 1)
    pmf_h = poisson.pmf(xs, lambda_h)
    pmf_a = poisson.pmf(xs, lambda_a)
    M = np.outer(pmf_h, pmf_a)
    if rho != 0.0:
        # ajustement uniquement sur les 4 cellules basses
        for x in (0, 1):
            for y in (0, 1):
                M[x, y] *= _tau(x, y, lambda_h, lambda_a, rho)
        # renormaliser (la masse perdue/gagnee est tres faible mais on la corrige)
        s = M.sum()
        if s > 0:
            M /= s
    return M


def derived_probs(
    lambda_h: float, lambda_a: float, rho: float = 0.0, threshold: float = 2.5
) -> dict[str, float]:
    """Calcule (p_h, p_d, p_a, p_over, p_btts) depuis la matrice jointe."""
    M = joint_matrix(lambda_h, lambda_a, rho)
    n = M.shape[0]
    p_h = float(np.sum(np.tril(M, -1)))  # home > away
    p_a = float(np.sum(np.triu(M, 1)))  # away > home
    p_d = float(np.trace(M))
    # over/under : somme i+j > seuil
    i_idx, j_idx = np.indices(M.shape)
    p_over = float(np.sum(M[(i_idx + j_idx) > threshold]))
    # btts : home>=1 et away>=1
    p_btts = float(np.sum(M[1:, 1:]))
    return {
        "p_h": p_h,
        "p_d": p_d,
        "p_a": p_a,
        "p_over": p_over,
        "p_btts": p_btts,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Inversions
# ─────────────────────────────────────────────────────────────────────────────


def invert_double(
    p_h: float, p_d: float, p_a: float, p_over25: float
) -> InversionResult:
    """Methode actuelle prod : Poisson independants, 4 contraintes (1X2 + O2.5).

    BTTS non utilise. rho fixe a 0.
    """

    def residuals(x: np.ndarray) -> np.ndarray:
        lh, la = x
        if lh <= 0 or la <= 0:
            return np.array([1e3] * 4)
        d = derived_probs(lh, la, rho=0.0)
        return np.array(
            [
                d["p_h"] - p_h,
                d["p_d"] - p_d,
                d["p_a"] - p_a,
                d["p_over"] - p_over25,
            ]
        )

    # seed raisonnable a partir des cotes
    seed_total = 2.5 if p_over25 >= 0.5 else 2.2
    seed_home_share = 0.55 if p_h > p_a else 0.45
    x0 = np.array([seed_total * seed_home_share, seed_total * (1 - seed_home_share)])

    try:
        res = least_squares(
            residuals, x0, bounds=([0.05, 0.05], [6.0, 6.0]), max_nfev=200
        )
        d = derived_probs(res.x[0], res.x[1], rho=0.0)
        return InversionResult(
            lambda_h=float(res.x[0]),
            lambda_a=float(res.x[1]),
            rho=0.0,
            residuals={
                "1": d["p_h"] - p_h,
                "X": d["p_d"] - p_d,
                "2": d["p_a"] - p_a,
                "O2.5": d["p_over"] - p_over25,
                "BTTS": d["p_btts"] - 0.0,  # info, non contraint
            },
            ok=res.success,
            method="double_indep",
            cost=float(res.cost),
        )
    except Exception as e:
        return InversionResult(0, 0, 0, ok=False, method=f"double_indep:err:{e}")


def invert_triple(
    p_h: float,
    p_d: float,
    p_a: float,
    p_over25: float,
    p_btts: float,
) -> InversionResult:
    """Nouvelle methode : Dixon-Coles 3 params, 5 contraintes (1X2 + O2.5 + BTTS).

    Surdetermine => moindres carres ponderes.
    """
    weights = np.array(
        [
            1.0,  # 1
            1.0,  # X
            1.0,  # 2
            1.2,  # O2.5 (contrainte plus structurante sur total)
            1.5,  # BTTS (nouvelle contrainte qu'on veut respecter fortement)
        ]
    )

    def residuals(x: np.ndarray) -> np.ndarray:
        lh, la, rho = x
        if lh <= 0 or la <= 0:
            return np.array([1e3] * 5)
        # contrainte de bornes Dixon-Coles sur rho : max(-1/lh, -1/la) <= rho <= min(1/(lh*la), 1)
        rho_max = min(1.0 / max(lh * la, 1e-6), 1.0)
        rho_min = max(-1.0 / max(lh, 1e-6), -1.0 / max(la, 1e-6))
        if rho < rho_min or rho > rho_max:
            return np.array([1e3] * 5)
        d = derived_probs(lh, la, rho=rho)
        r = np.array(
            [
                d["p_h"] - p_h,
                d["p_d"] - p_d,
                d["p_a"] - p_a,
                d["p_over"] - p_over25,
                d["p_btts"] - p_btts,
            ]
        )
        return r * weights

    # seed depuis l'inversion double
    seed = invert_double(p_h, p_d, p_a, p_over25)
    x0 = np.array([seed.lambda_h, seed.lambda_a, 0.0])

    try:
        res = least_squares(
            residuals,
            x0,
            bounds=([0.05, 0.05, -0.4], [6.0, 6.0, 0.4]),
            max_nfev=400,
        )
        lh, la, rho = float(res.x[0]), float(res.x[1]), float(res.x[2])
        d = derived_probs(lh, la, rho=rho)
        return InversionResult(
            lambda_h=lh,
            lambda_a=la,
            rho=rho,
            residuals={
                "1": d["p_h"] - p_h,
                "X": d["p_d"] - p_d,
                "2": d["p_a"] - p_a,
                "O2.5": d["p_over"] - p_over25,
                "BTTS": d["p_btts"] - p_btts,
            },
            ok=res.success,
            method="triple_dixon_coles",
            cost=float(res.cost),
        )
    except Exception as e:
        return InversionResult(0, 0, 0, ok=False, method=f"triple_dc:err:{e}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers cotes <-> probas (avec retrait de marge)
# ─────────────────────────────────────────────────────────────────────────────


def odds_to_probs_1x2(odd_h: float, odd_d: float, odd_a: float) -> tuple[float, ...]:
    """Convertit 3 cotes 1X2 en probas normalisees (retrait marge proportionnel)."""
    inv = (1 / odd_h, 1 / odd_d, 1 / odd_a)
    s = sum(inv)
    return tuple(x / s for x in inv)


def odds_to_prob_binary(odd_yes: float, odd_no: float) -> float:
    """Convertit 2 cotes O/U ou BTTS Y/N en proba 'yes' normalisee."""
    inv_y = 1 / odd_yes
    inv_n = 1 / odd_no
    return inv_y / (inv_y + inv_n)


def score_log_loss(p_home_win: float, p_draw: float, p_away_win: float, outcome: str) -> float:
    """Log-loss 1X2 d'une prediction vs resultat reel ('H', 'D', 'A')."""
    eps = 1e-12
    if outcome == "H":
        return -math.log(max(p_home_win, eps))
    if outcome == "D":
        return -math.log(max(p_draw, eps))
    if outcome == "A":
        return -math.log(max(p_away_win, eps))
    raise ValueError(f"outcome inconnu : {outcome}")
