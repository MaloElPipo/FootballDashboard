---
name: V8 Elo snapshot silent 1500 fallback
description: Pourquoi charger l'Elo V8 depuis un snapshot gele peut casser silencieusement une nation (fallback 1500).
---

# Piège : snapshot Elo V8 incomplet → fallback 1500 silencieux

`wc_simulator.simulate_tournament` fait `elo_map.get(code, 1500)` : toute nation
absente du dict Elo tombe a **1500 sans erreur**. Une nation top (ex ESP 2157)
devient alors mediocre → P(champion) ~0%, P(qualif poule) ~50%.

**Cause vue en pratique** : le forecast comparait/blendait contre un *snapshot
labo gele* (`artifacts/football-lab/lab/data/snapshots/initial_baseline_*`) qui
avait 45 nations, alors que la prod (`artifacts/football-dashboard/
pin_calibrated_elo.json`) en a 46 — ESP ajoutee apres le gel du snapshot.

**Regle** : un comparatif/blend "vs V8 prod" doit lire l'Elo **prod LIVE**, pas
un snapshot. Les snapshots labo servent au backtest reproductible, pas au
forecast courant.

**Comment detecter** : si une nation a un P(champion) absurde vs son rating,
verifier d'abord `elo_dict.get(code)` — un `None` = fallback 1500 = bug de
source, pas une opinion du modele. Comparer `set(prod) - set(snapshot)`.
