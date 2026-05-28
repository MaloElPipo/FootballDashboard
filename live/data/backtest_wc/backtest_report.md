# Backtest CDM 2018 + 2022 — calibration formule lambda

Date : 1780002008 | Source : eloratings.net (Elo pre-tournoi + 128 matchs World Cup)

## Resultats grid search

| Formule | baseline | scale | shrink | Log-loss | Brier | MAE λh | MAE λa | ECE |
|---|---|---|---|---|---|---|---|---|
| V8_prod **BEST** | 1.25 | 0.5 | 1.0 | 1.0062 | 0.5979 | 1.004 | 0.811 | 0.0524 |
| V5c_s08_sh09 | 1.35 | 0.8 | 0.9 | 1.0103 | 0.5923 | 1.007 | 0.799 | 0.0475 |
| V5e_b13_s08 | 1.3 | 0.8 | 1.0 | 1.0123 | 0.5916 | 0.979 | 0.835 | 0.0388 |
| V5b_s10_sh09 | 1.35 | 1.0 | 0.9 | 1.0241 | 0.5930 | 1.004 | 0.806 | 0.0454 |
| V5f_b13_s10 | 1.3 | 1.0 | 0.95 | 1.0257 | 0.5937 | 1.000 | 0.816 | 0.0386 |
| V5d_s10_sh10 | 1.35 | 1.0 | 1.0 | 1.0264 | 0.5942 | 0.982 | 0.865 | 0.0414 |
| V5_calib | 1.35 | 1.2 | 0.9 | 1.0397 | 0.5982 | 1.013 | 0.816 | 0.0448 |

Benchmark : log-loss uniform (1/3 chaque) = 1.0986

- **Log-loss** : penalise plus les predictions confiantes mais fausses. Plus bas = mieux.
- **Brier** : erreur quadratique moyenne. Plus bas = mieux.
- **MAE λ** : ecart moyen lambda predit vs buts reels. Mesure la qualite du baseline.
- **ECE** (Expected Calibration Error) : moyenne ponderee |p_pred - freq_obs| par bin. Plus bas = mieux calibre.

## Calibration par bin — top 3 formules

### V8_prod
| Bin | n | p_pred | freq_obs | gap |
|---|---|---|---|---|
| 0-10% | 1 | 0.09 | 1.00 | +0.91 |
| 10-20% | 18 | 0.17 | 0.11 | -0.06 |
| 20-30% | 193 | 0.26 | 0.21 | -0.04 |
| 30-40% | 65 | 0.35 | 0.35 | +0.01 |
| 40-50% | 56 | 0.45 | 0.52 | +0.07 |
| 50-60% | 45 | 0.54 | 0.62 | +0.08 |
| 60-70% | 5 | 0.63 | 0.80 | +0.17 |
| 70-80% | 1 | 0.71 | 0.00 | -0.71 |

### V5c_s08_sh09
| Bin | n | p_pred | freq_obs | gap |
|---|---|---|---|---|
| 0-10% | 7 | 0.07 | 0.29 | +0.22 |
| 10-20% | 55 | 0.16 | 0.20 | +0.04 |
| 20-30% | 167 | 0.25 | 0.21 | -0.04 |
| 30-40% | 43 | 0.35 | 0.40 | +0.05 |
| 40-50% | 42 | 0.45 | 0.45 | +0.00 |
| 50-60% | 38 | 0.56 | 0.55 | -0.00 |
| 60-70% | 26 | 0.64 | 0.73 | +0.09 |
| 70-80% | 4 | 0.73 | 1.00 | +0.27 |
| 80-90% | 2 | 0.82 | 0.00 | -0.82 |

### V5e_b13_s08
| Bin | n | p_pred | freq_obs | gap |
|---|---|---|---|---|
| 0-10% | 12 | 0.07 | 0.25 | +0.17 |
| 10-20% | 58 | 0.16 | 0.19 | +0.03 |
| 20-30% | 159 | 0.25 | 0.21 | -0.03 |
| 30-40% | 42 | 0.35 | 0.38 | +0.03 |
| 40-50% | 36 | 0.45 | 0.50 | +0.05 |
| 50-60% | 32 | 0.55 | 0.53 | -0.02 |
| 60-70% | 33 | 0.64 | 0.64 | +0.00 |
| 70-80% | 10 | 0.73 | 0.80 | +0.07 |
| 80-90% | 2 | 0.85 | 0.00 | -0.85 |

## Verdict

- Meilleure formule : **V8_prod** (log-loss 1.0062, ECE 0.0524)
- V8 prod actuel : log-loss 1.0062, ECE 0.0524
- V5 calib (deploye dans PDF) : log-loss 1.0397 (+0.0335 vs V8) — ECE 0.0448
- Gain log-loss best vs V8 : **+0.0000**

**Recommandation : NO-GO** — aucune formule alternative ne bat V8 prod sur 128 matchs. Garder l'existant.

## Limitations methodologiques

- 128 matchs : n petit. Intervalle de confiance log-loss ~±0.03.
- Pas de Tilt offensif : V5 perd un de ses leviers prevus.
- Elo pre-tournoi ≠ Elo PELE Silver : on teste la structure de la formule, pas le rating system.
- Tournoi neutre force : pas de bonus hote (Russie 2018, Qatar 2022 — biais marginal).
- Poisson independant : pas de correlation Dixon-Coles (sous-estime les nuls 0-0/1-1).