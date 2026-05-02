#!/bin/bash
# Push correctifs codes TM pour 14 ligues à 0 joueurs sur le portail.
set -e
cd "$(dirname "$0")/.."

[ -f .git/index.lock ] && rm -f .git/index.lock

# Configure remote auth via GH_PAT
REMOTE_URL="https://${GH_PAT}@github.com/MaloElPipo/FootballDashboard.git"
git remote set-url github "$REMOTE_URL" 2>/dev/null || git remote add github "$REMOTE_URL"

# Author config
git config user.email "agent@replit.com"
git config user.name "Replit Agent"

# Add + commit
git add live/leagues_master.py
if git diff --cached --quiet; then
  echo "[INFO] Aucune modif staged, on saute le commit"
else
  git commit -m "fix(master): 14 codes TM corrigés (10 codes invalides + SLO1/SK1 inversés + ES3/IT3 splits)

Diagnostic : 14 ligues affichaient 0 joueurs sur le portail GitHub Pages
parce que leurs codes Transfermarkt étaient invalides (HTTP 302 vers la
page navigation TM). Le scraper créait les CSV mais sans aucune ligne.

Corrections via vérification directe sur transfermarkt.com :

Codes simples corrigés (slug inchangé sauf BG1) :
- AL1 → ALB1 (Albanie, kategoria-superiore)
- BH1 → BOS1 (Bosnie-H., premijer-liga, nom corrigé)
- BG1 → BU1  (Bulgarie, slug first-league → parva-liga)
- CY1 → ZYP1 (Chypre, first-division)
- FN1 → FI1  (Finlande, veikkausliiga)
- GE1 → GE1N (Géorgie, erovnuli-liga)
- HU1 → UNG1 (Hongrie, nemzeti-bajnoksag)
- NI1 → NIR1 (Irlande du Nord, premiership)
- LV1 → LET1 (Lettonie, virsliga)
- LT1 → LI1  (Lituanie, a-lyga)
- PT2 → PO2  (Portugal D2, liga-portugal-2)

Inversion Slovaquie/Slovénie corrigée :
- SLO1 (Slovénie) → SL1 (Prva Liga, vrai code TM)
- SK1  (Slovaquie) → SLO1 (Niké Liga, vrai code TM)
  Conséquence : les 2116 lignes actuellement étiquetées 'Slovénie' sur
  le portail étaient en fait la Slovaquie. Au prochain run, tout sera
  correctement étiqueté.

Splits multi-groupes (Transfermarkt sépare en girones distincts) :
- ES3 → E3G1 (Grupo I) + E3G2 (Grupo II)
- IT3 → IT3A (Girone A) + IT3B (Girone B) + IT3C (Girone C)

Au total : 71 ligues → 74 ligues (+3 nouvelles entrées splits).
Sanity assert mis à jour.

Co-Authored-By: ChatGPT <agent@replit.com>"
fi

# Push : tout l'historique local en avance (le commit Enrichissement précédent + ce nouveau)
git push github main 2>&1
git fetch github main 2>&1

echo "[OK] Push terminé. État après :"
git --no-optional-locks log --oneline -3
