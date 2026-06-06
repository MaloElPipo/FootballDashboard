# SESSION LOG — Football Dashboard / V-Pin FR

> Mémoire chronologique tenue par l'agent. **La roadmap est pilotée séparément par l'utilisateur** — ce log sert de matière pour mettre à jour la roadmap manuellement.
>
> Format constant : 6 sections par session, dernière session en haut.

---

## Session 2026-05-03 (après-midi)

### Modules touchés
- **mod_4** (Buteurs / Passeurs + Scraping + Values) — données de référence
- **Process / outillage** — roadmap + log de session

### Ce qu'on a fait
- **Scraping Transfermarkt 74 ligues** : valeur marchande totale + moyenne par équipe + nombre d'équipes/joueurs + buts par match sur 5 saisons (2021/22 → 2025/26).
  - Sortie : `artifacts/football-dashboard/live/data/leagues_overview.csv` (74/74 valeur marchande, 69-73/74 buts/match selon saison — les manquants sont les coupes sans format championnat, comportement attendu).
  - Script réutilisable : `artifacts/football-dashboard/scripts/scrape_leagues_overview.py` (mode merge, args `--seasons` / `--slice` / `--skip-overview`).
- **Mise en place du SESSION_LOG.md** (ce fichier) à la racine du repo.
- **Page Roadmap intégrée au dashboard** (lecture seule du JSON `live/data/roadmap.json`) :
  - Bouton dédié dans la sidebar, isolé sous séparateur "🛠️ Suivi projet".
  - Vue kanban par module avec barre de progression checkpoints, filtres priorité/statut, badges de couleur.
  - Aucune écriture Python sur le JSON — l'utilisateur garde 100 % la main.
- **Workflow dashboard relancé** (était en pause après inactivité).

### Ce qu'on a décidé
- **Roadmap = pilotée par l'utilisateur seul.** L'agent ne modifie jamais `roadmap.json`.
- **SESSION_LOG.md = espace de l'agent.** Format constant pour faciliter la lecture.
- **Modèle Buteurs Maison 4.1 = INTOUCHABLE.** Toute évolution sera additive, jamais en remplacement.
- **Temps de jeu joueur** : par défaut 90 minutes ; la distinction titulaire/remplaçant est gérée en aval par l'optimisation des line-ups.
- **Probabilité que l'équipe marque** : déjà calculée ailleurs dans la stack, on s'appuie dessus, on ne la recalcule pas.
- **Roadmap dans le dashboard mais à l'écart** des sections data/analyse (bouton sidebar dédié, page séparée).
- **CSV `leagues_overview.csv`** en euros bruts (entiers), `code_tm` en première colonne pour faciliter les jointures futures.

### Sujets ouverts / à reprendre
- **Portail GH Pages + exploitation TM** : sujet à reprendre dans la session courante (court terme), exploitation rapide à venir.
- **Run GitHub Actions #7** (`scrape-weekly.yml`) : en cours, durée estimée 5-6 h. Persistera tm_scrap + tm_career + tm_career_current sur main + portail gh-pages 74 ligues.
- **Évolutions modèle Buteurs** envisagées (à valider avant codage) : proba ≥1 but Poisson sur la base des `goals_90_final`. En attente de la décision finale de l'utilisateur.
- **Module mod_1 "Structurer l'app"** : actuellement P3 dans la roadmap, suggéré P1/P2 par l'agent au regard de la dette accumulée. Décision à prendre par l'utilisateur.

### État technique (check médical app)
| Composant | Statut | Note |
|---|---|---|
| Workflow `football-dashboard: web` | ✅ running | Restart effectué cette session |
| Workflow `api-server` | ⏸️ stoppé | Non bloquant pour le dashboard Streamlit |
| Workflow `mockup-sandbox` | ⏸️ stoppé | Non bloquant |
| Page Roadmap dans le dashboard | ✅ opérationnelle | Bouton sidebar "🗺️ Ouvrir la Roadmap" |
| Données `leagues_overview.csv` | ✅ à jour | 74 ligues, 5 saisons buts/match |
| Données `tm_career_current/` | ⚠️ partiel | 1 ligue locale (mar1), le reste en cours via run #7 |
| Run GitHub Actions #7 (scrape weekly) | ⏳ en cours | URL : actions/runs/25253250233 |
| Warnings console (sidebar theme colors) | ⚠️ cosmétique | Sans impact fonctionnel, à nettoyer plus tard si on veut une console propre |

### Fichiers créés / modifiés cette session
- `artifacts/football-dashboard/live/data/leagues_overview.csv` *(créé)*
- `artifacts/football-dashboard/live/data/roadmap.json` *(copié depuis attached_assets, sera réécrit par l'utilisateur)*
- `artifacts/football-dashboard/live/roadmap_page.py` *(créé)*
- `artifacts/football-dashboard/scripts/scrape_leagues_overview.py` *(créé)*
- `artifacts/football-dashboard/app.py` *(édité : import + bouton sidebar + bypass page)*
- `SESSION_LOG.md` *(créé)*

---
