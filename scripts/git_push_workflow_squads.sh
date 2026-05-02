#!/bin/bash
# Push la modif du workflow GH Actions (ajout étape scraping squads + persistance).
set -e
cd /home/runner/workspace

[ -f .git/index.lock ] && rm -f .git/index.lock

REMOTE_URL="https://${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
git remote set-url github "$REMOTE_URL" 2>/dev/null || git remote add github "$REMOTE_URL"

git config user.email "agent@replit.com"
git config user.name "Replit Agent"

git add .github/workflows/scrape-weekly.yml
if git diff --cached --quiet; then
  echo "[INFO] Aucune modif staged."
else
  git commit -m "ci(workflow): scrape les effectifs manquants avant la carrière

Le workflow scrape-weekly.yml ne lançait que tm_player_career.py qui
exigeait que live/data/tm_scrap/{code}.csv soit pré-existant. Pour les
18 nouveaux codes TM (corrigés au commit précédent 43cb6a2), aucun
fichier squads n'existe — donc le scraping carrière les sautait
silencieusement.

Ajouts :
- Étape 'Scraping effectifs (squads) pour ligues sans CSV' qui appelle
  scripts/scrape_all_squads.py --only <code> pour chaque code manquant
- Étape 'Persister les nouveaux effectifs sur main' qui commit + push
  les nouveaux CSV vers main pour éviter de re-scraper à chaque run
  hebdomadaire
- Compteur de ligues mis à jour : 71 → 74

Le critère de présence est maintenant 'fichier existe ET > 1 ligne'
(au lieu de seulement 'fichier existe') pour détecter les CSV
header-only laissés par les anciens codes invalides."
fi

git push github main
echo "[OK] Push terminé."
git log --oneline -3