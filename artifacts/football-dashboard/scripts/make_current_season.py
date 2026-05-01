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
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "live" / "data" / "tm_career"
OUT_DIR = REPO_ROOT / "live" / "data" / "tm_career_current"


def detect_current_season(career_path: Path) -> int | None:
    """Retourne la valeur entière maximale de la colonne 'season' présente."""
    seasons: set[int] = set()
    with career_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                seasons.add(int(row["season"]))
            except (KeyError, ValueError):
                continue
    return max(seasons) if seasons else None


def filter_csv_by_season(src: Path, dst: Path, season: int) -> int:
    """Filtre un CSV sur season == saison; renvoie nb de lignes écrites."""
    written = 0
    with src.open("r", newline="", encoding="utf-8") as fi, \
         dst.open("w", newline="", encoding="utf-8") as fo:
        reader = csv.DictReader(fi)
        writer = csv.DictWriter(fo, fieldnames=reader.fieldnames or [])
        writer.writeheader()
        for row in reader:
            try:
                if int(row["season"]) == season:
                    writer.writerow(row)
                    written += 1
            except (KeyError, ValueError):
                continue
    return written


def process_league(code: str) -> dict:
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

    career_dst = OUT_DIR / f"{code_l}_career.csv"
    n_career = filter_csv_by_season(career_src, career_dst, season)

    n_matches = 0
    if matches_src.exists():
        matches_dst = OUT_DIR / f"{code_l}_matches.csv"
        n_matches = filter_csv_by_season(matches_src, matches_dst, season)

    return {
        "code": code,
        "ok": True,
        "season": season,
        "n_career": n_career,
        "n_matches": n_matches,
    }


def main(argv: list[str]) -> int:
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
    return 0 if n_ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
