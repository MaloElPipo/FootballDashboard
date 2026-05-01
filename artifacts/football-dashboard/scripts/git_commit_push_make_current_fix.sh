#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then echo "[ERR] GH_PAT non défini"; exit 1; fi
git config user.email "agent@replit.com"
git config user.name "Replit Agent"
[ -f .git/index.lock ] && rm -f .git/index.lock

git add artifacts/football-dashboard/scripts/make_current_season.py \
        artifacts/football-dashboard/scripts/git_commit_push_make_current_fix.sh

git status --short

if git diff --cached --quiet; then
  echo "Rien à commiter"
else
  git commit -m "fix(workflow): make_current_season ne bloque plus le pipeline si KO partiel

Avant: exit 1 dès qu'au moins une ligue n'avait pas de saison detectable,
ce qui sautait build_pages + deploy gh-pages (pipeline cassé alors que
53/71 ligues etaient pretes a publier).

Apres: exit 0 tant qu'au moins une ligue est OK. Warning logue pour les KO."
  REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
  git push "${REMOTE_URL}" HEAD:main
fi
echo "[OK] Done"
git log --oneline -2
