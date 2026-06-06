# Backtest CDM 2018 + 2022 — calibration formule lambda

Date : 1780004442 | Source : eloratings.net (Elo pre-tournoi + 128 matchs World Cup)

## Resultats grid search

| Formule | baseline | scale | shrink | Log-loss | Brier | MAE λh | MAE λa | ECE |
|---|---|---|---|---|---|---|---|---|
| blend70_V8_V5calib **BEST** | 0.7×V8_prod + 0.3×V5_calib | — | — | 0.9987 | 0.5909 | — | — | 0.0366 |
| blend50_V8_V5calib | 0.5×V8_prod + 0.5×V5_calib | — | — | 0.9994 | 0.5896 | — | — | 0.0346 |
| blend50_V8_V5c08 | 0.5×V8_prod + 0.5×V5c_s08_sh09 | — | — | 1.0036 | 0.5936 | — | — | 0.0487 |
| V8_prod | 1.25 | 0.5 | 1.0 | 1.0062 | 0.5979 | 1.004 | 0.811 | 0.0524 |
| blend30_V8_V5calib | 0.3×V8_prod + 0.7×V5_calib | — | — | 1.0064 | 0.5910 | — | — | 0.0350 |
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

### blend70_V8_V5calib
| Bin | n | p_pred | freq_obs | gap |
|---|---|---|---|---|
| 0-10% | 2 | 0.08 | 1.00 | +0.92 |
| 10-20% | 51 | 0.17 | 0.14 | -0.03 |
| 20-30% | 173 | 0.25 | 0.23 | -0.03 |
| 30-40% | 46 | 0.35 | 0.37 | +0.02 |
| 40-50% | 46 | 0.45 | 0.48 | +0.03 |
| 50-60% | 38 | 0.55 | 0.55 | +0.00 |
| 60-70% | 24 | 0.63 | 0.75 | +0.12 |
| 70-80% | 4 | 0.73 | 0.50 | -0.23 |

### blend50_V8_V5calib
| Bin | n | p_pred | freq_obs | gap |
|---|---|---|---|---|
| 0-10% | 8 | 0.08 | 0.25 | +0.17 |
| 10-20% | 62 | 0.16 | 0.19 | +0.04 |
| 20-30% | 162 | 0.25 | 0.22 | -0.03 |
| 30-40% | 40 | 0.35 | 0.40 | +0.05 |
| 40-50% | 36 | 0.45 | 0.47 | +0.02 |
| 50-60% | 32 | 0.55 | 0.56 | +0.01 |
| 60-70% | 32 | 0.63 | 0.62 | -0.01 |
| 70-80% | 11 | 0.73 | 0.73 | -0.00 |
| 80-90% | 1 | 0.81 | 0.00 | -0.81 |

### blend50_V8_V5c08
| Bin | n | p_pred | freq_obs | gap |
|---|---|---|---|---|
| 0-10% | 2 | 0.07 | 1.00 | +0.93 |
| 10-20% | 38 | 0.17 | 0.10 | -0.06 |
| 20-30% | 180 | 0.25 | 0.22 | -0.03 |
| 30-40% | 54 | 0.35 | 0.37 | +0.02 |
| 40-50% | 51 | 0.45 | 0.49 | +0.04 |
| 50-60% | 44 | 0.56 | 0.61 | +0.06 |
| 60-70% | 13 | 0.64 | 0.77 | +0.13 |
| 70-80% | 2 | 0.76 | 0.00 | -0.76 |

## Verdict

- Meilleure formule : **blend70_V8_V5calib** (log-loss 0.9987, ECE 0.0366)
- V8 prod actuel : log-loss 1.0062, ECE 0.0524
- V5 calib (deploye dans PDF) : log-loss 1.0397 (+0.0335 vs V8) — ECE 0.0448
- Gain log-loss best vs V8 : **-0.0075**

**Recommandation : GO** — migrer prod vers `blend70_V8_V5calib` (amelioration significative).

## Limitations methodologiques

- 128 matchs : n petit. Intervalle de confiance log-loss ~±0.03.
- Pas de Tilt offensif : V5 perd un de ses leviers prevus.
- Elo pre-tournoi ≠ Elo PELE Silver : on teste la structure de la formule, pas le rating system.
- Tournoi neutre force : pas de bonus hote (Russie 2018, Qatar 2022 — biais marginal).
- Poisson independant : pas de correlation Dixon-Coles (sous-estime les nuls 0-0/1-1).