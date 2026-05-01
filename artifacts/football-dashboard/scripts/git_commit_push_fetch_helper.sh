#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then echo "[ERR] GH_PAT non défini"; exit 1; fi
git config user.email "agent@replit.com"
git config user.name "Replit Agent"
[ -f .git/index.lock ] && rm -f .git/index.lock

git add \
  artifacts/football-dashboard/scripts/git_fetch_sync.sh \
  artifacts/football-dashboard/scripts/git_commit_push_fetch_helper.sh

git status --short

if git diff --cached --quiet; then
  echo "Rien à commiter"
else
  git commit -m "chore(scripts): helper git_fetch_sync pour resync ref github/main locale"
  REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
  git push "${REMOTE_URL}" HEAD:main
  # MAJ tracking ref local pour que status soit synchro
  git fetch github main
fi

echo "=== Etat final ==="
git --no-optional-locks status --short --branch | head -3
git --no-optional-locks rev-list --left-right --count HEAD...github/main
echo "[OK] Done"
