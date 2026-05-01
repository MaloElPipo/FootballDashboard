#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then echo "[ERR] GH_PAT non défini"; exit 1; fi
git config user.email "agent@replit.com"
git config user.name "Replit Agent"
[ -f .git/index.lock ] && rm -f .git/index.lock

git add artifacts/football-dashboard/scripts/build_iso_pays_csv.py \
        artifacts/football-dashboard/scripts/git_commit_push_iso_v2.sh \
        artifacts/football-dashboard/live/data/portail/iso_pays.csv

git status --short

if git diff --cached --quiet; then
  echo "Rien à commiter"
else
  git commit -m "feat(iso): regroupe toutes les competitions par pays dans iso_pays.csv

Ajout de 3 colonnes consolidees pour faciliter la lecture pays-par-pays :
- nb_competitions : total (ligues + selection nationale)
- codes_tm_competitions : tous les codes TM regroupes (ex Allemagne 'L1;L2;L3;GER')
- codes_tm_competitions_detail : annotation [L]eague / [N]ational

Total : 119 competitions reparties sur 77 pays."
  REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
  git push "${REMOTE_URL}" HEAD:main
fi
echo "[OK] Done"
git log --oneline -2
