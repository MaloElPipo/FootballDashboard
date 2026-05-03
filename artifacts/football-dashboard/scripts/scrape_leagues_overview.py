"""
Scrape Transfermarkt pour produire un CSV récapitulatif par championnat :
- Valeur marchande totale (saison en cours)
- Nombre d'équipes
- Valeur marchande moyenne par équipe (calculée)
- Buts par match sur les 5 dernières saisons (depuis la page tabelle)

Sortie : artifacts/football-dashboard/live/data/leagues_overview.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from live.leagues_master import LEAGUES  # noqa: E402

OUT_PATH = ROOT / "live" / "data" / "leagues_overview.csv"
ALL_SEASONS = [2025, 2024, 2023, 2022, 2021]
DELAY = 0.35
TIMEOUT = 20
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})


def parse_market_value(text: str) -> Optional[int]:
    """Convertit '€5.02bn', '€98.18m', '€500k', '€1.20bn' en euros entiers."""
    if not text:
        return None
    t = text.strip().replace("\xa0", " ")
    m = re.search(r"€\s*([\d.,]+)\s*(bn|m|k|mil|Mrd|Mio|Tsd)?", t, re.I)
    if not m:
        return None
    num_str = m.group(1).replace(",", "")
    try:
        num = float(num_str)
    except ValueError:
        return None
    unit = (m.group(2) or "").lower()
    mult = {
        "bn": 1_000_000_000,
        "mrd": 1_000_000_000,
        "m": 1_000_000,
        "mio": 1_000_000,
        "mil": 1_000_000,
        "k": 1_000,
        "tsd": 1_000,
        "": 1,
    }[unit]
    return int(num * mult)


def fetch(url: str) -> Optional[BeautifulSoup]:
    try:
        r = session.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        print(f"    ERREUR fetch {url}: {e}", file=sys.stderr)
        return None


def get_overview(slug: str, code: str) -> dict:
    """Page startseite -> Total MV + nb équipes + nb joueurs."""
    url = f"https://www.transfermarkt.com/{slug}/startseite/wettbewerb/{code}"
    soup = fetch(url)
    out = {"valeur_marchande_eur": None, "nb_equipes": None, "nb_joueurs": None}
    if soup is None:
        return out

    # Total Market Value
    for tag in soup.find_all(string=re.compile(r"Total\s*Market\s*Value", re.I)):
        # Le pattern observé : '€5.02bnTotal Market Value' dans le parent
        full = tag.parent.parent.get_text(" ", strip=True) if tag.parent and tag.parent.parent else str(tag)
        v = parse_market_value(full)
        if v:
            out["valeur_marchande_eur"] = v
            break

    # Nb teams + Nb players (texte 'Number of teams:18 teamsPlayers:518Foreigners:...')
    for tag in soup.find_all(string=re.compile(r"Number of teams", re.I)):
        full = tag.parent.parent.get_text(" ", strip=True) if tag.parent and tag.parent.parent else str(tag)
        m_t = re.search(r"Number of teams:?\s*(\d+)", full)
        m_p = re.search(r"Players:?\s*(\d+)", full)
        if m_t:
            out["nb_equipes"] = int(m_t.group(1))
        if m_p:
            out["nb_joueurs"] = int(m_p.group(1))
        break
    return out


def get_goals_per_match(slug: str, code: str, saison: int) -> Optional[float]:
    """Page tabelle saison X -> goals/match calculé depuis le classement."""
    url = f"https://www.transfermarkt.com/{slug}/tabelle/wettbewerb/{code}?saison_id={saison}"
    soup = fetch(url)
    if soup is None:
        return None
    table = soup.select_one("table.items")
    if not table:
        return None
    total_buts = 0
    total_matchs_eq = 0  # somme matchs joués pour toutes les équipes
    nb_teams_in_table = 0
    for tr in table.select("tbody tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        # Format observé : ['#', '', 'Club', 'M', 'W', 'D', 'L', 'X:Y', '+/-', 'Pts']
        if len(cells) < 10:
            continue
        m_played = cells[3]
        goals = cells[7]
        try:
            mp = int(m_played)
        except ValueError:
            continue
        m_g = re.match(r"(\d+)\s*:\s*(\d+)", goals)
        if not m_g:
            continue
        if mp == 0:
            continue
        total_buts += int(m_g.group(1))
        total_matchs_eq += mp
        nb_teams_in_table += 1
    if nb_teams_in_table == 0 or total_matchs_eq == 0:
        return None
    total_matchs = total_matchs_eq / 2
    return round(total_buts / total_matchs, 3)


FULL_FIELDS = [
    "code_tm", "championnat", "pays",
    "valeur_marchande_eur", "valeur_marchande_moy_equipe_eur",
    "nb_equipes", "nb_joueurs",
] + [f"buts_par_match_{s}_{str(s+1)[-2:]}" for s in ALL_SEASONS]


def _load_existing() -> dict:
    if not OUT_PATH.exists():
        return {}
    with open(OUT_PATH, newline="", encoding="utf-8") as f:
        return {r["code_tm"]: r for r in csv.DictReader(f)}


def _save(rows_by_code: dict):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Réordonne selon LEAGUES
    ordered = []
    for league in LEAGUES:
        r = rows_by_code.get(league["code_tm"])
        if r:
            ordered.append({k: r.get(k, "") for k in FULL_FIELDS})
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FULL_FIELDS)
        w.writeheader()
        w.writerows(ordered)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2025",
                    help="Saisons buts/match séparées par virgules (ex: 2025,2024). Default: 2025")
    ap.add_argument("--slice", default=":",
                    help="Tranche LEAGUES style python (ex: 0:30, 30:60). Default: tout")
    ap.add_argument("--skip-overview", action="store_true",
                    help="Ne pas refetcher la startseite (valeur marchande déjà connue)")
    args = ap.parse_args()

    seasons = [int(s) for s in args.seasons.split(",") if s.strip()]
    a, _, b = args.slice.partition(":")
    a = int(a) if a else 0
    b = int(b) if b else len(LEAGUES)
    leagues = LEAGUES[a:b]

    rows_by_code = _load_existing()
    n = len(leagues)
    print(f"Saisons: {seasons} | Tranche: {a}:{b} ({n} ligues) | skip_overview={args.skip_overview}")

    for i, league in enumerate(leagues, 1):
        code = league["code_tm"]
        slug = league["slug"]
        nom = league["nom"]
        pays = league["pays"]
        print(f"[{i}/{n}] {code} - {nom}", flush=True)

        row = rows_by_code.get(code, {k: "" for k in FULL_FIELDS})
        row["code_tm"] = code
        row["championnat"] = nom
        row["pays"] = pays

        if not args.skip_overview:
            ov = get_overview(slug, code)
            time.sleep(DELAY)
            mv_total = ov["valeur_marchande_eur"]
            nb_eq = ov["nb_equipes"]
            mv_avg = (mv_total // nb_eq) if (mv_total and nb_eq) else None
            row["valeur_marchande_eur"] = mv_total if mv_total is not None else ""
            row["valeur_marchande_moy_equipe_eur"] = mv_avg if mv_avg is not None else ""
            row["nb_equipes"] = nb_eq if nb_eq is not None else ""
            row["nb_joueurs"] = ov["nb_joueurs"] if ov["nb_joueurs"] is not None else ""

        for s in seasons:
            v = get_goals_per_match(slug, code, s)
            time.sleep(DELAY)
            row[f"buts_par_match_{s}_{str(s+1)[-2:]}"] = v if v is not None else ""

        rows_by_code[code] = row
        _save(rows_by_code)  # save après chaque ligue (résilience timeout)

    print(f"\nOK. {len(rows_by_code)} lignes au total -> {OUT_PATH}")


if __name__ == "__main__":
    main()
