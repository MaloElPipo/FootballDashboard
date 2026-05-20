# Report Phase 2 — Recalibrage Elo via xG getStandings

Status : **DRAFT** (algo livre, backtest a lancer depuis l'onglet "Backtest 1X2")

## Probleme

L'Elo prod (`pin_calibrated_elo.json`) est calibre sur les resultats 1X2
historiques. Ca le rend reactif aux sequences de chance (un gardien en feu sur
5 matchs, un poteau qui sauve, etc.) qui ne refletent pas le niveau structurel.

Le **xG (Expected Goals)** est une mesure beaucoup moins bruitee : il agrege la
qualite des occasions creees / concedees. Sur 38 matchs PL, l'ecart-type du xG
total d'une equipe est ~30 % inferieur a celui des buts reels, ce qui donne un
signal de niveau plus stable et plus rapide a converger.

## Methode

1. **Fetch standings BSD** pour 5-7 leagues × 3-5 saisons.
   Endpoint : `v2/standings/?league=<id>&season=<id>`.
   On extrait `xg_for`, `xg_against`, `matches_played` par equipe.

2. **Normalisation league/saison** : pour chaque (league, saison) on calcule
   `mean(xgf_per_match)` et `mean(xga_per_match)` puis on ramene chaque equipe a
   un ratio centre sur 1.0. Ca isole le niveau intra-league.

3. **Decay exponentiel inter-saisons** : poids `0.7^k` ou k est l'ordre de la
   saison (0 = derniere). La saison la plus recente compte le plus.

4. **Conversion en Elo** :
   - Si on a un snapshot prod, on cale `a + b * strength` par regression
     lineaire sur l'intersection des equipes. Le Elo_xg est ainsi DIRECTEMENT
     comparable au Elo_prod.
   - Sinon : `mu=1500, sigma=80` nominaux.

5. **Backtest 1X2** sur saison N matchs :
   - log-loss vs resultat reel
   - Brier score
   - ROI Pinnacle close (mise unitaire si EV > 2 %)
   On compare Elo_xg vs Elo_prod vs un eventuel blend `(1-α) * prod + α * xg`.

## Agregation CDM (information non bloquante)

Pour produire un Elo nation a partir des club_strengths :

```python
nation = aggregate_nation_elo(squad_26, club_strengths, minutes_by_player)
# pondere par minutes club -> att/def/strength nation
```

L'user garde la main sur les overrides manuels CDM (nations forced).

## Critere go/no-go (a remplir apres backtest)

Trois critere cumulatifs pour pousser une bascule shadow -> blend 30 % :

1. **Log-loss Elo_xg ≤ log-loss Elo_prod + 0.005** sur 100+ matchs PL
2. **Brier Elo_xg ≤ Brier Elo_prod + 0.005**
3. **ROI cumule ≥ ROI prod** sur la meme periode (test sur PL 24/25 + PL 25/26)

Si seulement 2/3 sont verifies, blend a 20 % avec re-evaluation a 6 mois.

## Limitations connues

- **Manque adversaire-specifique** : la regression actuelle ne distingue pas
  "xGF face a la defense A" vs "xGF face a la defense B". C'est un raccourci
  qui marche bien en moyenne mais sous-estime les variations contextuelles.
  Une vraie version 2 ferait une regression matrix factorization (att_t × def_o)
  match par match.
- **Saison en cours sous-echantillonnee** : sur des saisons <10 journees, le
  xG par match a un ecart-type encore eleve. Le decay attenue mais ne supprime
  pas le bruit.

## Fichiers

- `lab/calibration/elo_from_xg.py` — fetch, regression, calibration, backtest
- `lab/pages/phase2_elo_xg.py` — UI 4 tabs
- `lab/reports/backtest_elo_xg_L<id>_S<id>.csv` — output backtest persiste
