#!/usr/bin/env bash
set -euo pipefail
cd /home/runner/workspace

if [ -z "${GH_PAT:-}" ]; then echo "[ERR] GH_PAT non défini"; exit 1; fi
git config user.email "agent@replit.com"
git config user.name "Replit Agent"
[ -f .git/index.lock ] && rm -f .git/index.lock

git add \
  artifacts/football-dashboard/scripts/enrich_competitions_from_tm.py \
  artifacts/football-dashboard/scripts/build_competitions_par_pays.py \
  artifacts/football-dashboard/scripts/git_commit_push_enrich_fr_mapping.sh \
  artifacts/football-dashboard/live/data/portail/competitions_vues.csv \
  artifacts/football-dashboard/live/data/portail/competitions_vues_par_pays.csv \
  artifacts/football-dashboard/live/data/portail/_competitions_tm_cache.json

git status --short

if git diff --cached --quiet; then
  echo "Rien à commiter"
else
  git commit -m "feat(portail): enrichissement complet noms+pays FR pour 1616/1618 compétitions

- enrich_competitions_from_tm.py : +37 pays mappés EN->FR (Andorre,
  Bangladesh, Cambodge, Hong Kong, Inde, Saint-Marin, Soudan du Sud,
  Trinité-et-Tobago, etc.)
- nouvelle fonction pays_en_to_fr_smart() qui gere les suffixes:
    * 'Brazil U17' -> 'Bresil U17'
    * 'New Caledonia U16/U17' -> 'Nouvelle-Caledonie U16/U17'
    * 'Hungary Olympic Team' -> 'Hongrie - Equipe Olympique'
- build_competitions_par_pays.py : nouveau script qui regenere le CSV
  par pays a partir du vues.csv enrichi (et plus seulement du master).
  Resultat : 176 pays couverts (avant: 49 du master uniquement).
- Cache TM : 1558 codes (3 nouveaux fetched: OBLI, OLA, SHMR)
- Couverture noms : 1616/1618 (100%, 2 codes KO restants : CHIU, JUSO
  pages TM 404, negligeable)"
  REMOTE_URL="https://x-access-token:${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
  git push "${REMOTE_URL}" HEAD:main
fi
echo "[OK] Done"
git log --oneline -2
