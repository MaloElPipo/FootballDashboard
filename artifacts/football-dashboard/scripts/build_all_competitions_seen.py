"""
Agrège l'union de TOUTES les compétitions vues dans la carrière des joueurs
scrapés sur l'ensemble des ligues du portail.

Source : ZIPs `{code}_all.zip` publiés sur GitHub Pages (branche gh-pages).
Pour chaque ZIP, on lit `{code}_competitions_seen.csv` qui contient :
    competition_id, n_players_with_match

On produit deux CSV :
    1. live/data/portail/competitions_vues.csv
       (1 ligne par compétition unique, avec stats agrégées)
    2. live/data/portail/competitions_vues_par_pays.csv
       (1 ligne par pays, regroupant les compétitions connues)

Usage :
    python3 scripts/build_all_competitions_seen.py [--source DIR] [--portal-url URL]

Par défaut, télécharge depuis https://maloElpipo.github.io/FootballDashboard/data/
Avec --source DIR, lit les ZIPs depuis un dossier local.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
import urllib.error
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live.leagues_master import LEAGUES, NATIONAL_TEAMS  # noqa: E402

OUT_DIR = ROOT / "live" / "data" / "portail"
DEFAULT_PORTAL = "https://maloElpipo.github.io/FootballDashboard/data"


def build_known_competitions() -> dict[str, dict]:
    """Mapping code_tm -> {nom, pays, type}. Sources : LEAGUES + NATIONAL_TEAMS."""
    known: dict[str, dict] = {}
    for L in LEAGUES:
        known[L["code_tm"]] = {
            "nom": L["nom"],
            "pays": L["pays"],
            "type": "league",
            "tier": L.get("tier"),
        }
    for t in NATIONAL_TEAMS:
        known[t["code_tm"]] = {
            "nom": f"Sélection {t['nom']}",
            "pays": t["nom"],
            "type": "national_team",
            "tier": None,
        }
    return known


def download_zip(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def iter_zip_sources(args: argparse.Namespace) -> list[tuple[str, bytes]]:
    """Renvoie [(code, zip_bytes)] pour toutes les ligues+sélections trouvées."""
    codes_to_try = [L["code_tm"].lower() for L in LEAGUES] + \
                   [t["code_tm"].lower() for t in NATIONAL_TEAMS]
    found: list[tuple[str, bytes]] = []

    if args.source:
        src_dir = Path(args.source)
        for code in codes_to_try:
            fp = src_dir / f"{code}_all.zip"
            if fp.exists():
                found.append((code, fp.read_bytes()))
    else:
        # Téléchargement depuis le portail
        print(f"[INFO] Téléchargement depuis {args.portal_url}/")
        for code in codes_to_try:
            url = f"{args.portal_url}/{code}_all.zip"
            data = download_zip(url)
            if data is not None:
                found.append((code, data))
                print(f"  [OK] {code}_all.zip ({len(data):>8} bytes)")
            else:
                print(f"  [--] {code}_all.zip absent (404)")
    return found


def parse_seen_from_zip(code: str, zip_bytes: bytes) -> list[tuple[str, int]]:
    """Renvoie [(competition_id, n_players)] depuis {code}_competitions_seen.csv."""
    name = f"{code}_competitions_seen.csv"
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        if name not in zf.namelist():
            return []
        with zf.open(name) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            return [(r["competition_id"], int(r["n_players_with_match"]))
                    for r in reader]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", help="Dossier local contenant les ZIPs (sinon télécharge)")
    ap.add_argument("--portal-url", default=DEFAULT_PORTAL,
                    help=f"URL du portail (défaut: {DEFAULT_PORTAL})")
    args = ap.parse_args()

    known = build_known_competitions()
    sources = iter_zip_sources(args)

    if not sources:
        print("[ERR] Aucun ZIP trouvé.")
        return 1

    print(f"\n[INFO] {len(sources)} ZIPs traités.")

    # Agrégation : pour chaque competition_id rencontré, on suit
    #   - n_ligues_concernees : nombre de ligues sources où cette comp apparait
    #   - n_joueurs_total     : somme des n_players_with_match
    #   - sources             : liste des codes sources
    agg: dict[str, dict] = defaultdict(
        lambda: {"n_ligues_sources": 0, "n_joueurs_total": 0, "sources": []}
    )

    for src_code, zip_bytes in sources:
        rows = parse_seen_from_zip(src_code, zip_bytes)
        for comp_id, n_players in rows:
            agg[comp_id]["n_ligues_sources"] += 1
            agg[comp_id]["n_joueurs_total"] += n_players
            agg[comp_id]["sources"].append(src_code.upper())

    print(f"[INFO] {len(agg)} compétitions distinctes vues au total.")

    # Tri : par nb de joueurs total décroissant
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # === CSV 1 : competitions_vues.csv ===
    out1 = OUT_DIR / "competitions_vues.csv"
    n_known = 0
    with out1.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "code_tm",
            "nom_competition",
            "pays",
            "type",
            "tier",
            "connue_dans_master",
            "n_ligues_sources",
            "n_joueurs_total",
            "sources",
        ])
        ordered = sorted(agg.items(),
                         key=lambda kv: (-kv[1]["n_joueurs_total"], kv[0]))
        for comp_id, data in ordered:
            info = known.get(comp_id)
            if info:
                n_known += 1
                w.writerow([
                    comp_id,
                    info["nom"],
                    info["pays"],
                    info["type"],
                    info["tier"] or "",
                    "oui",
                    data["n_ligues_sources"],
                    data["n_joueurs_total"],
                    ";".join(data["sources"]),
                ])
            else:
                w.writerow([
                    comp_id,
                    "",  # à enrichir ultérieurement (scraping TM)
                    "",
                    "",
                    "",
                    "non",
                    data["n_ligues_sources"],
                    data["n_joueurs_total"],
                    ";".join(data["sources"]),
                ])

    print(f"[OK] {out1}")
    print(f"     {len(agg)} compétitions, dont {n_known} connues dans master "
          f"({len(agg) - n_known} inconnues à enrichir).")

    # === CSV 2 : competitions_vues_par_pays.csv ===
    # Regroupe par pays les compétitions CONNUES uniquement.
    by_pays: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for comp_id, data in agg.items():
        info = known.get(comp_id)
        if info:
            by_pays[info["pays"]].append(
                (comp_id, info["nom"], data["n_joueurs_total"])
            )

    out2 = OUT_DIR / "competitions_vues_par_pays.csv"
    with out2.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pays_fr",
            "nb_competitions_connues",
            "competitions_code_nom",
            "n_joueurs_total_pays",
        ])
        for pays in sorted(by_pays):
            comps = sorted(by_pays[pays], key=lambda t: -t[2])  # par joueurs desc
            code_noms = ";".join(f"{c}={n}" for c, n, _ in comps)
            total = sum(p for _, _, p in comps)
            w.writerow([pays, len(comps), code_noms, total])

    print(f"[OK] {out2}")
    print(f"     {len(by_pays)} pays couverts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
