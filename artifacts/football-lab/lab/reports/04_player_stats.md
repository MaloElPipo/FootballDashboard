# Report Phase 4 — Migration player stats BSD

Status : **DRAFT** (algo + UI livres, mesures a faire depuis la page Streamlit)

## Probleme

La collecte actuelle des stats joueurs (goals, assists, xG, xA, minutes) repose
sur un scraper Sofascore (`live/data/sofascore_stats_cache.json`). Trois fragilites :

- **HTML qui bouge** : le scraper casse a chaque refonte UI Sofascore
- **Pas de couverture stable hors top 5** : MLS / Eredivisie / Primeira sont
  intermittents
- **xG empirique non stable** : Sofascore expose un xG par match mais ne le
  recalcule pas retroactivement -> historique incoherent

BSD getPlayerStats expose les memes champs avec un modele xG mature et une
API stable.

## Methode

1. **Wrapper BSD** : `fetch_player_season_stats(player_id, season_id)` agrege
   les rows par-match BSD en somme saison.

2. **Comparaison forward log** : on prend les 30 joueurs les plus suivis dans
   `forward_log.jsonl` prod, on fetch BSD, on compare aux dernieres stats
   Sofascore cachees. Tolerances :

   | champ     | tolerance |
   |-----------|-----------|
   | goals     | 1         |
   | assists   | 1         |
   | xg        | 0.5       |
   | xa        | 0.3       |
   | minutes   | 90        |

3. **Couverture extension** : 20 IDs hors top 5 (sample MLS + Eredivisie +
   Primeira), on mesure le % avec data.

## Critere go/no-go

| Critere                                   | Seuil GO |
|-------------------------------------------|----------|
| Couverture BSD sur forward log top 5      | >= 90 %  |
| Couverture BSD sur extension hors top 5   | >= 70 %  |
| Taux DISAGREE sur goals (> 1)             | <= 10 %  |
| Taux DISAGREE sur xG (> 0.5)              | <= 25 %  |

Si tout GO : bascule directe en prod (le scraper Sofascore reste en fallback
pendant 30 jours puis depreciation).
Si GO partiel (extension < 70 %) : prod top 5 uniquement, extension en
shadow + Sofascore pour les manquants.

## Risques

- **Player IDs BSD ≠ Sofascore** : besoin d'un mapping. Le forward log prod
  contient deja les BSD player_ids dans la plupart des cas (verifier),
  sinon il faut un round-trip search par nom.
- **Latence des stats BSD post-match** : a verifier (idealement < 6 h apres FT).

## Fichiers

- `lab/calibration/player_stats.py` — wrapper + comparaison + couverture
- `lab/pages/phase4_player_stats.py` — UI 3 tabs
- Tableau resultats : a coller ici apres le run forward log
