#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then echo "[ERR] GH_PAT non défini"; exit 1; fi
git config user.email "agent@replit.com"
git config user.name "Replit Agent"
[ -f .git/index.lock ] && rm -f .git/index.lock

git add \
  artifacts/football-dashboard/scripts/enrich_competitions_from_tm.py \
  artifacts/football-dashboard/scripts/git_commit_push_enrich_fr_v2.sh \
  artifacts/football-dashboard/live/data/portail/competitions_vues.csv \
  artifacts/football-dashboard/live/data/portail/competitions_vues_par_pays.csv

git status --short

if git diff --cached --quiet; then
  echo "Rien à commiter"
else
  git commit -m "fix(portail): ajoute mapping FR pour Bahrain, Timor-Leste, Yemen

Suite a la code review : ces 3 pays apparaissaient dans le cache TM via
des selections jeunes (Bahrain U17, Timor-Leste U23, Yemen U19) mais leur
base n'etait pas dans EN_TO_FR -> sortaient en anglais dans le CSV final.

Apres patch:
  - Bahrain U17    -> Bahrein U17
  - Timor-Leste U23 -> Timor oriental U23
  - Yemen U19      -> Yemen U19

Verification : 0 code avec base pays non traduite restant dans le cache."
  REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
  git push "${REMOTE_URL}" HEAD:main
fi
echo "[OK] Done"
git log --oneline -3
