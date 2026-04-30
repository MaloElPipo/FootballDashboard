"""
Scraper Transfermarkt par CLUB + SAISON pour championnats de clubs.

Note historique : la première version essayait de scraper les pages joueur
(/leistungsdatendetails/spieler/{id}) comme le script R `finalNewScrap.R`,
mais Transfermarkt a migré ces pages vers un rendu Svelte client-side, le
HTML brut ne contient plus de tableaux. Cette version pivote vers les
pages CLUB qui rendent encore une table HTML utilisable :

    /{slug}/leistungsdaten/verein/{club_id}/plus/0?reldata={comp}%26{saison}

Pipeline (3 étapes) :
  1) Lister les équipes d'une compétition (page startseite/wettbewerb/{code}).
  2) Pour chaque (équipe, saison) : 1 GET → table d'environ 25-45 lignes,
     une par joueur sur la compétition cette saison-là (numéro, position,
     player_id, name, âge, nationalité, in_squad, appearances, goals,
     minutes_played).
  3) Concaténer en CSV unique.

Compromis vs script R original : on perd les colonnes assists / yellow_cards
/ red_cards (la page club ne les expose pas). Pour le moteur Buteur Maison
4.1 ce sont matchs+buts+minutes qui comptent en primaire.

Optimisations :
- ThreadPoolExecutor (~3 workers) pour paralléliser les GET I/O bound.
- Pause aléatoire courte (0.1-0.4s) au sein de chaque worker.
- Headers Chrome 146 + Accept-Language fr/en + Referer transfermarkt.
- Décompression gzip manuelle.

Usage CLI :
    python tm_league_scraper.py --comp SFA1 --slug betway-premiership \
        --seasons 2021,2022,2023,2024,2025 \
        --out live/data/tm_scrap/sfa1.csv
    python tm_league_scraper.py --comp SFA1 --slug betway-premiership \
        --test --test-n-teams 1   # smoke test 1 club

Usage programmatique :
    from tm_league_scraper import scrape_league
    df_rows = scrape_league("SFA1", "betway-premiership",
                            seasons=[2021,2022,2023,2024,2025], workers=3)
"""

from __future__ import annotations

import argparse
import csv
import gzip
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape

# ============================================================
# Config & constantes
# ============================================================
BASE_URL = "https://www.transfermarkt.com"

TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.com/",
    "Accept-Encoding": "gzip",
}

TIMEOUT = 20
PAUSE_MIN = 0.10
PAUSE_MAX = 0.40

# ============================================================
# HTTP helpers
# ============================================================
def _fetch(url: str, timeout: int = TIMEOUT) -> tuple[str, int | None, str | None]:
    """GET avec gestion gzip + headers Chrome.

    Returns (html, status, error). En cas de succès : (html, 200, None).
    En cas d'échec : ("", status_code_si_dispo, message_d'erreur).
    Cela permet à l'appelant de distinguer "page vide légitime" (200 + html
    sans table) de "erreur réseau" (timeout, 5xx, 429).
    """
    req = urllib.request.Request(url, headers=TM_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            return data.decode("utf-8", errors="replace"), r.status, None
    except urllib.error.HTTPError as e:
        return "", e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return "", None, f"URL error: {e.reason}"
    except TimeoutError:
        return "", None, "timeout"
    except Exception as e:
        return "", None, f"{type(e).__name__}: {e}"


def _fetch_html(url: str, timeout: int = TIMEOUT) -> str:
    """Wrapper compat : ne renvoie que le HTML (vide si erreur). Pour appelants
    qui n'ont pas besoin du statut détaillé."""
    html, _status, _err = _fetch(url, timeout)
    return html


def _polite_pause():
    time.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))


# ============================================================
# Parsing helpers (regex pures, pas de bs4)
# ============================================================
def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _to_int(s: str) -> int:
    """Convertit '16', '1.408', '-', '' → int. Strip apostrophe minutes."""
    if s is None:
        return 0
    s = s.strip().rstrip("'").replace(".", "").replace(",", "").replace("\xa0", "")
    if not s or s == "-":
        return 0
    try:
        return int(s)
    except ValueError:
        # Garde les chiffres uniquement
        digits = re.sub(r"[^\d]", "", s)
        return int(digits) if digits else 0


def _find_table_end(html: str, start: int) -> int:
    """Trouve la fin de la table à `start` (au '<table') en gérant l'imbrication."""
    pos = start + len("<table")
    depth = 1
    while pos < len(html) and depth > 0:
        m = re.search(r"<(/?)table\b", html[pos:])
        if not m:
            return -1
        if m.group(1) == "/":
            depth -= 1
        else:
            depth += 1
        pos += m.end()
    return pos


def _split_top_level(html: str, tag: str) -> list[str]:
    """Découpe les balises `tag` (tr, td) au top-level, en gérant l'imbrication."""
    cells: list[str] = []
    depth = 0
    cur: int | None = None
    pat = re.compile(rf"<(/?){tag}\b[^>]*>")
    i = 0
    while i < len(html):
        m = pat.match(html, i)
        if m:
            if m.group(1) == "/":
                depth -= 1
                if depth == 0 and cur is not None:
                    cells.append(html[cur:i])
                    cur = None
            else:
                if depth == 0:
                    cur = i + m.end() - i  # i + length matched from i
                depth += 1
            i += m.end() - m.start()
        else:
            i += 1
    return cells


# ============================================================
# Étape 1 : Équipes d'une compétition
# ============================================================
# Match deux ordres possibles : title= avant ou après href=
# Le href peut contenir un suffixe /saison_id/YYYY après l'ID club, on l'accepte
_TEAM_LINK_PAT_A = re.compile(
    r'<a\s+title="([^"]+)"\s+href="(/([^/"]+)/startseite/verein/(\d+))[^"]*"'
)
_TEAM_LINK_PAT_B = re.compile(
    r'<a\s+href="(/([^/"]+)/startseite/verein/(\d+))[^"]*"\s+title="([^"]+)"'
)


def get_league_teams(comp_code: str, slug: str = "x") -> list[dict]:
    """Liste des équipes (id, slug, name) d'une compétition TM."""
    url = f"{BASE_URL}/{slug}/startseite/wettbewerb/{comp_code}"
    html, status, err = _fetch(url)
    if not html:
        print(f"   ! échec liste équipes {comp_code}: status={status} err={err}", flush=True)
        return []
    seen: set[str] = set()
    teams: list[dict] = []
    # Pattern A : title= avant href= (cas observé en 04/2026)
    for m in _TEAM_LINK_PAT_A.finditer(html):
        title, _href, team_slug, club_id = m.group(1), m.group(2), m.group(3), m.group(4)
        if club_id in seen:
            continue
        seen.add(club_id)
        teams.append({"team_id": club_id, "team_slug": team_slug,
                      "team_name": unescape(title)})
    # Pattern B : href= avant title= (fallback ancien layout)
    for m in _TEAM_LINK_PAT_B.finditer(html):
        _href, team_slug, club_id, title = m.group(1), m.group(2), m.group(3), m.group(4)
        if club_id in seen:
            continue
        seen.add(club_id)
        teams.append({"team_id": club_id, "team_slug": team_slug,
                      "team_name": unescape(title)})
    return teams


# ============================================================
# Étape 2 : Stats joueurs d'un CLUB pour une SAISON donnée
# ============================================================
_PLAYER_PROFIL_PAT = re.compile(r'/profil/spieler/(\d+)')
_LINK_TITLE_PAT = re.compile(r'<a[^>]+title="([^"]+)"')
_IMG_TITLE_PAT = re.compile(r'<img[^>]+title="([^"]+)"')
_POS_TAIL_PAT = re.compile(r"</tr>\s*<tr>\s*<td>([^<]+)</td>", re.IGNORECASE)


def _extract_player_cell(td_html: str) -> tuple[str | None, str | None, str | None]:
    """Depuis la cellule [1] (nom+lien+position), renvoie (player_id, name, position)."""
    pid_m = _PLAYER_PROFIL_PAT.search(td_html)
    pid = pid_m.group(1) if pid_m else None

    # Nom : meilleur candidat = title du <a> qui pointe vers /profil/spieler/
    name = None
    for m in re.finditer(r'<a\s+title="([^"]+)"\s+href="([^"]+)"', td_html):
        if "/profil/spieler/" in m.group(2):
            name = unescape(m.group(1))
            break
    if not name:
        # Fallback : tout premier title= rencontré
        m = _LINK_TITLE_PAT.search(td_html)
        if m:
            name = unescape(m.group(1))

    # Position : 2e ligne <tr><td>Position</td></tr> dans la sous-table inline
    pos = None
    pm = _POS_TAIL_PAT.search(td_html)
    if pm:
        pos = unescape(pm.group(1)).strip()
    return pid, name, pos


def _extract_nationality(td_html: str) -> str | None:
    m = _IMG_TITLE_PAT.search(td_html)
    return unescape(m.group(1)).strip() if m else None


def get_club_season_perfs(
    club_id: str,
    club_slug: str,
    club_name: str,
    comp_code: str,
    season: int,
) -> list[dict]:
    """Récupère les perfs joueurs d'un club sur une compétition + saison.

    URL : /{club_slug}/leistungsdaten/verein/{club_id}/plus/0?reldata={comp}%26{season}

    Retourne une liste de dicts par joueur. Une saison renvoie typiquement 25-45
    lignes. Si la saison n'existe pas (club promu plus tard) ou si la page est
    vide, retourne [].
    """
    url = (
        f"{BASE_URL}/{club_slug}/leistungsdaten/verein/{club_id}/plus/0"
        f"?reldata={comp_code}%26{season}"
    )
    _polite_pause()
    html, status, err = _fetch(url)
    if not html:
        # Distingue erreur réseau (status None ou 5xx) vs page vide légitime.
        if status is None or (status and status >= 500) or status == 429:
            print(
                f"   ! erreur fetch club={club_id} saison={season}: "
                f"status={status} err={err}",
                flush=True,
            )
        return []

    # Cherche la 1re table.items (regex tolérante : classes additionnelles
    # type class="items table-foo" autorisées).
    m = re.search(r'<table[^>]*\bclass="[^"]*\bitems\b[^"]*"[^>]*>', html)
    if not m:
        return []
    end = _find_table_end(html, m.start())
    if end < 0:
        return []
    tbl = html[m.start():end]

    tbody_m = re.search(r"<tbody>([\s\S]*)</tbody>", tbl, re.IGNORECASE)
    if not tbody_m:
        return []
    tbody = tbody_m.group(1)

    rows = _split_top_level(tbody, "tr")
    if not rows:
        return []

    out: list[dict] = []
    for row in rows:
        # Filtre : on veut uniquement les lignes "data" (class odd/even),
        # pas les éventuels en-têtes de groupe.
        cells = _split_top_level(row, "td")
        if len(cells) < 8:
            continue

        # Cell 0 : numéro maillot (peut être vide)
        shirt_txt = _strip_html(cells[0])
        try:
            shirt = int(re.sub(r"[^\d]", "", shirt_txt) or 0)
        except ValueError:
            shirt = 0

        pid, name, pos = _extract_player_cell(cells[1])
        if not pid:
            continue  # ligne sans joueur identifiable (bandeau, etc.)

        age = _to_int(_strip_html(cells[2]))
        nat = _extract_nationality(cells[3])
        in_squad = _to_int(_strip_html(cells[4]))
        apps = _to_int(_strip_html(cells[5]))
        goals = _to_int(_strip_html(cells[6]))
        minutes = _to_int(_strip_html(cells[7]))

        out.append({
            "player_id": pid,
            "player_name": name or "",
            "team_id": club_id,
            "team_name": club_name,
            "season": season,
            "competition": comp_code,
            "shirt_number": shirt,
            "position": pos or "",
            "age": age,
            "nationality": nat or "",
            "in_squad": in_squad,
            "appearances": apps,
            "goals": goals,
            "minutes_played": minutes,
        })
    return out


# ============================================================
# Orchestrateur
# ============================================================
def scrape_league(
    comp_code: str,
    slug: str,
    seasons: list[int],
    workers: int = 3,
    test_n_teams: int | None = None,
    progress_cb=None,
) -> list[dict]:
    """Scrape une compétition complète sur N saisons.

    Args:
        comp_code  : code TM (ex 'SFA1' pour Betway Premiership).
        slug       : slug ligue (ex 'betway-premiership').
        seasons    : liste d'années (ex [2021, 2022, 2023, 2024, 2025]).
        workers    : nb threads parallèles.
        test_n_teams : si fourni, ne scrape que les N premières équipes.

    Returns:
        Liste de dicts (1 par joueur × club × saison).
    """
    print(f"=== Scraping {comp_code} (slug={slug}) saisons={seasons} ===", flush=True)

    # Étape 1 : équipes
    print("── Étape 1 : équipes de la ligue", flush=True)
    teams = get_league_teams(comp_code, slug)
    if not teams:
        print("   ! aucune équipe trouvée", flush=True)
        return []
    print(f"   {len(teams)} équipes trouvées", flush=True)

    if test_n_teams is not None:
        teams = teams[:test_n_teams]
        names = ", ".join(t["team_name"] for t in teams)
        print(f"   TEST MODE : {len(teams)} équipe(s) ({names})", flush=True)

    # Étape 2 : (club × saison) en parallèle
    tasks = [(t, s) for t in teams for s in seasons]
    print(f"── Étape 2 : {len(tasks)} GET (clubs={len(teams)} × saisons={len(seasons)}, workers={workers})", flush=True)

    rows: list[dict] = []
    rows_lock = threading.Lock()
    done = 0
    t0 = time.time()

    def worker(team_dict: dict, season: int) -> tuple[str, int, int]:
        try:
            r = get_club_season_perfs(
                team_dict["team_id"], team_dict["team_slug"],
                team_dict["team_name"], comp_code, season,
            )
        except Exception as e:
            print(f"   ! err {team_dict['team_name']} {season}: {e}", flush=True)
            return team_dict["team_name"], season, 0
        with rows_lock:
            rows.extend(r)
        return team_dict["team_name"], season, len(r)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(worker, t, s) for (t, s) in tasks]
        for f in as_completed(futures):
            tname, season, n = f.result()
            done += 1
            if done % 5 == 0 or done == len(tasks):
                elapsed = time.time() - t0
                print(f"   [{done}/{len(tasks)}] {tname} {season}: {n} joueurs ({elapsed:.1f}s écoulées)", flush=True)
            if progress_cb:
                progress_cb(done, len(tasks))

    dt = (time.time() - t0) / 60
    print(f"=== Terminé en {dt:.1f} min : {len(rows)} lignes ===", flush=True)
    return rows


# ============================================================
# Sortie CSV
# ============================================================
COLUMNS = [
    "player_id", "player_name", "team_id", "team_name",
    "season", "competition", "shirt_number", "position",
    "age", "nationality", "in_squad", "appearances",
    "goals", "minutes_played",
]


def _write_csv(rows: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    print(f"\n✓ Saved {len(rows)} rows to {path}", flush=True)


# ============================================================
# CLI
# ============================================================
def main():
    p = argparse.ArgumentParser(description="Scraper TM par club × saison")
    p.add_argument("--comp", required=True, help="Code compétition TM (ex SFA1)")
    p.add_argument("--slug", required=True, help="Slug compétition (ex betway-premiership)")
    p.add_argument(
        "--seasons", default="2021,2022,2023,2024,2025",
        help="Saisons CSV (ex 2021,2022,2023,2024,2025). Défaut : 5 dernières.",
    )
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--out", default=None, help="Chemin CSV de sortie")
    p.add_argument("--test", action="store_true", help="Mode test (limite équipes)")
    p.add_argument("--test-n-teams", type=int, default=1, help="Nb équipes en mode test")
    args = p.parse_args()

    try:
        seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    except ValueError:
        print("ERREUR : --seasons doit être une liste d'entiers (ex 2021,2022,2023)", file=sys.stderr)
        sys.exit(2)

    out = args.out
    if out is None:
        out = f"live/data/tm_scrap/{args.comp.lower()}.csv"

    rows = scrape_league(
        comp_code=args.comp,
        slug=args.slug,
        seasons=seasons,
        workers=args.workers,
        test_n_teams=(args.test_n_teams if args.test else None),
    )
    _write_csv(rows, out)


if __name__ == "__main__":
    main()
