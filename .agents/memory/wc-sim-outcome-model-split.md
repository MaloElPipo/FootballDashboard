---
name: WC simulator outcome-model inconsistency
description: Pourquoi le simulateur CDM compresse les points/qualif — deux modèles de résultat incohérents (Poisson-Elo indépendant vs sigmoïde calibrée).
---

# Incohérence de modèle de résultat dans le simulateur CDM

Le **1X2 affiché** utilise `sigmoid_v8_1x2` (calibrée au marché, validée par audit).
Mais le **résultat qui attribue les points en poule** (`simulate_tournament` →
`simulate_match_goals`) tire deux **Poisson indépendants** sur des λ Elo
(`derive_lambdas_from_elo`). Ces deux chemins ne donnent pas les mêmes probas.

**Symptôme** : presque aucune équipe ne dépasse 6 points attendus en poule
(1 seule sur 48), et les P(qualif) sont redistribuées vers les faibles.

**Pourquoi** : le Poisson indépendant sur-produit structurellement les nuls et
écrase l'écart de victoire (pas de corrélation / pas de correction Dixon-Coles).
À delta=+400 Elo : Poisson-Elo ≈ 57/23/19 vs sigmoïde ≈ 74/17/9. De plus, les
`expected_scores` marché ne servent qu'au goal-average de départage, jamais au
résultat → l'avantage hôte (USA/MEX/CAN) est totalement absent du résultat.

**Why:** un favori qui domine ses 3 matchs *doit* tourner à ~7 pts attendus et
~96-99% de qualif ; la compression venait du modèle de résultat, PAS de l'Elo ni
de la sigmoïde (toutes deux saines).

**How to apply:** pour caler le simulateur sur le marché, tirer l'issue W/N/D
depuis le 1X2 calibré — Option A `sigmoid_v8_1x2`, ou Option B 1X2 marché
de-viggé quand couvert (≈69/72) + fallback A — et **garder** les λ uniquement
pour le goal-average. Prototypes read-only : `scripts/proto_group_points.py`
(points attendus) et `scripts/proto_qualif_optionB.py` (Monte-Carlo P(qualif)).
Détail numérique : Option B fait monter les favoris à 96-99%, USA +15,5%,
AUT +12,3%, et fait chuter les outsiders gonflés (JOR/PAN/QAT ≈ −20%).

**Piège numérique** : agréger les probas Poisson sur grille tronquée (`mx`) laisse
~0,18% de masse ; ne pas l'attribuer implicitement aux victoires extérieures —
renormaliser pw+pd+pl=1 (sinon léger biais away sur le modèle de référence).
