import os
import json
import time
import threading
import logging
from datetime import datetime, timezone

import schedule

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bsd_cache")

CACHE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(CACHE_DIR, "bsd_data_cache.json")
LOCK = threading.Lock()

MAX_CACHE_AGE_HOURS = 26


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data: dict):
    with LOCK:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False)


def cache_age_hours() -> float:
    cache = load_cache()
    ts = cache.get("updated_at")
    if not ts:
        return 999
    try:
        updated = datetime.fromisoformat(ts)
        now = datetime.now(timezone.utc)
        return (now - updated).total_seconds() / 3600
    except Exception:
        return 999


def is_cache_fresh() -> bool:
    return cache_age_hours() < MAX_CACHE_AGE_HOURS


def build_full_cache():
    """
    Construit le cache complet :
      1. Joueurs par nationalité (47 nations CM2026)
      2. Matching squad TM → BSD player IDs
      3. Stats agrégées pour chaque joueur matché
    """
    import requests
    import unicodedata

    BASE = "https://sports.bzzoiro.com/api"
    KEY = os.environ.get("BSD_API_KEY", "")
    HEADERS = {"Authorization": f"Token {KEY}"}

    from bsd_api import TM_CODE_TO_BSD_NATIONALITY, _norm

    logger.info("=== Début du build cache BSD ===")
    start = time.time()

    # ── 1. Charger les joueurs par nationalité ────────────────────────────────
    nationality_players = {}
    for code, nat_name in TM_CODE_TO_BSD_NATIONALITY.items():
        all_players = []
        page = 1
        while True:
            try:
                r = requests.get(
                    f"{BASE}/players/",
                    params={"nationality": nat_name, "per_page": 100, "page": page},
                    headers=HEADERS,
                    timeout=15,
                )
                if r.status_code != 200:
                    break
                data = r.json()
                results = data.get("results", [])
                for p in results:
                    all_players.append({
                        "id": p.get("id"),
                        "name": p.get("name", ""),
                        "position": p.get("type", ""),
                        "market_value": p.get("market_value", 0),
                    })
                if not data.get("next"):
                    break
                page += 1
                if page > 15:
                    break
            except Exception:
                break
            time.sleep(0.05)
        nationality_players[code] = all_players
        logger.info(f"  {code} ({nat_name}): {len(all_players)} joueurs")

    logger.info(f"Nationalités chargées: {len(nationality_players)}")

    # ── 2. Matcher squads TM → BSD IDs ────────────────────────────────────────
    squad_file = os.path.join(CACHE_DIR, "squads_static.json")
    try:
        with open(squad_file, "r") as f:
            squads = json.load(f)
    except Exception:
        squads = {}

    def _match_in_list(player_name, candidates):
        target = _norm(player_name)
        parts_t = target.split()
        for p in candidates:
            if _norm(p.get("name", "")) == target:
                return p
        for p in candidates:
            pn = _norm(p.get("name", "")).split()
            if parts_t and pn and parts_t[-1] == pn[-1]:
                if len(parts_t) > 1 and len(pn) > 1 and parts_t[0][0] == pn[0][0]:
                    return p
        for p in candidates:
            pn = _norm(p.get("name", "")).split()
            if parts_t and pn and parts_t[-1] == pn[-1] and len(parts_t[-1]) >= 5:
                return p
        return None

    squad_matches = {}
    all_bsd_ids_to_fetch = set()

    for code in squads:
        nat_pool = nationality_players.get(code, [])
        if not nat_pool:
            continue
        matches = {}
        for p in squads[code].get("players", []):
            name = p.get("name", "")
            bsd_p = _match_in_list(name, nat_pool)
            if bsd_p and bsd_p.get("id"):
                matches[name] = bsd_p["id"]
                all_bsd_ids_to_fetch.add(bsd_p["id"])
        squad_matches[code] = matches

    total_matched = sum(len(v) for v in squad_matches.values())
    logger.info(f"Joueurs matchés: {total_matched} (IDs uniques: {len(all_bsd_ids_to_fetch)})")

    # ── 3. Récupérer les stats agrégées pour chaque joueur ────────────────────
    player_stats = {}
    done = 0
    total = len(all_bsd_ids_to_fetch)

    for pid in all_bsd_ids_to_fetch:
        try:
            r = requests.get(
                f"{BASE}/player-stats/",
                params={"player": pid, "per_page": 100},
                headers=HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                records = r.json().get("results", [])
                if records:
                    def _sum(key):
                        return sum((rec.get(key) or 0) for rec in records)
                    def _avg(key):
                        vals = [rec.get(key) for rec in records if rec.get(key) is not None]
                        return round(sum(vals) / len(vals), 2) if vals else None

                    appearances = sum(1 for rec in records if (rec.get("minutes_played") or 0) > 0)
                    total_mins = _sum("minutes_played")
                    full_90 = sum(1 for rec in records if (rec.get("minutes_played") or 0) >= 90)
                    player_stats[str(pid)] = {
                        "appearances": appearances,
                        "minutes_played": total_mins,
                        "full_90": full_90,
                        "rating": _avg("rating"),
                        "goals": _sum("goals"),
                        "assists": _sum("goal_assist"),
                        "xg": round(sum((rec.get("expected_goals") or 0) for rec in records), 2),
                        "xa": round(sum((rec.get("expected_assists") or 0) for rec in records), 2),
                        "total_shots": _sum("total_shots"),
                        "shots_on_target": _sum("shots_on_target"),
                        "key_passes": _sum("key_pass"),
                        "total_passes": _sum("total_pass"),
                        "accurate_passes": _sum("accurate_pass"),
                        "pass_accuracy": round(_sum("accurate_pass") / max(_sum("total_pass"), 1) * 100, 1),
                        "tackles": _sum("total_tackle"),
                        "interceptions": _sum("interception"),
                        "duels_won": _sum("duel_won"),
                        "duels_lost": _sum("duel_lost"),
                        "duel_pct": round(_sum("duel_won") / max(_sum("duel_won") + _sum("duel_lost"), 1) * 100, 1),
                        "yellow_cards": _sum("yellow_card"),
                        "red_cards": _sum("red_card"),
                        "saves": _sum("saves"),
                        "goals_conceded": _sum("goals_conceded"),
                        "records": len(records),
                    }
        except Exception:
            pass

        done += 1
        if done % 50 == 0:
            logger.info(f"  Stats: {done}/{total} joueurs traités")
        time.sleep(0.03)

    logger.info(f"Stats récupérées: {len(player_stats)} joueurs")

    # ── 4. Sauvegarder le cache ──────────────────────────────────────────────
    cache_data = {
        "updated_at": _now_iso(),
        "nationality_players": nationality_players,
        "squad_matches": squad_matches,
        "player_stats": player_stats,
    }

    save_cache(cache_data)
    elapsed = round(time.time() - start, 1)
    logger.info(f"=== Cache BSD sauvegardé ({elapsed}s) ===")
    logger.info(f"  Fichier: {CACHE_FILE}")
    size_mb = round(os.path.getsize(CACHE_FILE) / 1024 / 1024, 1)
    logger.info(f"  Taille: {size_mb} MB")

    return cache_data


def get_cached_nationality_players(nation_code: str) -> list:
    cache = load_cache()
    return cache.get("nationality_players", {}).get(nation_code, [])


def get_cached_squad_matches(nation_code: str) -> dict:
    cache = load_cache()
    return cache.get("squad_matches", {}).get(nation_code, {})


def get_cached_player_stats(bsd_player_id: int) -> dict:
    cache = load_cache()
    return cache.get("player_stats", {}).get(str(bsd_player_id))


def get_cached_squad_stats(nation_code: str, players_raw: list) -> dict:
    """
    Retourne un dict player_name → stats agrégées depuis le cache.
    Instantané car tout est pré-calculé.
    """
    cache = load_cache()
    squad_map = cache.get("squad_matches", {}).get(nation_code, {})
    all_stats = cache.get("player_stats", {})

    results = {}
    for p in players_raw:
        name = p.get("name", "")
        bsd_id = squad_map.get(name)
        if bsd_id:
            stats = all_stats.get(str(bsd_id))
            if stats:
                stats_copy = dict(stats)
                stats_copy["bsd_id"] = bsd_id
                stats_copy["bsd_name"] = name
                stats_copy["market_value"] = p.get("market_value_eur", 0)
                results[name] = stats_copy
            else:
                results[name] = None
        else:
            results[name] = None
    return results


def cache_summary() -> dict:
    cache = load_cache()
    if not cache:
        return {"exists": False}
    n_nations = len(cache.get("nationality_players", {}))
    n_squads = len(cache.get("squad_matches", {}))
    n_stats = len(cache.get("player_stats", {}))
    return {
        "exists": True,
        "updated_at": cache.get("updated_at", "N/A"),
        "age_hours": round(cache_age_hours(), 1),
        "fresh": is_cache_fresh(),
        "nations": n_nations,
        "squads_matched": n_squads,
        "player_stats": n_stats,
    }


# ── Scheduler (thread daemon) ────────────────────────────────────────────────
_scheduler_started = False

def _scheduler_loop():
    while True:
        schedule.run_pending()
        time.sleep(60)


def start_daily_refresh(hour="05:00"):
    global _scheduler_started
    if _scheduler_started:
        return

    schedule.every().day.at(hour).do(_daily_job)
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="bsd-cache-scheduler")
    t.start()
    _scheduler_started = True
    logger.info(f"Scheduler BSD démarré — rafraîchissement quotidien à {hour} UTC")


def _daily_job():
    logger.info("Lancement du rafraîchissement quotidien du cache BSD...")
    try:
        build_full_cache()
    except Exception as e:
        logger.error(f"Erreur lors du rafraîchissement: {e}")


def ensure_cache_ready():
    """
    Appelé au démarrage de l'app.
    Si le cache est absent ou périmé, lance un build en arrière-plan.
    Démarre aussi le scheduler quotidien.
    """
    start_daily_refresh("05:00")

    if not is_cache_fresh():
        logger.info("Cache BSD absent ou périmé → build en arrière-plan")
        t = threading.Thread(target=build_full_cache, daemon=True, name="bsd-cache-init")
        t.start()
