#!/usr/bin/env bash
set -euo pipefail

cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then
  echo "[ERR] GH_PAT non défini"
  exit 1
fi

git config user.email "agent@replit.com"
git config user.name "Replit Agent"

if [ -f .git/index.lock ]; then
  echo "[CLEANUP] Suppression .git/index.lock résiduel"
  rm -f .git/index.lock
fi

echo "[1/4] git add"
git add artifacts/football-dashboard/live/data/tm_scrap/*.csv \
        artifacts/football-dashboard/scripts/scrape_all_squads.py \
        artifacts/football-dashboard/scripts/git_commit_push_squads.sh \
        .gitignore

echo "[2/4] git status"
git status --short | head -20
echo "..."
echo "Total staged: $(git diff --cached --numstat | wc -l) fichiers"

echo "[3/4] git commit"
if git diff --cached --quiet; then
  echo "  Rien à commiter"
else
  git commit -m "feat(squads): scraping complet 71 ligues TM (Phase 3 couverture totale)

- 67 ligues OK / 0 KO en 29.4 min via scripts/scrape_all_squads.py
- 4 ligues retournent 0 lignes (PG1/CHA1/EQ1/CHN1 - slugs TM à corriger ulterieurement)
- Output dans live/data/tm_scrap/ (17 MB total)
- Permet au workflow GH Actions de scraper les carrieres pour toutes les ligues couvertes"
fi

echo "[4/4] git push (via x-access-token)"
REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
git push "${REMOTE_URL}" HEAD:main

echo "[OK] Commit + push terminés"
git log --oneline -3
