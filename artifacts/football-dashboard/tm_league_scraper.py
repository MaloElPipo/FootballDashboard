"""
Scraper Transfermarkt généralisé pour championnats de clubs.

Port Python du script R `finalNewScrap.R`. Pipeline :
  1) Lister les équipes d'une compétition (page startseite/wettbewerb/{code})
  2) Lister les joueurs de chaque équipe (page kader)
  3) Pour chaque joueur, scraper TOUTES les saisons en 1 requête via la
     page leistungsdatendetails (toutes saisons d'un coup) ; fallback
     saison par saison si la page globale échoue.
  4) Résoudre les noms de clubs avec un cache mémoïsé (un seul GET par
     club même si N joueurs y sont passés).

Optimisations vs squad_scraper.py :
- Threading (ThreadPoolExecutor, équivalent furrr) pour paralléliser
  les requêtes I/O bound.
- Cache club thread-safe (Lock).
- Pause aléatoire courte (0.1-0.4s) au sein de chaque worker.
- Headers Chrome 146 + Accept-Language fr/en + Referer transfermarkt.

Usage :
    from tm_league_scraper import scrape_league
    df = scrape_league(comp_code="SFA1", slug="betway-premiership",
                       seasons=range(2016, 2026), workers=3)
    df.to_csv("psl_scrap.csv", index=False)
"""

from __future__ import annotations

import argparse
import csv
import json
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
from typing import Iterable

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
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.transfermarkt.com/",
}

PAUSE_MIN = 0.10
PAUSE_MAX = 0.40
TIMEOUT = 20

# ============================================================
# Cache de clubs thread-safe (équivalent du new.env() R)
# ============================================================
_club_cache: dict[str, str | None] = {}
_club_cache_lock = threading.Lock()


# ============================================================
# HTTP helper avec gestion gzip
# ============================================================
def _fetch(url: str, timeout: int = TIMEOUT) -> str:
    """GET tolérant aux pannes. Retourne "" en cas d'échec."""
    headers = dict(TM_HEADERS)
    # urllib gère gzip/deflate seulement si on lit manuellement le content-encoding
    headers["Accept-Encoding"] = "gzip"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return ""


def _polite_pause():
    """Pause aléatoire courte entre requêtes — comportement humain-like."""
    time.sleep(random.uniform(PAUSE_MIN, PAUSE_MAX))


# ============================================================
# Étape 1 : équipes de la ligue
# ============================================================
def get_league_teams(comp_code: str, slug: str = "x") -> list[dict]:
    """Liste les équipes d'une compétition.

    Args:
        comp_code: code TM de la compétition (ex: "SFA1" pour Betway Premiership).
        slug: slug url-friendly (mis à "x" par défaut, TM redirige correctement).

    Returns:
        list[{team_name, team_id, team_slug, team_url}]
    """
    url = f"{BASE_URL}/{slug}/startseite/wettbewerb/{comp_code}"
    html = _fetch(url)
    if not html:
        raise RuntimeError(f"Impossible d'accéder à la page de la ligue {comp_code}")

    # Extraire toutes les références <a href="/{slug}/startseite/verein/{id}">
    # depuis la table principale. Pattern défensif tolérant aux espaces/quotes.
    pattern = re.compile(
        r'<a[^>]+href="/([^"/]+)/startseite/verein/(\d+)[^"]*"[^>]*>([^<]+)</a>',
        re.IGNORECASE,
    )
    seen: set[str] = set()
    teams: list[dict] = []
    for m in pattern.finditer(html):
        team_slug = unescape(m.group(1)).strip()
        team_id = m.group(2)
        team_name = unescape(m.group(3)).strip()
        if team_id in seen or not team_name or len(team_name) < 2:
            continue
        # Filtrer les liens d'image / wrapper (texte vide ou "Logo")
        if team_name.lower() in ("logo", "wappen"):
            continue
        seen.add(team_id)
        teams.append({
            "team_name": team_name,
            "team_id": team_id,
            "team_slug": team_slug,
            "team_url": f"/{team_slug}/startseite/verein/{team_id}",
        })
    return teams


# ============================================================
# Étape 2 : joueurs d'une équipe
# ============================================================
# Capture (player_slug, player_id) — l'ordre des attributs étant variable
# sur TM, on ne peut pas exiger title= juste après href. Le nom est résolu
# en 2e passe (img alt → title= → fallback slug capitalisé).
_PLAYER_HREF_PAT = re.compile(
    r'href="/([^"/]+)/profil/spieler/(\d+)"',
    re.IGNORECASE,
)


def _name_for_player(html: str, player_id: str, player_slug: str) -> str:
    """Cherche le nom du joueur dans le HTML autour de son lien.

    Stratégie :
      1) Première occurrence de `/profil/spieler/{id}` → fenêtre ±400 chars
      2) Chercher `<img ... alt="Nom"` ou `title="Nom"` ou texte du <a>
      3) Fallback : reconstituer depuis le slug ("ronwen-williams" →
         "Ronwen Williams"). Toujours valide même si TM change le DOM.
    """
    needle = f'/profil/spieler/{player_id}'
    idx = html.find(needle)
    if idx >= 0:
        window = html[max(0, idx - 200):idx + 400]
        # img alt= avec un nom non vide
        m = re.search(r'<img[^>]+alt="([^"]{2,})"', window)
        if m:
            n = unescape(m.group(1)).strip()
            if n and "logo" not in n.lower():
                return n
        # title="Nom" sur le lien englobant
        m2 = re.search(r'title="([^"]{2,})"', window)
        if m2:
            n = unescape(m2.group(1)).strip()
            if n and "logo" not in n.lower():
                return n
        # Texte direct du <a>
        m3 = re.search(
            r'<a[^>]+/profil/spieler/' + re.escape(player_id) + r'[^>]*>([^<]+)</a>',
            window,
        )
        if m3:
            n = unescape(m3.group(1)).strip()
            if n:
                return n
    # Fallback : slug capitalisé. "ronwen-williams" → "Ronwen Williams"
    parts = [p for p in player_slug.split("-") if p]
    return " ".join(part.capitalize() for part in parts)


def get_team_players(team_id: str, team_slug: str, team_name: str) -> list[dict]:
    """Liste les joueurs d'une équipe via la page kader détaillée.

    Page : /{slug}/kader/verein/{id}/plus/1 — contient 1 ligne par joueur
    avec poste dans la sous-table .posrela.
    """
    url = f"{BASE_URL}/{team_slug}/kader/verein/{team_id}/plus/1"
    _polite_pause()
    html = _fetch(url)
    if not html:
        return []

    # 1ʳᵉ passe : (slug, id) uniques, ordre du DOM préservé.
    seen: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for m in _PLAYER_HREF_PAT.finditer(html):
        pid = m.group(2)
        if pid in seen:
            continue
        seen.add(pid)
        pairs.append((unescape(m.group(1)).strip(), pid))

    # 2ᵉ passe : nom + poste résolus contextuellement
    players: list[dict] = []
    for player_slug, pid in pairs:
        players.append({
            "player_id": pid,
            "player_name": _name_for_player(html, pid, player_slug),
            "player_slug": player_slug,
            "team_id": team_id,
            "team_slug": team_slug,
            "team_name": team_name,
            "player_pos": _extract_position_for_player(html, pid),
        })
    return players


def _extract_position_for_player(html: str, player_id: str) -> str | None:
    """Cherche le poste du joueur autour de son lien dans la table kader.

    Heuristique : la table TM affiche le poste dans la dernière ligne d'une
    sous-table .posrela attachée à la ligne du joueur. On prend une fenêtre
    HTML de ±2000 caractères autour du lien profil et on cherche un libellé
    de poste connu (FR / EN / DE).
    """
    # Localiser le premier match du player_id dans le HTML
    needle = f'/profil/spieler/{player_id}"'
    idx = html.find(needle)
    if idx < 0:
        return None
    # Fenêtre vers la suite (la cellule poste vient après le nom)
    window = html[idx:idx + 2500]
    # Match d'un libellé de poste connu
    poses = (
        "Goalkeeper", "Gardien", "Torwart", "Keeper",
        "Centre-Back", "Left-Back", "Right-Back", "Defender", "Défenseur",
        "Defensive Midfield", "Central Midfield", "Attacking Midfield",
        "Left Midfield", "Right Midfield", "Midfielder", "Milieu",
        "Left Winger", "Right Winger", "Second Striker",
        "Centre-Forward", "Forward", "Attaquant", "Stürmer",
    )
    pat = re.compile(
        r">\s*(" + "|".join(re.escape(p) for p in poses) + r")\s*<",
        re.IGNORECASE,
    )
    m = pat.search(window)
    return m.group(1) if m else None


# ============================================================
# Étape 3 : toutes les saisons d'un joueur en 1 requête
# ============================================================
# Capture chaque box de saison + sa table — boxes ordonnés du plus récent
# au plus ancien sur la page leistungsdatendetails.
_SEASON_BOX_PAT = re.compile(
    r'<div class="box">.*?</div>\s*</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
# Header "Détail des matchs - 24/25" ou "Detailed stats - 24/25"
_SEASON_HEADER_PAT = re.compile(r'(\d{2})/(\d{2})')
# Lignes de données dans table.items
_TBODY_ROW_PAT = re.compile(r'<tr[^>]*>.*?</tr>', re.IGNORECASE | re.DOTALL)
_TD_PAT = re.compile(r'<td[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)
_TAG_STRIP = re.compile(r'<[^>]+>')
_VEREIN_ID_PAT = re.compile(r'verein/(\d+)')


def _strip_html(s: str) -> str:
    return unescape(_TAG_STRIP.sub("", s)).strip()


def get_all_seasons_stats(
    player_id: str, player_name: str, player_slug: str,
    min_season_year: int = 2016,
) -> list[dict]:
    """Scrape toutes les saisons d'un joueur en 1 requête.

    Page : /{slug}/leistungsdatendetails/spieler/{id}/plus/1
    Si vide, fallback saison par saison.
    """
    url = (
        f"{BASE_URL}/{player_slug}/leistungsdatendetails/"
        f"spieler/{player_id}/plus/1"
    )
    _polite_pause()
    html = _fetch(url)
    if not html:
        return []

    rows: list[dict] = []
    # Découper grossièrement la page en boxes par occurrence d'un header de
    # saison (plus tolérant que la regex .box ouverte/fermée).
    # On split sur "<div class=\"box\"" et on traite chaque chunk.
    chunks = re.split(r'<div class="box"', html)
    for chunk in chunks[1:]:  # skip pre-header chunk
        # Identifier la saison du chunk : header "20/21" ou "Saison 20/21"
        head_m = re.search(r'>(.{0,200}?\d{2}/\d{2}.{0,200}?)<', chunk)
        if not head_m:
            continue
        season_m = _SEASON_HEADER_PAT.search(head_m.group(1))
        if not season_m:
            continue
        ys = int(season_m.group(1))
        season = (1900 + ys) if ys > 90 else (2000 + ys)
        if season < min_season_year:
            continue

        # Trouver la table.items dans le chunk
        table_m = re.search(
            r'<table class="items">.*?</table>',
            chunk,
            re.IGNORECASE | re.DOTALL,
        )
        if not table_m:
            continue
        table = table_m.group(0)
        for row_m in _TBODY_ROW_PAT.finditer(table):
            row_html = row_m.group(0)
            # Skip rows d'en-tête (th) et lignes "Total" (footer)
            if "<th" in row_html.lower():
                continue
            tds = _TD_PAT.findall(row_html)
            if len(tds) < 13:
                continue
            texts = [_strip_html(td) or "0" for td in tds]
            # Compétition : peut être un lien avec image — strip + texte
            competition = texts[1] if len(texts) > 1 else ""
            if not competition or competition.lower() in ("total", "totaux"):
                continue
            # Verein de la saison : 1er lien /verein/ dans la ligne
            v_m = _VEREIN_ID_PAT.search(row_html)
            verein_id = v_m.group(1) if v_m else None
            # Mapping colonnes TM (leistungsdatendetails) :
            #  0:numéro/logo  1:competition  2:appearances  3:goals
            #  4:assists      5:own_goals    6:subs_in     7:subs_out
            #  8:yellow       9:second_yellow  10:red       11:pens
            #  12:minutes_per_goal  13:minutes
            row = {
                "player_id": player_id,
                "player_name": player_name,
                "season": season,
                "verein_id": verein_id,
                "competition": competition,
                "appearances": _to_int(texts[2]),
                "goals": _to_int(texts[3]),
                "assists": _to_int(texts[4]),
                "yellow_cards": _to_int(texts[8]) if len(texts) > 8 else 0,
                "red_cards": _to_int(texts[10]) if len(texts) > 10 else 0,
                "minutes": _to_int(texts[13]) if len(texts) > 13 else 0,
            }
            rows.append(row)
    return rows


def _to_int(s: str) -> int:
    """Parse défensif d'un nombre TM : strip non-digits, '-' → 0."""
    if not s or s in ("-", "0"):
        return 0 if s != "" else 0
    # "1.234" (séparateur milliers) ou "1,234" → on garde les chiffres
    digits = re.sub(r"[^0-9]", "", s)
    return int(digits) if digits else 0


# ============================================================
# Étape 4 : résolution des noms de clubs avec cache mémoïsé
# ============================================================
def get_club_name(verein_id: str) -> str | None:
    """Résout l'ID club TM → nom officiel. Cache thread-safe."""
    if not verein_id:
        return None
    with _club_cache_lock:
        if verein_id in _club_cache:
            return _club_cache[verein_id]

    _polite_pause()
    url = f"{BASE_URL}/x/startseite/verein/{verein_id}"
    html = _fetch(url)
    name: str | None = None
    if html:
        # <h1 class="data-header__headline-wrapper">...Nom Club...</h1>
        m = re.search(
            r'<h1[^>]*data-header__headline-wrapper[^>]*>(.*?)</h1>',
            html,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            name = _strip_html(m.group(1)) or None
        if not name:
            # Fallback : 1er <h1> de la page
            m2 = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
            if m2:
                name = _strip_html(m2.group(1)) or None

    with _club_cache_lock:
        _club_cache[verein_id] = name
    return name


# ============================================================
# Pipeline principal
# ============================================================
def scrape_league(
    comp_code: str,
    slug: str = "x",
    *,
    workers: int = 3,
    min_season_year: int = 2016,
    test_mode: bool = False,
    test_n_players: int | None = None,
    filter_goalkeepers: bool = True,
    log_fn=print,
) -> list[dict]:
    """Pipeline complet R-style.

    Returns:
        list de dicts (1 ligne par joueur×saison×compétition), prêt à être
        écrit en CSV ou converti en DataFrame.
    """
    t0 = time.time()
    log_fn(f"=== Scraping {comp_code} (slug={slug}) ===")

    # 1) Équipes
    log_fn("── Étape 1 : équipes de la ligue")
    teams = get_league_teams(comp_code, slug)
    log_fn(f"   {len(teams)} équipes trouvées")
    if test_mode and teams:
        teams = teams[:1]
        log_fn(f"   TEST MODE : 1 équipe ({teams[0]['team_name']})")

    # 2) Joueurs de chaque équipe (parallélisé)
    log_fn(f"── Étape 2 : joueurs ({len(teams)} équipes, {workers} workers)")
    all_players: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(get_team_players, t["team_id"], t["team_slug"],
                      t["team_name"]): t
            for t in teams
        }
        for i, fut in enumerate(as_completed(futs), 1):
            t = futs[fut]
            try:
                ps = fut.result()
            except Exception as e:
                log_fn(f"   [{i}/{len(teams)}] ERR {t['team_name']}: {e}")
                continue
            log_fn(f"   [{i}/{len(teams)}] {t['team_name']}: {len(ps)} joueurs")
            all_players.extend(ps)

    log_fn(f"   {len(all_players)} joueurs récupérés")

    if filter_goalkeepers:
        n_before = len(all_players)
        all_players = [
            p for p in all_players
            if not p.get("player_pos") or not re.search(
                r"goalkeeper|gardien|torwart|keeper",
                p["player_pos"], re.IGNORECASE,
            )
        ]
        log_fn(f"   Gardiens filtrés : {n_before} → {len(all_players)}")

    # Dédup par player_id (au cas où un joueur soit dans 2 effectifs)
    seen: set[str] = set()
    deduped: list[dict] = []
    for p in all_players:
        if p["player_id"] in seen:
            continue
        seen.add(p["player_id"])
        deduped.append(p)
    all_players = deduped
    log_fn(f"   {len(all_players)} joueurs uniques")

    if test_n_players is not None and test_n_players < len(all_players):
        random.shuffle(all_players)
        all_players = all_players[:test_n_players]
        log_fn(f"   Sous-échantillon : {len(all_players)} joueurs")

    # 3) Stats toutes saisons par joueur (parallélisé)
    log_fn(f"── Étape 3 : stats joueurs ({len(all_players)} joueurs, {workers} workers)")
    stats_rows: list[dict] = []
    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(
                get_all_seasons_stats,
                p["player_id"], p["player_name"], p["player_slug"],
                min_season_year,
            ): p
            for p in all_players
        }
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                rows = fut.result()
            except Exception as e:
                rows = []
                log_fn(f"   ERR {p['player_name']}: {e}")
            stats_rows.extend(rows)
            completed += 1
            if completed % 25 == 0 or completed == len(all_players):
                log_fn(f"   Progress {completed}/{len(all_players)} "
                       f"(rows: {len(stats_rows)})")

    # 4) Résolution clubs
    unique_vids = sorted({r["verein_id"] for r in stats_rows if r.get("verein_id")})
    log_fn(f"── Étape 4 : résolution {len(unique_vids)} clubs uniques")
    club_map: dict[str, str | None] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(get_club_name, vid): vid for vid in unique_vids}
        for fut in as_completed(futs):
            vid = futs[fut]
            try:
                club_map[vid] = fut.result()
            except Exception:
                club_map[vid] = None

    # Merge final + ajout des infos joueur (team_name, player_pos)
    pinfo = {p["player_id"]: p for p in all_players}
    final_rows: list[dict] = []
    for r in stats_rows:
        info = pinfo.get(r["player_id"], {})
        final_rows.append({
            "player_id": r["player_id"],
            "player_name": r["player_name"],
            "team_name": info.get("team_name"),
            "player_pos": info.get("player_pos"),
            "season": r["season"],
            "competition": r["competition"],
            "club": club_map.get(r["verein_id"]),
            "appearances": r["appearances"],
            "goals": r["goals"],
            "assists": r["assists"],
            "yellow_cards": r["yellow_cards"],
            "red_cards": r["red_cards"],
            "minutes_played": r["minutes"],
        })

    elapsed = (time.time() - t0) / 60.0
    n_players = len({r["player_id"] for r in final_rows})
    log_fn(f"=== Terminé en {elapsed:.1f} min : "
           f"{len(final_rows)} lignes pour {n_players} joueurs ===")
    return final_rows


# ============================================================
# CLI
# ============================================================
def _write_csv(rows: list[dict], path: str) -> None:
    if not rows:
        # Écrit quand même un CSV vide avec entête pour debug
        cols = ["player_id", "player_name", "team_name", "player_pos",
                "season", "competition", "club", "appearances", "goals",
                "assists", "yellow_cards", "red_cards", "minutes_played"]
    else:
        cols = list(rows[0].keys())
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--comp", required=True, help="Code TM (ex: SFA1)")
    ap.add_argument("--slug", default="x", help="Slug URL (ex: betway-premiership)")
    ap.add_argument("--out", required=True, help="Chemin CSV de sortie")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--min-season", type=int, default=2016)
    ap.add_argument("--test", action="store_true", help="Mode test : 1 équipe")
    ap.add_argument("--test-n-players", type=int, default=None)
    ap.add_argument("--keep-gk", action="store_true",
                    help="Ne pas filtrer les gardiens")
    args = ap.parse_args()

    rows = scrape_league(
        comp_code=args.comp,
        slug=args.slug,
        workers=args.workers,
        min_season_year=args.min_season,
        test_mode=args.test,
        test_n_players=args.test_n_players,
        filter_goalkeepers=not args.keep_gk,
    )
    _write_csv(rows, args.out)
    print(f"\n✓ Saved {len(rows)} rows to {args.out}")


if __name__ == "__main__":
    main()
