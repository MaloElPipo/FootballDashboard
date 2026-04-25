"""Cache des stats carrière joueurs (Understat archive + BSD saison courante).

Sources :
- Understat (`https://understat.com/main/getPlayersStats/`) pour les saisons N-1 à N-4
  des Top 5 ligues européennes (EPL, La Liga, Serie A, Bundesliga, Ligue 1). Ne dépend
  pas de BSD pour l'archive (BSD ne fournit pas de player-stats pour les saisons closes).
- BSD pour la saison en cours (déjà géré par `predict_today.py`/`enrich_results.py`).
  L'increment journalier est stocké dans `current_season_increment` du cache.

Le cache est un fichier JSON `live/data/career_stats_cache.json`. Pour chaque joueur :
{
  "name": "Mohamed Salah",
  "team_hint": "Liverpool",
  "position": "F M",
  "by_season": {
    "EPL/2024": {"games": 38, "minutes": 3392, "goals": 29, "xG": 27.7, ...},
    "EPL/2023": {...},
    ...
  },
  "current_season_increment": {"minutes": 0.0, "goals": 0.0, "xG": 0.0, "assists": 0.0, "xA": 0.0, "events_seen": []},
  "career": {  # somme by_season + current_season_increment
    "minutes": 12500.0, "matches": 145, "goals": 105, "assists": 78,
    "xG": 92.3, "xA": 68.4,
    "seasons_covered": ["EPL/2024", "EPL/2023", ...]
  }
}

Lookup BSD → Understat se fait par nom normalisé (sans accents, lowercase). Index
`name_index` maintenu dans le cache pour O(1).
"""
from __future__ import annotations

import json
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

DATA_DIR = Path(__file__).parent / "data"
CACHE_PATH = DATA_DIR / "career_stats_cache.json"

UNDERSTAT_BASE = "https://understat.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"

# Mapping ligue BSD → Understat
LEAGUE_MAP_BSD_TO_UNDERSTAT = {
    "premier_league": "EPL",
    "la_liga":        "La_liga",
    "serie_a":        "Serie_A",
    "bundesliga":     "Bundesliga",
    "ligue_1":        "Ligue_1",
}

ALL_UNDERSTAT_LEAGUES = list(LEAGUE_MAP_BSD_TO_UNDERSTAT.values())

# Champ utilisé pour cumul carrière côté T003
CAREER_NUMERIC_FIELDS = ("minutes", "goals", "assists", "xG", "xA", "matches")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers nom
# ─────────────────────────────────────────────────────────────────────────────

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_name(s: str) -> str:
    """Normalisation pour matching BSD ↔ Understat: lowercase, sans accents,
    espaces collapsés, ponctuation de base supprimée."""
    if not s:
        return ""
    s = _strip_accents(str(s)).lower()
    # Remplace . , ' - par espaces
    for ch in (".", ",", "'", "-", "_"):
        s = s.replace(ch, " ")
    return " ".join(s.split())


# ─────────────────────────────────────────────────────────────────────────────
# Fetch Understat
# ─────────────────────────────────────────────────────────────────────────────

def _understat_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": UA})
    # Warm up cookies — Understat pose un PHPSESSID/UID requis pour AJAX
    session.get(f"{UNDERSTAT_BASE}/", timeout=30)
    return session


def fetch_understat_season(league: str, season: str | int,
                           session: requests.Session | None = None) -> list[dict]:
    """Récupère les stats agrégées de tous les joueurs d'une (ligue, saison).

    `season` est l'année de début (2024 → saison 24/25). Renvoie liste de dicts
    avec champs Understat : id, player_name, team_title, games, time, goals, xG,
    assists, xA, npg, npxG, position, etc.
    """
    sess = session or _understat_session()
    url = f"{UNDERSTAT_BASE}/main/getPlayersStats/"
    headers = {
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    r = sess.post(url, data={"league": league, "season": str(season)},
                  headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        return []
    return data.get("players", [])


def _coerce_season_row(row: dict) -> dict:
    """Convertit une ligne Understat (strings) en dict typé canonique."""
    def _f(k):
        try:
            return float(row.get(k, 0) or 0)
        except (ValueError, TypeError):
            return 0.0
    def _i(k):
        try:
            return int(float(row.get(k, 0) or 0))
        except (ValueError, TypeError):
            return 0
    return {
        "matches": _i("games"),
        "minutes": _f("time"),
        "goals":   _f("goals"),
        "xG":      _f("xG"),
        "npg":     _f("npg"),
        "npxG":    _f("npxG"),
        "assists": _f("assists"),
        "xA":      _f("xA"),
        "shots":   _f("shots"),
        "key_passes": _f("key_passes"),
        "team":    str(row.get("team_title", "")),
        "position": str(row.get("position", "")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Build cache
# ─────────────────────────────────────────────────────────────────────────────

def build_career_cache(n_seasons: int = 4,
                       leagues: list[str] | None = None,
                       write_path: Path | None = CACHE_PATH,
                       verbose: bool = True) -> dict:
    """Crawl Understat pour les `n_seasons` saisons précédentes (N-1..N-n_seasons)
    et construit le cache. Ne crawl PAS la saison courante (BSD s'en charge).

    Note : utilise la date système pour déterminer la saison courante. Convention
    Understat : year=2024 ↔ saison 2024/2025. Saison courante = année dernière
    si on est entre janvier-juin (saison commencée en juillet de l'année d'avant).
    """
    today = datetime.now(timezone.utc)
    current_starting_year = today.year if today.month >= 7 else today.year - 1
    seasons_to_crawl = [str(current_starting_year - i) for i in range(1, n_seasons + 1)]
    leagues_to_crawl = leagues or ALL_UNDERSTAT_LEAGUES

    if verbose:
        print(f"Build career cache : {len(leagues_to_crawl)} leagues × {len(seasons_to_crawl)} seasons "
              f"= {len(leagues_to_crawl) * len(seasons_to_crawl)} pages")
        print(f"Seasons : {seasons_to_crawl}")

    sess = _understat_session()
    # by_pid[pid] = { name, team_hint, position, by_season: { "EPL/2024": {...}, ... } }
    by_pid: dict[str, dict] = {}
    coverage: dict[str, dict] = defaultdict(dict)

    t_start = time.time()
    for lg in leagues_to_crawl:
        for season in seasons_to_crawl:
            t0 = time.time()
            try:
                rows = fetch_understat_season(lg, season, session=sess)
            except Exception as e:
                if verbose:
                    print(f"  [{lg}/{season}] FAIL: {e}")
                continue
            elapsed = time.time() - t0
            coverage[lg][season] = len(rows)
            if verbose:
                print(f"  [{lg}/{season}] {len(rows):4d} players in {elapsed:.2f}s")

            key_season = f"{lg}/{season}"
            for row in rows:
                pid = str(row.get("id", "")).strip()
                if not pid:
                    continue
                slot = by_pid.setdefault(pid, {
                    "name": str(row.get("player_name", "")),
                    "team_hint": str(row.get("team_title", "")),
                    "position": str(row.get("position", "")),
                    "by_season": {},
                })
                slot["by_season"][key_season] = _coerce_season_row(row)
                # Garde le team le plus récent (saisons crawled in order N-1, N-2, ...)
                if not slot["team_hint"] and row.get("team_title"):
                    slot["team_hint"] = str(row["team_title"])

    t_total = time.time() - t_start

    # Compute career totals + name_index (multi-map pour gérer collisions)
    name_index: dict[str, list[str]] = {}
    for pid, slot in by_pid.items():
        career = {f: 0.0 for f in CAREER_NUMERIC_FIELDS}
        seasons_covered = []
        for season_key, season_data in slot["by_season"].items():
            for f in CAREER_NUMERIC_FIELDS:
                career[f] += float(season_data.get(f, 0) or 0)
            seasons_covered.append(season_key)
        career["seasons_covered"] = sorted(seasons_covered, reverse=True)
        slot["career_archive"] = career
        # Init increment vide
        slot["current_season_increment"] = {f: 0.0 for f in CAREER_NUMERIC_FIELDS}
        slot["current_season_increment"]["events_seen"] = []
        # Cache total = archive + current (init = archive)
        slot["career"] = dict(career)
        # Index par nom (multi-map : un nom peut être partagé : Sergio García, Ricardo, etc.)
        norm = normalize_name(slot["name"])
        if norm:
            name_index.setdefault(norm, []).append(pid)

    cache = {
        "$updated_at": today.isoformat(),
        "$build_seconds": round(t_total, 2),
        "$coverage": dict(coverage),
        "$source": "understat-archive",
        "players": by_pid,
        "name_index": name_index,
    }

    if write_path:
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
        if verbose:
            print(f"\nWrote {len(by_pid)} players to {write_path} ({write_path.stat().st_size // 1024} KB)")
            print(f"Total build time: {t_total:.1f}s")

    return cache


# ─────────────────────────────────────────────────────────────────────────────
# Load + lookup
# ─────────────────────────────────────────────────────────────────────────────

def load_career_cache(path: Path | None = CACHE_PATH) -> dict | None:
    """Charge le cache, retourne None s'il n'existe pas."""
    p = path or CACHE_PATH
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _pick_best_slot(cache: dict, pids: list, team_hint: Optional[str] = None) -> dict | None:
    """Parmi plusieurs candidats, choisit le meilleur slot.
    1) Si team_hint matche le team_hint d'un slot → ce slot.
    2) Sinon → slot avec le plus de minutes carrière (le joueur le plus probable).
    """
    if not pids:
        return None
    players = cache.get("players", {})
    slots = [players.get(p) for p in pids if players.get(p)]
    slots = [s for s in slots if s]
    if not slots:
        return None
    if team_hint:
        th_norm = normalize_name(team_hint)
        for s in slots:
            if normalize_name(s.get("team_hint", "")) == th_norm:
                return s
    # Fallback : celui qui a le plus de minutes carrière (le plus famous des homonymes)
    return max(slots, key=lambda s: float((s.get("career") or {}).get("minutes", 0) or 0))


def lookup_career(cache: dict, player_name: str, team_hint: Optional[str] = None) -> dict | None:
    """Retourne le slot career d'un joueur ou None si introuvable.

    Stratégie :
      1) match exact via name_index normalisé (multi-map → désambiguation
         par team_hint si plusieurs candidats, sinon le plus famous).
      2) match partiel par nom de famille (rare).
    """
    if not cache or not player_name:
        return None
    name_index: dict = cache.get("name_index", {})
    norm = normalize_name(player_name)

    # Path 1 : match exact (peut être 1 ou plusieurs pids)
    raw = name_index.get(norm)
    if raw is not None:
        pids = raw if isinstance(raw, list) else [raw]  # rétro-compat ancien format
        slot = _pick_best_slot(cache, pids, team_hint=team_hint)
        if slot:
            return slot

    # Path 2 : match partiel (last name only)
    parts = norm.split()
    if len(parts) >= 2:
        last = parts[-1]
        candidate_pids: list = []
        for k, v in name_index.items():
            if k.endswith(" " + last):
                candidate_pids.extend(v if isinstance(v, list) else [v])
        if candidate_pids:
            return _pick_best_slot(cache, candidate_pids, team_hint=team_hint)
    return None


def enrich_pool_with_career(pool: dict, cache: dict | None,
                            team_id_to_name: dict | None = None,
                            verbose: bool = False) -> tuple[int, int]:
    """Pour chaque joueur du pool, injecte les champs `career_minutes`,
    `career_goals`, `career_assists`, `career_xg`, `career_xa`, `career_matches`,
    `career_seasons_covered` (liste). Si pas trouvé : champs absents.

    `team_id_to_name` (optionnel) : map int→str pour résoudre `team_name` à
    partir de `team_id` du pool — sert à désambiguer les homonymes.

    Retourne (matched, total).
    """
    if not cache:
        return 0, len(pool)
    tmap = team_id_to_name or {}
    matched = 0
    for pid, player in pool.items():
        if not isinstance(player, dict):
            continue
        # team_hint : team_name si présent, sinon résolu via team_id
        team_hint = player.get("team_name")
        if not team_hint:
            tid = player.get("team_id")
            if tid is not None:
                team_hint = tmap.get(int(tid)) or tmap.get(str(tid))
        slot = lookup_career(cache, player.get("name", ""), team_hint)
        if not slot:
            continue
        career = slot.get("career", {})
        if (career.get("minutes", 0) or 0) <= 0:
            continue
        player["career_minutes"]  = float(career.get("minutes", 0))
        player["career_goals"]    = float(career.get("goals", 0))
        player["career_assists"]  = float(career.get("assists", 0))
        player["career_xg"]       = float(career.get("xG", 0))
        player["career_xa"]       = float(career.get("xA", 0))
        player["career_matches"]  = float(career.get("matches", 0))
        player["career_seasons_covered"] = career.get("seasons_covered", [])
        matched += 1
    if verbose:
        print(f"enrich_pool_with_career: {matched}/{len(pool)} matched")
    return matched, len(pool)


# ─────────────────────────────────────────────────────────────────────────────
# Update incremental — appelé par enrich_results.py après chaque match terminé
# ─────────────────────────────────────────────────────────────────────────────

def apply_event_increment(cache: dict, event_id: int,
                          player_stats: list[dict], verbose: bool = False) -> int:
    """Pour chaque player_stats row d'un match terminé (BSD format), incrémente
    `current_season_increment` du joueur dans le cache. Idempotent par event_id
    (skip si déjà dans `events_seen`).

    Retourne le nombre de joueurs mis à jour.
    """
    if not cache or not player_stats:
        return 0
    name_index: dict = cache.get("name_index", {})
    players: dict = cache.get("players", {})
    eid = int(event_id)
    n_updated = 0

    for s in player_stats:
        # BSD nested player.name
        p = s.get("player") or {}
        pname = p.get("name") if isinstance(p, dict) else None
        if not pname:
            continue
        norm = normalize_name(pname)
        pid = name_index.get(norm)
        if not pid:
            continue
        slot = players.get(pid)
        if not slot:
            continue
        inc = slot.setdefault("current_season_increment", {f: 0.0 for f in CAREER_NUMERIC_FIELDS})
        events_seen = inc.setdefault("events_seen", [])
        if eid in events_seen:
            continue  # idempotent

        mins = float(s.get("minutes_played") or 0)
        if mins <= 0:
            events_seen.append(eid)
            continue

        inc["minutes"] = float(inc.get("minutes", 0)) + mins
        inc["matches"] = float(inc.get("matches", 0)) + 1
        inc["goals"]   = float(inc.get("goals", 0))   + float(s.get("goals") or 0)
        inc["assists"] = float(inc.get("assists", 0)) + float(s.get("goal_assist") or 0)
        inc["xG"]      = float(inc.get("xG", 0))      + float(s.get("expected_goals") or 0)
        inc["xA"]      = float(inc.get("xA", 0))      + float(s.get("expected_assists") or 0)
        events_seen.append(eid)

        # Re-compute career = archive + increment
        archive = slot.get("career_archive", {})
        slot["career"] = {
            f: float(archive.get(f, 0) or 0) + float(inc.get(f, 0) or 0)
            for f in CAREER_NUMERIC_FIELDS
        }
        slot["career"]["seasons_covered"] = list(archive.get("seasons_covered", [])) + ["BSD/current"]
        n_updated += 1

    if verbose:
        print(f"apply_event_increment(event={eid}): {n_updated} players updated")
    return n_updated


def save_cache(cache: dict, path: Path | None = CACHE_PATH) -> None:
    p = path or CACHE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    cache["$updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _cli():
    import sys
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage:")
        print("  python -m live.career_stats build [--n-seasons N] [--leagues EPL,Serie_A,...]")
        print("  python -m live.career_stats lookup <player_name>")
        print("  python -m live.career_stats stats")
        return

    if args[0] == "build":
        n_seasons = 4
        leagues = None
        i = 1
        while i < len(args):
            if args[i] == "--n-seasons":
                n_seasons = int(args[i + 1]); i += 2
            elif args[i] == "--leagues":
                leagues = args[i + 1].split(","); i += 2
            else:
                i += 1
        build_career_cache(n_seasons=n_seasons, leagues=leagues, verbose=True)

    elif args[0] == "lookup":
        name = " ".join(args[1:])
        cache = load_career_cache()
        if not cache:
            print("No cache. Run `python -m live.career_stats build` first.")
            return
        slot = lookup_career(cache, name)
        if not slot:
            print(f"NOT FOUND: {name}")
            return
        print(f"Name: {slot['name']} (team_hint={slot.get('team_hint')})")
        print(f"Position: {slot.get('position')}")
        c = slot.get("career", {})
        print(f"Career: minutes={c.get('minutes')} matches={c.get('matches')} goals={c.get('goals')} "
              f"assists={c.get('assists')} xG={c.get('xG'):.2f} xA={c.get('xA'):.2f}")
        print(f"Seasons covered: {c.get('seasons_covered')}")
        print(f"\nBy season:")
        for k, v in sorted(slot.get("by_season", {}).items(), reverse=True):
            print(f"  {k}: g={v['matches']:2d} min={v['minutes']:.0f} G={v['goals']:.0f} A={v['assists']:.0f} "
                  f"xG={v['xG']:.2f} xA={v['xA']:.2f}")

    elif args[0] == "stats":
        cache = load_career_cache()
        if not cache:
            print("No cache.")
            return
        print(f"Cache built at: {cache.get('$updated_at')}")
        print(f"Build duration: {cache.get('$build_seconds')}s")
        print(f"Source: {cache.get('$source')}")
        print(f"Players cached: {len(cache.get('players', {}))}")
        print(f"\nCoverage:")
        for lg, seasons in cache.get("$coverage", {}).items():
            for s, n in sorted(seasons.items(), reverse=True):
                print(f"  {lg}/{s}: {n} players")


if __name__ == "__main__":
    _cli()
