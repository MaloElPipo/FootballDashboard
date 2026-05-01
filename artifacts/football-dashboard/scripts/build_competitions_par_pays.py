"""
Régénère competitions_vues_par_pays.csv depuis competitions_vues.csv ENRICHI.

Contrairement à build_all_competitions_seen.py qui ne prend que les compétitions
connues du master, ce script regroupe TOUTES les compétitions enrichies (master
+ scraping TM), pour donner un panorama exhaustif des pays couverts.

Sortie:
    live/data/portail/competitions_vues_par_pays.csv
    Colonnes: pays_fr, nb_competitions, nb_connues_master, nb_enrichies_tm,
              competitions_code_nom, n_joueurs_total_pays
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTAIL_DIR = ROOT / "live" / "data" / "portail"
INP = PORTAIL_DIR / "competitions_vues.csv"
OUT = PORTAIL_DIR / "competitions_vues_par_pays.csv"


def main() -> int:
    if not INP.exists():
        print(f"[ERR] {INP} introuvable", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(INP.open(encoding="utf-8")))
    print(f"[INFO] {len(rows)} compétitions lues depuis {INP.name}")

    by_pays: dict[str, list[dict]] = defaultdict(list)
    no_country = 0
    for r in rows:
        pays = (r.get("pays") or "").strip()
        if not pays:
            no_country += 1
            continue
        by_pays[pays].append(r)

    print(f"[INFO] {len(by_pays)} pays distincts ({no_country} comp. sans pays)")

    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pays_fr",
            "nb_competitions",
            "nb_connues_master",
            "nb_enrichies_tm",
            "competitions_code_nom",
            "n_joueurs_total_pays",
        ])
        for pays in sorted(by_pays):
            comps = by_pays[pays]
            comps_sorted = sorted(
                comps, key=lambda r: -int(r.get("n_joueurs_total") or 0)
            )
            nb_master = sum(1 for r in comps if r.get("connue_dans_master") == "oui")
            nb_tm = len(comps) - nb_master
            code_noms = ";".join(
                f"{r['code_tm']}={r['nom_competition']}" for r in comps_sorted
            )
            total = sum(int(r.get("n_joueurs_total") or 0) for r in comps)
            w.writerow([pays, len(comps), nb_master, nb_tm, code_noms, total])

    print(f"[OK] {OUT}")
    print(f"     {len(by_pays)} pays couverts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
