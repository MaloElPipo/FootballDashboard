"""
Scraper Transfermarkt pour les effectifs des équipes nationales CM 2026.
Pipeline validé : fixture page → match IDs → lineups → profils joueurs.
Cache sur disque avec TTL configurable.
"""

import urllib.request
import re
import json
import os
import time
from datetime import datetime
from html import unescape

CACHE_FILE = os.path.join(os.path.dirname(__file__), "squads_cache.json")
STATIC_DB_FILE = os.path.join(os.path.dirname(__file__), "squads_static.json")
CACHE_TTL_HOURS = 48

TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.transfermarkt.fr/",
}

REQUEST_DELAY = 0.6


def _fetch(url: str, timeout: int = 15) -> str:
    try:
        req = urllib.request.Request(url, headers=TM_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return ""


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _is_cache_valid(entry: dict) -> bool:
    ts = entry.get("fetched_at", "")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts)
        age_h = (datetime.now() - fetched).total_seconds() / 3600
        return age_h < CACHE_TTL_HOURS
    except Exception:
        return False


def _load_static_db() -> dict:
    """Charge la base de données statique pré-scrappée."""
    if not os.path.exists(STATIC_DB_FILE):
        return {}
    try:
        with open(STATIC_DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_static_squad(code: str) -> list[dict]:
    """Renvoie l'effectif depuis la base statique (sans scraping)."""
    db = _load_static_db()
    return db.get(code, {}).get("players", [])


def get_static_db_status() -> dict:
    """Retourne le statut de la base statique : {code: {n_players, scraped_at}}."""
    db = _load_static_db()
    return {
        code: {
            "n_players": len(entry.get("players", [])),
            "scraped_at": entry.get("scraped_at", ""),
        }
        for code, entry in db.items()
        if entry.get("players")
    }


# ─────────────────────────────────────────────
# Step 1 : récupérer les 5 derniers match IDs
# ─────────────────────────────────────────────

def get_recent_match_ids(slug: str, tm_id: int, n: int = 5) -> list[str]:
    """Renvoie les n derniers match IDs depuis la page des fixtures TM."""
    url = (
        f"https://www.transfermarkt.fr/{slug}/spielplandatum"
        f"/verein/{tm_id}/saison_id/2025"
    )
    html = _fetch(url)
    if not html:
        # Essayer saison 2024 en fallback
        url = (
            f"https://www.transfermarkt.fr/{slug}/spielplandatum"
            f"/verein/{tm_id}/saison_id/2024"
        )
        html = _fetch(url)
    if not html:
        return []

    raw = re.findall(r"spielbericht/index/spielbericht/(\d+)", html)
    unique = list(dict.fromkeys(raw))
    return unique[-n:]


# ─────────────────────────────────────────────
# Step 2 : scraper le lineup d'un match
# ─────────────────────────────────────────────

def _parse_player_block(block: str) -> list[dict]:
    """
    Extrait les joueurs d'un bloc HTML de lineup TM.
    Cherche les liens /profil/spieler/{id} et lit le nom dans l'attribut alt de l'img.
    """
    players = []
    # Pattern: href="/slug/profil/spieler/{id}"> <img alt="Name" ...>
    pattern = re.compile(
        r'href="/[^/]+/profil/spieler/(\d+)"[^>]*>\s*<img[^>]+alt="([^"]+)"',
        re.IGNORECASE | re.DOTALL,
    )
    seen = set()
    for m in pattern.finditer(block):
        pid, name = m.group(1), unescape(m.group(2).strip())
        if pid in seen or len(name) < 2:
            continue
        seen.add(pid)
        players.append({"tm_id": pid, "name": name})
    return players


def get_match_lineup(match_id: str, nation_tm_id: int) -> dict:
    """
    Scrape la feuille de match TM et renvoie uniquement les joueurs
    de l'équipe nationale (identifiée par nation_tm_id).

    Structure TM de la page aufstellung :
      Header :
        <div class="sb-team sb-heim"> verein/{home_id} → équipe domicile
        <div class="sb-team sb-gast"> verein/{away_id} → équipe extérieur
      Lineup sections (dans l'ordre home → away) :
        <div class="large-6 columns"> → home lineup
        <div class="large-6 columns"> → away lineup
    """
    url = f"https://www.transfermarkt.fr/x/aufstellung/spielbericht/{match_id}"
    html = _fetch(url)
    if not html:
        return {"players": []}

    tid_str = str(nation_tm_id)
    verein_ref = f"verein/{tid_str}"

    # Find the two lineup section positions
    large6_positions = [m.start() for m in re.finditer(r'class="large-6 columns"', html)]

    # TM match sheet structure (4 large-6 blocks):
    #   [0] home starters    [1] away starters
    #   [2] home bench/subs  [3] away bench/subs
    if len(large6_positions) >= 4:
        l0, l1, l2, l3 = (large6_positions[i] for i in range(4))
        l4 = large6_positions[4] if len(large6_positions) >= 5 else len(html)

        # Determine home/away via the header section
        header = html[:l0]
        heim_pos = header.find('class="sb-team sb-heim"')
        gast_pos = header.find('class="sb-team sb-gast"')

        is_home = False
        if heim_pos >= 0 and gast_pos >= 0:
            heim_section = header[heim_pos:gast_pos]
            is_home = verein_ref in heim_section
        else:
            # Fallback: nation ID in first starter block → home
            is_home = verein_ref in html[l0:l1]

        if is_home:
            # Blocks 0 (starters) + 2 (bench)
            block = html[l0:l1] + html[l2:l3]
        else:
            # Blocks 1 (starters) + 3 (bench)
            block = html[l1:l2] + html[l3:l4]

    elif len(large6_positions) >= 2:
        # Simplified 2-block layout
        home_start, away_start = large6_positions[0], large6_positions[1]
        away_end = large6_positions[2] if len(large6_positions) >= 3 else len(html)
        header = html[:home_start]
        heim_pos = header.find('class="sb-team sb-heim"')
        gast_pos = header.find('class="sb-team sb-gast"')
        is_home = (
            verein_ref in header[heim_pos:gast_pos]
            if heim_pos >= 0 and gast_pos >= 0
            else verein_ref in html[:away_start]
        )
        block = html[home_start:away_start] if is_home else html[away_start:away_end]

    else:
        # Last resort: use full page
        block = html

    players = _parse_player_block(block)
    return {"players": players}


# ─────────────────────────────────────────────
# Step 3 : scraper le profil d'un joueur
# ─────────────────────────────────────────────

_CLUB_BLACKLIST_IDS = {
    # IDs TM des 48 sélections nationales CM 2026 — à exclure du club du joueur
    # UEFA
    3377, 3375, 3262, 3299, 3300, 3379, 3382, 3556, 3383, 3384,
    3440, 3557, 3445, 3381, 3380, 3446,
    # CONMEBOL
    3437, 3439, 3816, 3449, 5750, 3581,
    # CONCACAF
    3505, 6303, 3510, 3577, 32364, 14161,
    # AFC
    3435, 3589, 3582, 3807, 3433, 14162, 3560, 15737, 3563,
    # CAF
    3575, 3499, 3672, 3614, 3670, 3591, 3441, 3854, 3806, 4311,
    # OFC
    9171,
}


def get_player_profile(player_tm_id: str) -> dict:
    """
    Scrape le profil TM d'un joueur.
    Renvoie {"name", "club", "club_tm_id", "market_value_eur", "position"}.
    """
    url = f"https://www.transfermarkt.fr/x/profil/spieler/{player_tm_id}"
    html = _fetch(url)
    if not html:
        return {}

    result: dict = {}

    # Nom complet (depuis le titre de page) — supprimer le suffixe " - Profil du joueur …"
    title_m = re.search(r"<title>([^<|]+)", html)
    if title_m:
        raw_name = unescape(title_m.group(1).strip())
        # Strip TM page title suffix e.g. " - Profil du joueur 25/26" or " - Spielerprofil"
        raw_name = re.sub(r'\s*[-–]\s*(Profil du joueur|Spielerprofil|Player profile).*$', '', raw_name, flags=re.IGNORECASE)
        result["name"] = raw_name.strip()

    # Position
    pos_m = re.search(
        r'class="[^"]*detail-position[^"]*"[^>]*>\s*([^<]+)\s*<', html
    )
    if pos_m:
        result["position"] = unescape(pos_m.group(1).strip())

    # Club actuel : chercher les liens /startseite/verein/{id} ou /profil/verein/{id}
    club_matches = re.findall(
        r'href="/[^/]+/(?:startseite|profil)/verein/(\d+)[^"]*"[^>]*>\s*([^<]+)\s*</(?:a|span)>',
        html,
    )
    for club_id_str, club_name in club_matches:
        cid = int(club_id_str)
        club_name = unescape(club_name.strip())
        if cid not in _CLUB_BLACKLIST_IDS and len(club_name) > 2 and club_name.lower() not in ("verein",):
            result["club"] = club_name
            result["club_tm_id"] = club_id_str
            break

    # Valeur marchande
    mv_m = re.search(r"(\d+[,.]?\d*)\s*(?:mio\.|Mio\.)\s*€", html, re.IGNORECASE)
    if mv_m:
        raw = mv_m.group(1).replace(",", ".")
        try:
            result["market_value_eur"] = int(float(raw) * 1_000_000)
        except ValueError:
            pass
    else:
        # Valeur en milliers (k)
        mv_k = re.search(r"(\d+)\s*(?:000\s*€|k\s*€)", html, re.IGNORECASE)
        if mv_k:
            try:
                result["market_value_eur"] = int(mv_k.group(1)) * 1000
            except ValueError:
                pass

    return result


# ─────────────────────────────────────────────
# Pipeline complet : construire l'effectif
# ─────────────────────────────────────────────

def build_squad(nation: dict, n_matches: int = 5,
                progress_callback=None) -> list[dict]:
    """
    Construit l'effectif d'une nation à partir de ses n derniers matchs.
    Retourne une liste de joueurs dédupliqués avec club + valeur marchande.
    `progress_callback(step, total, msg)` si fourni.
    """
    slug = nation["slug"]
    tm_id = nation["tm_id"]
    fr_name = nation["fr"]

    if not tm_id:
        return []

    def _cb(step, total, msg):
        if progress_callback:
            progress_callback(step, total, msg)

    _cb(0, 100, f"Recherche des matchs de {fr_name}…")

    match_ids = get_recent_match_ids(slug, tm_id, n=n_matches)
    if not match_ids:
        return []

    # Collect players across all matches
    player_appearances: dict[str, int] = {}   # tm_id → nb of appearances
    player_names: dict[str, str] = {}

    total_steps = len(match_ids) + 1
    for i, mid in enumerate(match_ids):
        _cb(int((i + 1) / total_steps * 50), 100,
            f"Match {i+1}/{len(match_ids)} — feuille de match…")
        time.sleep(REQUEST_DELAY)
        lineup = get_match_lineup(mid, tm_id)
        for p in lineup.get("players", []):
            pid = p["tm_id"]
            player_appearances[pid] = player_appearances.get(pid, 0) + 1
            player_names[pid] = p["name"]

    if not player_appearances:
        return []

    # Enrich with club + market value — tous les joueurs ayant au moins 1 apparition
    sorted_players = sorted(
        player_appearances.items(), key=lambda x: -x[1]
    )

    squad = []
    for idx, (pid, appearances) in enumerate(sorted_players):
        _cb(
            50 + int(idx / len(sorted_players) * 50), 100,
            f"Profil joueur {idx+1}/{len(sorted_players)}…",
        )
        time.sleep(REQUEST_DELAY)
        profile = get_player_profile(pid)
        squad.append(
            {
                "tm_id": pid,
                "name": profile.get("name", player_names.get(pid, "?")),
                "position": profile.get("position", ""),
                "club": profile.get("club", ""),
                "club_tm_id": profile.get("club_tm_id", ""),
                "market_value_eur": profile.get("market_value_eur", 0),
                "appearances": appearances,
            }
        )

    return squad


# ─────────────────────────────────────────────
# Interface publique avec cache
# ─────────────────────────────────────────────

def get_squad_cached(nation: dict, force_refresh: bool = False,
                     progress_callback=None) -> list[dict]:
    """
    Renvoie l'effectif depuis le cache ou le scrape si nécessaire.
    """
    code = nation["code"]
    cache = _load_cache()
    entry = cache.get(code, {})

    if not force_refresh and entry and _is_cache_valid(entry):
        return entry.get("players", [])

    players = build_squad(nation, progress_callback=progress_callback)

    cache[code] = {
        "fetched_at": datetime.now().isoformat(),
        "players": players,
    }
    _save_cache(cache)
    return players


def get_cache_status() -> dict:
    """Renvoie le statut du cache : {code: {fetched_at, n_players}}."""
    cache = _load_cache()
    status = {}
    for code, entry in cache.items():
        status[code] = {
            "fetched_at": entry.get("fetched_at", ""),
            "n_players": len(entry.get("players", [])),
            "valid": _is_cache_valid(entry),
        }
    return status


def clear_cache_for(code: str):
    """Supprime l'entrée cache d'une nation spécifique."""
    cache = _load_cache()
    cache.pop(code, None)
    _save_cache(cache)


def clear_all_cache():
    """Vide tout le cache."""
    _save_cache({})
