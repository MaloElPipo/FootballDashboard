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

echo "[1/4] git add (deletions + nouveaux fichiers)"
# -A capture deletions (pg1.csv, cha1.csv, eq1.csv, chn1.csv supprimés du fs local)
# et nouveaux fichiers (pr1a/clpd/ec1n/csl + iso_pays.csv + scripts)
git add -A artifacts/football-dashboard/live/data/tm_scrap/ \
           artifacts/football-dashboard/live/data/portail/ \
           artifacts/football-dashboard/live/leagues_master.py \
           artifacts/football-dashboard/scripts/build_iso_pays_csv.py \
           artifacts/football-dashboard/scripts/git_commit_push_fixes.sh

echo "[2/4] git status"
git status --short

echo ""
echo "[3/4] git commit"
if git diff --cached --quiet; then
  echo "  Rien à commiter"
else
  git commit -m "fix(squads): 4 ligues KO recuperees + referentiel pays ISO

Codes/slugs Transfermarkt corriges pour les 4 ligues qui retournaient 0 ligne :
- Paraguay : PG1/primera-division -> PR1A/primera-division-apertura (1983 lignes)
- Chili    : CHA1/primera-division -> CLPD/primera-division-de-chile (2733 lignes)
- Equateur : EQ1/liga-pro-serie-a -> EC1N/ligapro-serie-a (2634 lignes)
- Chine    : CHN1/chinese-super-league -> CSL/chinese-super-league (2698 lignes)

Couverture squads : 67/71 -> 71/71 (100%, +10048 lignes)

Nouveau referentiel ISO :
- live/data/portail/iso_pays.csv : mapping pays FR -> ISO 3166 alpha-3/alpha-2 + code FIFA
- 77 pays uniques (30 both, 29 league_only, 18 national_only)
- 4 sous-codes UK pour GBR (ENG/SCO/WAL/NIR)
- 19 cas FIFA != ISO3 traites (Allemagne DEU/GER, Pays-Bas NLD/NED, etc.)
- Genere par scripts/build_iso_pays_csv.py"
fi

echo ""
echo "[4/4] git push"
REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
git push "${REMOTE_URL}" HEAD:main

echo "[OK] Commit + push terminés"
git log --oneline -3
