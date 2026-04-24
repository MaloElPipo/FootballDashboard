"""
Test de NON-RÉGRESSION Garantie 2+

Compare la cote juste G2 calculée par :
  - MÉTHODE A (actuelle) : lambdas_buchdahl Nelder-Mead → compute_g2
  - MÉTHODE B (nouvelle) : lambdas_analytical fermée → compute_g2 (mêmes blocs aval)

Le bloc aval (Poisson matrix + Monte Carlo + fractions fixes) est IDENTIQUE
dans les 2 cas. Seule la façon d'obtenir λ_h / λ_a change.

Critères de migration safe :
  - Écart médian sur cote G2 < 1%   → migration safe
  - Écart médian < 3% et max < 10%  → migration acceptable
  - Sinon                            → on ne migre pas
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from g2_engine import (
    lambdas_buchdahl,
    remove_margin_proportional,
    simulate_g2_monte_carlo,
    prob_g2_fixed_fractions,
)
from compare_lambda_methods import (
    lambdas_analytical, fetch_matches, extract_consensus_odds, N_MATCHES,
)


def g2_from_lambdas(lh, la, p_h_devig, p_a_devig, team_is_home, n_sims=50_000):
    """Bloc aval Garantie 2+ identique à compute_g2, à partir de λ déjà donnés."""
    if team_is_home:
        lt, lo, p_win = lh, la, p_h_devig
    else:
        lt, lo, p_win = la, lh, p_a_devig
    prob_mc = simulate_g2_monte_carlo(lt, lo, n_sims=n_sims, seed=42)
    prob_frac = prob_g2_fixed_fractions(lt, lo, p_win_market=p_win)
    return (1.0 / prob_mc, 1.0 / prob_frac, lt, lo)


def main():
    print("=" * 92)
    print("TEST DE NON-RÉGRESSION GARANTIE 2+")
    print("Méthode A (actuelle, Nelder-Mead)  vs  Méthode B (nouvelle, analytique fermée)")
    print("=" * 92)

    raw = fetch_matches()
    matches = [m for m in (extract_consensus_odds(x) for x in raw) if m][:N_MATCHES]
    print(f"\n{len(matches)} matchs Bundesliga analysés\n")

    rows = []  # (label, team_is_home, fair_A_mc, fair_B_mc, fair_A_frac, fair_B_frac, lA, lB)

    for x in matches:
        h, d, a = x["h2h"]
        u25, o25 = x["totals_25"]
        by, bn = x["btts"]

        # MÉTHODE A : Nelder-Mead actuel (sans cs_mids puisque The Odds API n'en a pas)
        lA_h, lA_a, _ = lambdas_buchdahl(
            h, d, a,
            ou25_under=u25, ou25_over=o25,
            btts_yes=by, btts_no=bn,
        )

        # MÉTHODE B : analytique fermée
        lB_h, lB_a, dbg = lambdas_analytical(h, d, a, u25, o25, by, bn)

        ph = dbg["p_h_devig"]
        pa = dbg["p_a_devig"]

        # Pour chaque équipe (home + away) on calcule les 2 cotes G2
        for is_home, side in [(True, "HOME"), (False, "AWAY")]:
            fA_mc, fA_fr, ltA, loA = g2_from_lambdas(lA_h, lA_a, ph, pa, is_home)
            fB_mc, fB_fr, ltB, loB = g2_from_lambdas(lB_h, lB_a, ph, pa, is_home)
            team = x["home"] if is_home else x["away"]
            label = f"{team[:18]:<18} ({side[0]})"
            rows.append((label, fA_mc, fB_mc, fA_fr, fB_fr, ltA, ltB, loA, loB))

    # Affichage
    print(f"{'Équipe':<24} {'cote G2 Monte Carlo':>30} {'cote G2 Fractions fixes':>30}")
    print(f"{'':<24} {'A_actu  B_new   Δ%':>30} {'A_actu  B_new   Δ%':>30}")
    print("-" * 92)

    delta_mc, delta_frac = [], []
    for label, fAm, fBm, fAf, fBf, *_ in rows:
        d_mc = (fBm / fAm - 1.0) * 100
        d_fr = (fBf / fAf - 1.0) * 100
        delta_mc.append(d_mc)
        delta_frac.append(d_fr)
        print(f"{label:<24}    {fAm:>5.3f}  {fBm:>5.3f}  {d_mc:>+6.2f}%      "
              f"   {fAf:>5.3f}  {fBf:>5.3f}  {d_fr:>+6.2f}%")
    print("-" * 92)

    def stats(deltas, name):
        n = len(deltas)
        absd = [abs(d) for d in deltas]
        absd.sort()
        med = absd[n // 2]
        mx = max(absd)
        mean_signed = sum(deltas) / n
        return f"  {name}: |Δ| médian={med:.2f}%   |Δ| max={mx:.2f}%   Δ moyen signé={mean_signed:+.2f}%"

    print("\nÉCARTS (B vs A) :")
    print(stats(delta_mc, "Monte Carlo  "))
    print(stats(delta_frac, "Fractions fix"))

    # Verdict automatique
    abs_med_mc = sorted([abs(d) for d in delta_mc])[len(delta_mc) // 2]
    abs_max_mc = max(abs(d) for d in delta_mc)
    print("\nVERDICT (sur cote Monte Carlo, plus représentative) :")
    if abs_med_mc < 1.0 and abs_max_mc < 5.0:
        print(f"  ✓ MIGRATION SAFE — écart médian {abs_med_mc:.2f}% < 1% et max {abs_max_mc:.2f}% < 5%")
    elif abs_med_mc < 3.0 and abs_max_mc < 10.0:
        print(f"  ~ MIGRATION ACCEPTABLE — écart médian {abs_med_mc:.2f}% < 3% et max {abs_max_mc:.2f}% < 10%")
    else:
        print(f"  ✗ NE PAS MIGRER — écart médian {abs_med_mc:.2f}% ou max {abs_max_mc:.2f}% trop élevé")

    # Détail premier match (pédagogique)
    print("\n" + "=" * 92)
    label, fAm, fBm, fAf, fBf, ltA, ltB, loA, loB = rows[0]
    print(f"DÉTAIL PREMIER CAS : {label}")
    print("=" * 92)
    print(f"  Méthode A : λ_team={ltA:.3f}  λ_opp={loA:.3f}  → P(0)_team=e^(-λ)={math.exp(-ltA):.4f}")
    print(f"  Méthode B : λ_team={ltB:.3f}  λ_opp={loB:.3f}  → P(0)_team=e^(-λ)={math.exp(-ltB):.4f}")
    print(f"  Cote G2 Monte Carlo (50k sims, seed=42) : A={fAm:.3f}  B={fBm:.3f}  → écart {(fBm/fAm-1)*100:+.2f}%")
    print(f"  Cote G2 Fractions fixes                 : A={fAf:.3f}  B={fBf:.3f}  → écart {(fBf/fAf-1)*100:+.2f}%")
    print()
    print("  Rappel : le bloc 'cote G2' (Poisson matrix + MC + fractions) est IDENTIQUE")
    print("  dans les 2 méthodes. L'écart vient UNIQUEMENT de la différence sur λ.")


if __name__ == "__main__":
    main()
