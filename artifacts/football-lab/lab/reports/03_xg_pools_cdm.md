# Report Phase 3 — xG totaux poules CDM + meilleurs 3emes

Status : **DRAFT** (algos + UI livres en demo synthetique. Integration snapshot
`pinnacle_wc2026_odds.json` + squads CDM 26 = phase de bascule.)

## Probleme

Le simulateur CDM actuel calcule les probas de qualif via Monte Carlo 1X2 par
match independants. Trois faiblesses :

1. **Pas d'usage du marche O/U buts par equipe** : on rate des value bets
   sur "Total buts marques par X en phase poule".

2. **Independance inter-matchs** : la Poisson par match suppose qu'une equipe
   ne porte pas un facteur de forme global. En realite, si une equipe est dans
   un creux ou un pic, les 3 matchs sont correles -> la distribution des
   points est plus volatile que l'independante.

3. **Pas de feedback sur Elo nation** : si le marche pricer les buts attendus
   tres differemment de notre Elo, on ne corrige pas.

## Methode

### Brique 1 — xG par equipe (model + market)

Pour chaque equipe d'une poule :
- `xGF_pool_model` = somme(lambdas) des 3 matchs simules
- `xGF_pool_market` = somme(lambdas issus de la triple inversion phase 1) sur
  les cotes des 3 matchs de poule.

Comparaison delta_xgf = market - model, normalise par match.

### Brique 2 — Boucle B (recalibrage Elo)

Si `|delta_xgf / 3| > 0.5` buts par match :
- skip si la nation est forced (manuel CDM, gere par user)
- sinon : `Elo_new = Elo_old + sensitivity * (gap / 0.5)` ou sensitivity=100
- 3 iterations max (regenerer les lambdas modele entre chaque iteration)

### Brique 3 — Poisson correle inter-matchs

Pour chaque equipe, on simule N=3000 tirages des 3 matchs avec un facteur de
forme partage f ~ LogNormal(0, sigma=0.18). Lambdas attaque * f, lambdas
defense / f.

Effets attendus :
- P50 points inchange
- P25/P75 plus etales (queue plus epaisse a droite -> +1 point sur les
  scenarios bons, -1 sur les scenarios mauvais)
- Meilleurs 3emes : la queue droite "8 pts" devient accessible aux equipes
  moyennes, ce qui REDUIT P(qualif R32 via 3eme) pour les "favoris 3eme"

### Brique 4 — Value bets O/U buts marques par equipe

Pour chaque equipe :
- Estimer P(GF_pool > k) via Poisson(gf_mean) sur l'output simule
- Comparer aux cotes Betclic / Unibet sur les marches "Total buts X en
  phase poule"
- Flag value si EV > 4 %

## Critere go/no-go

| Critere                                               | Seuil |
|-------------------------------------------------------|-------|
| Convergence boucle B en <= 3 iterations               | 100 % |
| Distribution meilleurs 3emes : delta P_qualif < 10 pp | OK     |
| Value bets identifiees retrospectivement profitable   | hist. |

L'integration prod attend la connexion squad + pinnacle_wc2026 odds + Elo nation
actuels.

## Limitations connues

- **Sigma de forme 0.18 = hyperparam empirique** : a calibrer sur historique
  CDM 2018+2022 (residuel buts marques vs predit) avant bascule prod.
- **Approximation Poisson sur GF_pool_total** : la somme de 3 Poissons est
  bien Poisson mais le facteur de forme casse l'hypothese -> il faudra utiliser
  l'array sims directement plutot que la moyenne en prod.
- **prob_qualif_r32_as_third heuristique** : ne fait pas le scrutin entre les
  12 troisiemes en concurrence. La vraie version doit simuler les 12 poules
  conjointement (deja le cas dans le simulateur prod, mais avec independence).

## Fichiers

- `lab/cdm/pool_xg.py` — 4 briques (compute_pool_xg, adjust_elo_from_gap,
  simulate_team_pool_correlated, value_bets_team_total_goals)
- `lab/pages/phase3_pool_xg.py` — UI 4 tabs
- A connecter : snapshot `pinnacle_wc2026_odds.json` + `squads_static.json`
