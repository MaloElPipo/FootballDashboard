#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then echo "[ERR] GH_PAT non défini"; exit 1; fi
git config user.email "agent@replit.com"
git config user.name "Replit Agent"
[ -f .git/index.lock ] && rm -f .git/index.lock

git add artifacts/football-dashboard/scripts/build_iso_pays_csv.py \
        artifacts/football-dashboard/scripts/git_commit_push_iso_v3.sh \
        artifacts/football-dashboard/live/data/portail/iso_pays.csv

git status --short

if git diff --cached --quiet; then
  echo "Rien à commiter"
else
  git commit -m "feat(iso): ajoute noms complets des competitions par pays

Nouvelles colonnes dans iso_pays.csv :
- competitions_noms : noms officiels (ex 'Ligue 1;Ligue 2;Championnat National;Selection France')
- competitions_code_nom : couples code=nom (ex 'FR1=Ligue 1;GB1=Premier League;ES1=LaLiga')

Conserve toutes les colonnes precedentes pour compat."
  REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
  git push "${REMOTE_URL}" HEAD:main
fi
echo "[OK] Done"
git log --oneline -2
