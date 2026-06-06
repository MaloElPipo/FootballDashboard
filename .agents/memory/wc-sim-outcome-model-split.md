---
name: WC simulator outcome-model inconsistency + rollback
description: Le résultat de poule du simulateur CDM doit être tiré du 1X2 calibré (marché/sigmoïde), pas de 2 Poisson Elo indépendants ; flag de rollback en prod.
---

# Modèle de résultat du simulateur CDM

**Décision/règle** : l'issue W/N/D qui attribue les points en poule doit être
tirée du **1X2 calibré** — marché Pinnacle de-vigé quand le match est couvert,
fallback `sigmoid_v8_1x2` sinon. Les λ Elo restent réservés au goal-average FIFA.

**Why** : tirer le résultat depuis deux Poisson Elo **indépendants**
(`simulate_match_goals`) sur-produit structurellement les nuls et écrase les
favoris (pas de corrélation / pas de Dixon-Coles) → quasi aucune équipe ne
dépassait 6 pts attendus en poule et les qualifs étaient redistribuées vers les
faibles. L'avantage hôte (USA/MEX/CAN), présent dans les cotes, était aussi
absent du résultat. L'Elo et la sigmoïde, eux, étaient sains — le bug venait du
chemin de résultat, pas des inputs.

**How to apply** : en prod, c'est piloté par la constante module
`GROUP_OUTCOME_MODEL` (`"market"` défaut | `"legacy"`) en tête de
`wc_simulator.py`. Le 1X2 marché arrive via `params["market_1x2"]`
(`{(h,a):(pw,pd,pl)}`), construit côté `app.py`. Le chemin legacy (2 Poisson)
reste intact dans le code.

## Rollback (revenir à l'ancien comportement)
- Doux : remettre `GROUP_OUTCOME_MODEL = "legacy"` puis redémarrer le workflow
  football-dashboard. Aucune perte de code.
- Dur : rollback Replit au checkpoint d'avant la mise en prod.

## Pièges
- **Orientation marché** : clés `market_1x2` parfois orientées (away,home) côté
  Pinnacle ≠ orientation `GROUP_MATCHES` → tester les deux sens, inverser pw/pl.
- **Masse résiduelle** : toujours renormaliser pw+pd+pl=1 avant de tirer l'issue,
  sinon la masse manquante (Poisson tronqué, cote malformée) est absorbée par la
  victoire extérieure → biais away.
- Prototypes d'analyse read-only : `scripts/proto_group_points.py`,
  `scripts/proto_qualif_optionB.py`.
