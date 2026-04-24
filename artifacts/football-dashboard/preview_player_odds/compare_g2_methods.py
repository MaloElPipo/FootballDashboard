"""
[ARCHIVÉ — 2026-04-24]

Ce script servait au test de NON-RÉGRESSION pré-migration de Garantie 2+ :
  - MÉTHODE A (avant) : lambdas_buchdahl Nelder-Mead + Monte Carlo 50k + fractions fixes
  - MÉTHODE B (après) : lambdas analytique fermée + fractions fixes (sans MC)

Conclusion de la campagne :
  - Cote G2 fractions fixes (utilisée en prod) : écart médian 0.36%, max 0.73%
  - Cote G2 Monte Carlo : médian 10% (bruit MC ~1/sqrt(n_sims), non utilisé pour décisions)
  - Verdict : MIGRATION SAFE → Méthode B activée en prod le 2026-04-24.

Le script ne tourne plus car g2_engine.simulate_g2_monte_carlo a été supprimé
en même temps que la méthode A. Conservé comme trace historique uniquement.
"""

if __name__ == "__main__":
    print(__doc__)
