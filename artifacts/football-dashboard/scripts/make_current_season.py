"""
Filtre les CSV carrière TM pour produire la version "saison en cours".

Pour chaque championnat scrapé dans `live/data/tm_career/`, ce script :
  - lit `{code}_career.csv` et `{code}_matches.csv`
  - garde uniquement les lignes de la saison la plus récente (= saison en cours)
  - écrit le résultat dans `live/data/tm_career_current/`

Le summary et competitions_seen ne sont PAS filtrés — ils sont des références
globales et restent disponibles uniquement dans le ZIP "all".

Usage :
    python scripts/make_current_season.py            # toutes les ligues présentes
    python scripts/make_current_season.py mar1 alg1  # ligues spécifiques
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from career_export_transaction import CURRENT_SUFFIXES, export_transaction, recover_exports
SRC_DIR = REPO_ROOT / "live" / "data" / "tm_career"
OUT_DIR = REPO_ROOT / "live" / "data" / "tm_career_current"

# Regex pour extraire des années 4-chiffres (20xx ou 19xx) ou 2-chiffres isolés.
# Pas de \b en début : couvre aussi les formes collées ("S2025", "Y2026").
# La négation (?<!\d) / (?!\d) garantit qu'on ne découpe pas un plus long entier.
_RE_4DIGIT = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_RE_2DIGIT = re.compile(r"(?<!\d)(\d{2})(?!\d)")


def parse_season(val: str | int | None) -> int | None:
    """Normalise n'importe quel format TM de saison vers un entier représentatif.

    Formats gérés (maintenant et pour les saisons futures) :
      "2025"        → 2025
      "2025/26"     → 2026   (max des deux années)
      "2025/2026"   → 2026
      "25/26"       → 2026   (2-digit → 2000+, puis max)
      "26"          → 2026   (seul entier 2-chiffres)
      2025          → 2025   (déjà un int)

    Retourne None si aucune année ne peut être extraite.
    """
    if val is None:
        return None
    s = str(val).strip()

    # Cas 1 : entier pur (format historique)
    try:
        return int(s)
    except ValueError:
        pass

    # Cas 2 : formes avec séparateur "/" ou "-" (ex. "2025/26", "25/26", "2025-2026")
    sep = "/" if "/" in s else ("-" if "-" in s else None)
    if sep:
        parts = s.split(sep)
        years: list[int] = []
        for p in parts:
            p = p.strip()
            try:
                y = int(p)
                if y < 100:
                    y += 2000          # "26" → 2026
                years.append(y)
            except ValueError:
                pass
        if years:
            return max(years)

    # Cas 3 : années 4-chiffres quelque part dans la chaîne (ex. "S2025", "2025-26")
    found4 = _RE_4DIGIT.findall(s)
    if found4:
        return max(int(y) for y in found4)

    # Cas 4 : uniquement 2-chiffres (ex. "26")
    found2 = _RE_2DIGIT.findall(s)
    if found2:
        return max(int(y) + 2000 for y in found2)

    return None


def detect_current_season(career_path: Path) -> int | None:
    """Retourne la valeur de saison maximale (normalisée) présente dans le CSV."""
    seasons: set[int] = set()
    with career_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            parsed = parse_season(row.get("season"))
            if parsed is not None:
                seasons.add(parsed)
    return max(seasons) if seasons else None


def filter_csv_by_season(src: Path, dst: Path, season: int) -> int:
    """Filtre un CSV sur parse_season(season) == saison; renvoie nb de lignes écrites."""
    written = 0
    with src.open("r", newline="", encoding="utf-8") as fi, \
         dst.open("w", newline="", encoding="utf-8") as fo:
        reader = csv.DictReader(fi)
        writer = csv.DictWriter(fo, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            if parse_season(row.get("season")) == season:
                writer.writerow(row)
                written += 1
    return written


def process_league(code: str) -> dict:
    with export_transaction(SRC_DIR, code.lower()):
        with export_transaction(OUT_DIR, code.lower(), CURRENT_SUFFIXES) as tx:
            return _process_league(code, tx)


def _process_league(code: str, tx) -> dict:
    """Filtre career+matches d'une ligue. Retourne stats."""
    code_l = code.lower()
    career_src = SRC_DIR / f"{code_l}_career.csv"
    matches_src = SRC_DIR / f"{code_l}_matches.csv"

    if not career_src.exists():
        return {"code": code, "ok": False, "error": f"Pas de fichier {career_src.name}"}

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    season = detect_current_season(career_src)
    if season is None:
        return {"code": code, "ok": False, "error": "Aucune saison détectable"}

    n_career = 0
    n_matches = 0

    def prepare(directory):
        nonlocal n_career, n_matches
        n_career = filter_csv_by_season(
            career_src, directory / f"{code_l}_career.csv", season)
        if matches_src.exists():
            n_matches = filter_csv_by_season(
                matches_src, directory / f"{code_l}_matches.csv", season)

    # Missing matches historically leaves its previous output (or absence) intact.
    tx.write(prepare, preserve_unwritten=True)

    return {
        "code": code,
        "ok": True,
        "season": season,
        "n_career": n_career,
        "n_matches": n_matches,
    }


def main(argv: list[str]) -> int:
    recover_exports(OUT_DIR, CURRENT_SUFFIXES)
    recover_exports(SRC_DIR)
    if not SRC_DIR.exists():
        print(f"[ERREUR] Source manquante : {SRC_DIR}", file=sys.stderr)
        return 1

    if argv:
        codes = [a.upper() for a in argv]
    else:
        # Auto-détection : tous les *_career.csv présents
        codes = sorted({p.name.split("_career.csv")[0].upper()
                        for p in SRC_DIR.glob("*_career.csv")})

    if not codes:
        print(f"[INFO] Aucun fichier *_career.csv trouvé dans {SRC_DIR}")
        return 0

    print(f"[INFO] Filtrage saison en cours pour {len(codes)} championnat(s) :")
    print(f"       {', '.join(codes)}")
    print()

    n_ok = 0
    n_ko = 0
    for code in codes:
        res = process_league(code)
        if res["ok"]:
            n_ok += 1
            print(f"  [OK]  {res['code']:6s} saison={res['season']}  "
                  f"career={res['n_career']:>5}  matches={res['n_matches']:>5}")
        else:
            n_ko += 1
            print(f"  [KO]  {res['code']:6s} {res['error']}")

    print()
    print(f"[FIN] {n_ok} OK / {n_ko} KO   →   {OUT_DIR}")
    # On ne bloque le pipeline QUE si AUCUNE ligue n'a pu produire un fichier
    # current_season. Tant qu'au moins une ligue a réussi, le portail peut être
    # publié et les autres apparaîtront en "non disponibles".
    if n_ok == 0:
        print("[ERREUR] Aucune ligue n'a pu être filtrée — pipeline arrêté.",
              file=sys.stderr)
        return 1
    if n_ko > 0:
        print(f"[WARN] {n_ko} ligue(s) sans saison détectable — publication "
              f"poursuivie avec les {n_ok} ligue(s) valides.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
