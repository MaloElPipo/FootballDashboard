# Report Phase 6 — Synthese & plan de migration prod

Status : **TEMPLATE LIVRE** (page Streamlit operationnelle, decisions GO/NO-GO
a remplir au fil des backtests). Ce document acte le cadre de bascule, pas les
verdicts : ceux-ci sont consignes dans la grille de l'onglet "2. Grille
decision" du labo et reportes ici manuellement quand chaque phase est cloturee.

## 1. Tableau de synthese — etat des 5 chantiers

| Phase | Feature                          | Report         | Flag prod              | Valeurs                                              |
|-------|----------------------------------|----------------|------------------------|------------------------------------------------------|
| 1     | Triple inversion BTTS            | `01_inversion_btts.md` | `INVERSION_METHOD`     | `double_indep` / `triple_dixon_coles`                |
| 2     | Recalibrage Elo via xG           | `02_elo_xg.md`         | `ELO_SOURCE`           | `pin_calibrated` / `xg_regression` / `blend_50_50`   |
| 3     | xG poules CDM + 3emes correle    | `03_xg_pools_cdm.md`   | `CDM_THIRDS_METHOD`    | `independent_poisson` / `correlated_form`            |
| 4     | Migration player stats BSD       | `04_player_stats.md`   | `PLAYER_STATS_SOURCE`  | `sofascore_scrape` / `bsd_api`                       |
| 5     | Sharp money tracker              | (setup only)           | `SHARP_TRACKER`        | `off` / `observation_only` / `signal_active`         |

Les criteres go/no-go detailles sont rappeles dans la page Streamlit
"Phase 6 — Synthese" (onglet 2) et dans chaque report individuel.

## 2. Decisions actuelles

| Phase | Decision provisoire | Date | Commentaire bref |
|-------|---------------------|------|------------------|
| 1     | PENDING             | -    | en attente backtest 100 matchs PL 24/25 |
| 2     | PENDING             | -    | en attente backtest 100 matchs PL 24/25 + 25/26 |
| 3     | PENDING             | -    | en attente snapshot pinnacle_wc2026 + squads_static |
| 4     | PENDING             | -    | en attente run sur 30 joueurs forward log |
| 5     | SHADOW (setup OK)   | 2026-05-20 | 3 semaines d'observation requises avant signal predictif |

> **Convention** : `SHADOW` = code livre, tourne en parallele, n'influence pas la
> prod. `GO blend X%` = la prod publie `(1-X) * ancien + X * nouveau`. `GO 100%`
> = bascule complete, ancien code en fallback 30 jours puis depreciation.

## 3. Plan de bascule progressive (rappel)

Pour CHAQUE feature qui passe en GO, le pipeline standard est :

1. **Etape 0 — Shadow** (1-2 semaines)
   - Nouveau modele tourne en parallele, outputs logges, aucune mise/publication.
   - Comparaison statistique quotidienne KPIs vs prod.

2. **Etape 1 — Blend 80/20** (2 semaines)
   - `proba_publiee = 0.8 * prod + 0.2 * nouveau`.
   - Forward log marque `SOURCE=blend_20`.
   - Si KPI degrade -> rollback flag immediatement.

3. **Etape 2 — Blend 50/50** (2 semaines)
   - Verification stabilite : drift Elo, ROI, log-loss, Brier.

4. **Etape 3 — Migration 100%**
   - Feature flag pointe sur la nouvelle valeur.
   - Ancien code reste 30 jours en fallback puis depreciation.

## 4. Feature flags a ajouter en prod

Fichier a creer : `artifacts/football-dashboard/feature_flags.py`

```python
import os

INVERSION_METHOD = os.getenv("INVERSION_METHOD", "double_indep")
ELO_SOURCE = os.getenv("ELO_SOURCE", "pin_calibrated")
CDM_THIRDS_METHOD = os.getenv("CDM_THIRDS_METHOD", "independent_poisson")
PLAYER_STATS_SOURCE = os.getenv("PLAYER_STATS_SOURCE", "sofascore_scrape")
SHARP_TRACKER = os.getenv("SHARP_TRACKER", "off")
```

Chaque module prod consomme le flag avant d'invoquer l'algo V1 ou V2 :

```python
from feature_flags import INVERSION_METHOD

if INVERSION_METHOD == "triple_dixon_coles":
    lh, la, rho = invert_triple(probs_1x2, prob_o25, prob_btts)
else:
    lh, la = invert_double(probs_1x2, prob_o25)
```

**Rollback** : changer la valeur d'env var puis restart workflow
`artifacts/football-dashboard: web`. Aucune migration de schema, aucune perte
de donnees.

## 5. Ordre de bascule recommande

Plus le risque de regression est faible et plus le gain immediat est fort,
plus la phase passe tot :

1. **Phase 4 (player stats BSD)** — bascule la plus sure : input data
   uniquement, pas d'algo. Si couverture > 90 % top 5 et > 70 % extension,
   GO 100 % en une seule fois (le scraper Sofascore reste 30 jours en fallback).

2. **Phase 1 (inversion BTTS)** — algo local match-par-match, isolable derriere
   un flag, backtest log-loss objectif. Si GO : shadow 2 semaines puis blend
   50 % puis 100 %.

3. **Phase 2 (Elo xG)** — impact systeme (touche TOUS les modeles 1X2 derives).
   A bouger seulement si Phase 1 est stable en prod depuis 2 semaines. Blend
   30 % par defaut, escalade lente.

4. **Phase 3 (xG poules CDM + 3emes)** — fenetre courte (CDM 2026), bascule
   directe sur le simulateur WC si convergence boucle B prouvee. Pas de blend
   pertinent (sim unique).

5. **Phase 5 (sharp tracker)** — bascule `observation_only` -> `signal_active`
   apres 3 semaines d'historique ET correlation prouvee avec mouvements
   profitables.

## 6. Garde-fous

- **Pas de bascule simultanee de 2 phases** : isolation des effets, sinon
  impossible d'attribuer une regression.
- **Forward log immutable** : `outcome_scored` reste source de verite pour les
  backtests post-bascule.
- **Snapshot prod avant chaque bascule** : `lab/data/snapshots/<tag>/` pour
  permettre un diff avant/apres et un rollback de reference si necessaire.
- **Page "Synthese & migration" mise a jour** : la grille de decision en
  session_state doit etre retranscrite ici manuellement a chaque verdict
  (la session Streamlit n'est pas persistee).

## 7. Fichiers

- `lab/pages/phase6_synthesis.py` — page Streamlit 3 onglets
- `lab/reports/01-04_*.md` — reports detailles par phase
- `lab/reports/05_synthesis.md` — present document (synthese + plan migration)
- `lab/data/snapshots/<tag>/` — snapshots prod de reference pour chaque bascule
