---
name: PELE reverse-engineering caveat
description: Comment reconstruire un moteur de simulation depuis les outputs publics PELE (Silver Bulletin) sans exploser les probas des favoris.
---

# Reconstruire PELE depuis les outputs publics

PELE expose publiquement (CSV Datawrapper) :
- PELE rating (Elo-like)
- Tilt rating (offense/defense propensity)
- Round-Robin GF/GA/W/D/L par équipe en site neutre vs les 210 autres

**La formule de conversion (rating, tilt) → λ n'est PAS publiée** (paywall).

## La règle

Dériver les λ par `baseline × att_team × def_opp × (1 + α·tilt)` où att/def sont
des ratios bruts du Round-Robin **produit des prédictions VIOLEMMENT trop
tranchées** sur les gros mismatches. Mesuré : MAE 7.86 pts vs Pinnacle (V8 prod
était à 2.93). FRA-SEN, BRA-MAR, USA-PAR : écart > 35 pts de % chacun.

**Why:** le ratio att/def round-robin double-compte la force d'équipe déjà
contenue dans le PELE rating. En multipliant les deux, on amplifie les écarts
d'un facteur ~2-3x.

**Note complémentaire :** voir aussi `pele-methodology.md`. La vraie PELE elle-
même est aussi plus tranchée que Pinnacle sur les groupes CDM (biais favori
+4.3 pts vs marché, MAE 6.23 sur 19 matchs Pinnacle). Une partie de l'écart
de notre reconstruction venait du double-comptage ci-dessus, mais une autre
partie venait de l'absence des WC tweaks (mult 0.9× sur Δ rating en group
stage) et de l'absence de la Phase 2 (mean-reversion Transfermarkt) — donc
même une reconstruction parfaite côté formule donnerait des résultats plus
tranchés que Pinnacle, et c'est conforme à ce que fait Silver.

**How to apply:**
1. Pour le 1X2 : passer **uniquement** par le PELE rating delta + une sigmoid
   standard (type sigmoid V6 nu, sans booster favori), comme on le ferait pour
   un Elo classique.
2. Pour les λ (buts) : dériver depuis le PELE rating delta (`exp(δ/600)`-style)
   PUIS multiplier par `(1 + α·(tilt_h + tilt_a))` pour moduler le total.
   α ≈ 0.3-0.4. **Ne pas** utiliser les att/def Round-Robin comme multiplicateur.
3. Le Round-Robin sert à **valider** la calibration (les GF/GA simulés doivent
   matcher les GF/GA publiés à <10% près), pas à dériver les λ.

## Données techniques

- Datawrapper URLs : `https://datawrapper.dwcdn.net/<id>/1/data.csv`
  - IDs publiés dans l'article méthodologie : changent à chaque update PELE.
  - Headers `User-Agent` navigateur **obligatoire** (default Python urllib → 403).
- Codes équipes : FIFA standard, identiques aux nôtres pour les 48 CDM 2026.
