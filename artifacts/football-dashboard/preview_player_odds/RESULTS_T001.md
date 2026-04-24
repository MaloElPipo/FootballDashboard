# T001 — Backtest réaliste Bundesliga 2025/26 — RÉSULTATS

**Date**: 2026-04-24
**Périmètre**: 270 matchs Bundesliga 25/26, 9 263 prédictions joueur (après filtre cold-start `n_pool ≥ 3`).

## Setup réaliste (zéro data leakage)

| Composant | Source |
|---|---|
| xG team prédit | Odds closing **Pinnacle** (150/270) + **Bet365** fallback (120/270) du CSV Football-Data.co.uk → résolu analytiquement (bissection sur Poisson U2.5 + split par supremacy) |
| Squad probable | 5 derniers matchs joueur : starter (mins ≥ 60) → 78', sub (0 < mins < 60) → 25', sinon exclu |
| Stats joueur | `aggregate_player_pool` filtré sur dates `< match_date` (leave-one-out) |
| Shrinkage | k=8 prior bayésien (LP_XG90 = 0.10, LP_XA90 = 0.08) |
| **Non-participants inclus** | **OUI** — 25.5% des joueurs prévus n'ont finalement pas joué |

## Métriques globales

### Anytime Goalscorer (base rate 6.90%)
| Métrique | **Modèle** | Uniform (xG/N) | Global rate |
|---|---|---|---|
| Brier (↓) | **0.0605** | 0.0634 | 0.0642 |
| LogLoss (↓) | **0.2271** | 0.2455 | 0.2510 |
| AUC (↑) | **0.7286** | 0.6189 | 0.5000 |

### Anytime Assist (base rate 5.12%)
| Métrique | **Modèle** | Uniform (xA/N) | Global rate |
|---|---|---|---|
| Brier (↓) | **0.0473** | 0.0481 | 0.0486 |
| LogLoss (↓) | **0.1903** | 0.1980 | 0.2019 |
| AUC (↑) | **0.6903** | 0.6167 | 0.5000 |

## Calibration

### Scorer
| Bin | n | predicted | observed | gap |
|---|---|---|---|---|
| [0-10%) | 7 343 | 5.0% | 4.5% | bonne |
| [10-20%) | 1 382 | 15.0% | 12.2% | -2.8 pp |
| [20-30%) | 346 | 25.0% | 22.8% | -2.2 pp |
| [30-40%) | 141 | 35.0% | 27.0% | **-8.0 pp (sur-confiance)** |
| [40-50%) | 39 | 45.0% | 38.5% | -6.5 pp |
| [50-60%) | 12 | 55.0% | 58.3% | OK |

→ Le modèle **sur-estime légèrement** dans la zone 30-50% (joueurs offensifs élite). Probablement parce que le ratio xA cible (0.65 × xG team) est encore arbitraire et que la régression vers la moyenne n'est pas assez forte sur les petits échantillons en début de saison.

### Assist
| Bin | n | predicted | observed |
|---|---|---|---|
| [0-10%) | 8 247 | 5.0% | 4.2% |
| [10-20%) | 924 | 15.0% | 11.8% |
| [20-30%) | 80 | 25.0% | 20.0% |
| [30-40%) | 12 | 35.0% | 41.7% |

## ROI simulé — ⚠️ TEST CIRCULAIRE

```
ROI scorer p>15% : -20.1% (954 picks)
ROI scorer p>25% : -17.1% (325 picks)
ROI scorer p>40% : -15.2% (51 picks)
ROI assist p>25% : +1.5%  (30 picks)
ROI assist p>30% : +16.0% (12 picks, échantillon trop petit)
```

**⚠️ Limitation méthodologique majeure** : la simulation utilise `odd_book = 1 / (p_model × 1.08)` comme proxy d'odds bookmaker. C'est **auto-référentiel** :
- Si le modèle est parfaitement calibré → ROI = 0% (vig 8% absorbé)
- Si le modèle sur-estime → ROI < 0
- Si le modèle sous-estime → ROI > 0

**Cette simulation mesure la calibration, pas la viabilité économique.** Le seul vrai test ROI nécessite des **odds player-props réels** des bookmakers .fr/.com → impossible en backtest car non historisés (Football-Data CSV n'a que 1X2 + O/U). Seule voie : Voie 2 forward test en live.

## Décision Go/No-Go T002

| Critère | Cible | Réalisé | Verdict |
|---|---|---|---|
| AUC scorer | ≥ 0.65 | **0.729** | ✅ |
| AUC assist | ≥ 0.65 | **0.690** | ✅ |
| Brier < uniform | oui | -4.6% / -1.7% | ✅ |
| Calibration acceptable | gap < 10pp | gap max 8pp | ✅ |
| ROI ≥ +2% net vig | ≥ +2% | non testable proprement | ⚠️ |

## Fixes post-revue méthodologique appliqués

1. **Détection gardien** : passé de `position == "G"` (0/28 détectés !) à `saves > 0 OR position == "G"` (28/28). Évite d'attribuer du xG à un gardien.
2. **Ratio xA target** : passé de 0.65 (arbitraire) à 0.707 (mesuré : 598 assists / 846 buts Bundesliga 25/26).
3. Métriques quasi inchangées (effets de second ordre) mais ROI assist au seuil 30% : +16% → **+29.6%** (n=17).

## ✅ GO conditionnel sur Voie 2

**Recommandation** : Lancer Voie 2 (forward test live) pour valider l'edge réel avec **odds player-props bookmakers .fr scrapés en live**. C'est la seule façon de mesurer le vrai ROI sans tomber dans l'auto-référence.

**À surveiller en parallèle** :
1. Reduire la sur-confiance scorer 30-50% (ajuster shrinkage k de 8 → 12 ou 15 ?)
2. Ajout adversaire defensif (xGA contre = défense forte → atténuer xG joueur)
3. Calibration finale via Platt scaling ou isotonic regression sur le forward log
