"""Builder du cache StatsHub massif pour les joueurs Top 5 + UCL/UEL/UECL.

Usage :
    python live/build_statshub_cache.py --leagues top5 ucl uel
    python live/build_statshub_cache.py --leagues all              # défaut
    python live/build_statshub_cache.py --max-players 50           # smoke test
    python live/build_statshub_cache.py --refresh-all              # force re-resolve

Sortie :
    live/data/statshub_players_index.json     (mapping bsd_id → external_id)
    live/data/statshub_performance/{ext}.json (raw payloads)
    .local/notes/statshub-cache-build-<date>.md (rapport)

Idempotent : skip ce qui est déjà cached et frais (TTL 7j).

Garde-fous :
- Aucun import de predict_today / g2_engine / model 4.1
- Read-only sur les squads JSON, write-only sur le cache
- Échecs silencieux par joueur (compte dans report, n'arrête pas le sweep)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Ensure imports work when run as `python live/build_statshub_cache.py`
ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

import requests  # noqa: E402

from live.statshub_helpers import (  # noqa: E402
    _HEADERS as _SH_HEADERS,
    BASE_URL as _SH_BASE,
    fetch_player_performance,
    find_external_id_for_player,
)

# --- Config -----------------------------------------------------------------

DATA_DIR = ROOT / "data"
INDEX_FILE = DATA_DIR / "statshub_players_index.json"
PERF_DIR = DATA_DIR / "statshub_performance"

DEFAULT_TARGET_LEAGUES = [
    "premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1",
    "champions_league", "europa_league",
    # "conference_league" : squad JSON pas encore téléchargé
]

LEAGUE_GROUPS = {
    "top5": ["premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1"],
    "ucl":  ["champions_league"],
    "uel":  ["europa_league"],
    "uecl": ["conference_league"],
    "all":  DEFAULT_TARGET_LEAGUES,
}

INDEX_TTL = 7 * 86400        # 7 jours
PERF_TTL = 7 * 86400         # 7 jours
WORKERS = 10
WORKERS_PERF = 5         # plus conservatif pour /performance (gros payloads)
MAX_RETRIES = 1
PERF_TIMEOUT = 25        # /performance peut renvoyer 100K+ bytes


# --- Squad loaders ----------------------------------------------------------

def _load_squad_file(slug: str) -> list[dict]:
    """Loads `live/data/<slug>_squads.json` and returns a flat list of player dicts.

    Squad file shape: { "<team_id>": [ {id, name, nationality, current_team:{id,name}, ...}, ... ] }
    Returns: [ {bsd_player_id, name, nationality, team_bsd_id, team_name, league_slug}, ... ]
    """
    fp = DATA_DIR / f"{slug}_squads.json"
    if not fp.exists():
        return []
    try:
        with fp.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        print(f"  ! erreur lecture {fp.name}: {e}")
        return []

    out: list[dict] = []
    if not isinstance(raw, dict):
        return []
    for team_key, players in raw.items():
        if not isinstance(players, list):
            continue
        for p in players:
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            name = p.get("name")
            if not pid or not name:
                continue
            ct = p.get("current_team") or {}
            out.append({
                "bsd_player_id": int(pid),
                "name": name,
                "nationality": p.get("nationality"),
                "team_bsd_id": ct.get("id"),
                "team_name": ct.get("name") or team_key,
                "league_slug": slug,
                "position": p.get("position"),
            })
    return out


def collect_unique_players(league_slugs: list[str]) -> dict[int, dict]:
    """Aggregate squads across leagues, dedup by bsd_player_id.

    A player who appears in multiple leagues (e.g. in Top 5 + UCL) is kept
    once, with `source_squad_league` = first league seen and
    `also_in_leagues` listing the others.
    """
    by_id: dict[int, dict] = {}
    for slug in league_slugs:
        players = _load_squad_file(slug)
        print(f"  · {slug:<22} → {len(players):>4} entries")
        for p in players:
            pid = p["bsd_player_id"]
            if pid in by_id:
                also = by_id[pid].setdefault("also_in_leagues", [])
                if p["league_slug"] not in also and p["league_slug"] != by_id[pid]["league_slug"]:
                    also.append(p["league_slug"])
            else:
                by_id[pid] = dict(p)
                by_id[pid]["source_squad_league"] = p["league_slug"]
    return by_id


# --- Index I/O --------------------------------------------------------------

def _load_index() -> dict[str, dict]:
    if not INDEX_FILE.exists():
        return {}
    try:
        with INDEX_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_index(idx: dict[str, dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(INDEX_FILE.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(INDEX_FILE)


# --- Phase 1 : sweep search → externalId -----------------------------------

def _resolve_one(player: dict) -> tuple[int, dict | None, str | None]:
    """Resolve one player. Returns (bsd_id, index_entry_or_None, error_str)."""
    name = player["name"]
    country = player.get("nationality")
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = find_external_id_for_player(name, country=country)
            if r:
                entry = {
                    "bsd_player_id": player["bsd_player_id"],
                    "bsd_name": name,
                    "bsd_nationality": country,
                    "team_bsd_id": player.get("team_bsd_id"),
                    "team_name": player.get("team_name"),
                    "source_squad_league": player.get("source_squad_league"),
                    "also_in_leagues": player.get("also_in_leagues", []),
                    "position": player.get("position"),
                    "sh_external_id": r.external_id,
                    "sh_internal_id": r.internal_id,
                    "sh_slug": r.slug,
                    "sh_name": r.name,
                    "sh_country_slug": r.country_slug,
                    "resolution_score": round(r.score, 3),
                    "last_resolved_ts": int(time.time()),
                }
                return player["bsd_player_id"], entry, None
            last_err = "no_match"
        except Exception as e:
            last_err = str(e)[:80]
        time.sleep(0.3 * (attempt + 1))
    # No success → record a "miss" entry so we don't retry on next run within TTL
    miss = {
        "bsd_player_id": player["bsd_player_id"],
        "bsd_name": name,
        "bsd_nationality": country,
        "team_bsd_id": player.get("team_bsd_id"),
        "team_name": player.get("team_name"),
        "source_squad_league": player.get("source_squad_league"),
        "also_in_leagues": player.get("also_in_leagues", []),
        "sh_external_id": None,
        "resolution_error": last_err,
        "last_resolved_ts": int(time.time()),
    }
    return player["bsd_player_id"], miss, last_err


def phase1_resolve(players: dict[int, dict], refresh: bool = False,
                   time_budget_s: float | None = None) -> dict[str, dict]:
    """Returns the updated index (str(bsd_id) → entry).

    If `time_budget_s` set, exits gracefully after that wall-clock budget
    (useful when running in time-limited shells).
    """
    idx = _load_index()
    now = int(time.time())

    # Determine which players still need resolution
    todo: list[dict] = []
    for pid, p in players.items():
        existing = idx.get(str(pid))
        if existing and not refresh:
            age = now - int(existing.get("last_resolved_ts", 0))
            if age < INDEX_TTL:
                continue
        todo.append(p)

    print(f"\n[Phase 1] Resolution search → externalId : {len(todo)} à faire (sur {len(players)} total, {len(players)-len(todo)} déjà cached)")
    if not todo:
        return idx

    t0 = time.time()
    n_ok = 0
    n_miss = 0
    n_done = 0
    save_every = 20
    stopped_early = False

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_resolve_one, p): p for p in todo}
        for fut in as_completed(futures):
            try:
                pid, entry, err = fut.result()
            except Exception as e:
                print(f"  !! exception worker: {e}")
                continue
            if entry is not None:
                idx[str(pid)] = entry
                if entry.get("sh_external_id"):
                    n_ok += 1
                else:
                    n_miss += 1
            n_done += 1
            if n_done % 50 == 0:
                eta = (time.time() - t0) / n_done * (len(todo) - n_done)
                print(f"  [{n_done:>4}/{len(todo)}] OK={n_ok} miss={n_miss} | ETA {eta:.0f}s", flush=True)
            if n_done % save_every == 0:
                _save_index(idx)
            if time_budget_s and (time.time() - t0) > time_budget_s:
                stopped_early = True
                print(f"  [time-budget] {time_budget_s}s atteint, sortie propre …", flush=True)
                # Cancel remaining futures (best-effort)
                for f in futures:
                    if not f.done():
                        f.cancel()
                break

    _save_index(idx)
    elapsed = time.time() - t0
    suffix = " (BUDGET ATTEINT, partial)" if stopped_early else ""
    print(f"[Phase 1] {'PARTIAL' if stopped_early else 'FAIT'} en {elapsed:.1f}s → +{n_ok} résolus, +{n_miss} miss, taux={n_ok/max(1,n_done)*100:.1f}%{suffix}")
    return idx


# --- Phase 2 : sweep performance ----------------------------------------

def _fetch_perf_one(external_id: int, name: str) -> tuple[int, bool, str | None]:
    """Fetch performance and dump to disk. Returns (ext_id, success, error).

    Uses a longer timeout (`PERF_TIMEOUT`) than statshub_helpers default
    because /performance payloads can reach 100K+ bytes for top players.
    1 retry on network errors / non-200.
    """
    last_err = None
    url = f"{_SH_BASE}/api/player/{int(external_id)}/performance?limit=200"
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=_SH_HEADERS, timeout=PERF_TIMEOUT)
            if r.status_code != 200:
                last_err = f"http_{r.status_code}"
            elif "json" not in r.headers.get("content-type", ""):
                last_err = "non_json"
            else:
                payload = r.json()
                # Sanity check
                ok = (
                    (isinstance(payload, dict) and (
                        "matches" in payload or "events" in payload
                        or "performance" in payload or "data" in payload
                    ))
                    or (isinstance(payload, list))
                )
                if not ok:
                    last_err = "unrecognized_payload_shape"
                else:
                    PERF_DIR.mkdir(parents=True, exist_ok=True)
                    fp = PERF_DIR / f"{external_id}.json"
                    tmp = fp.with_suffix(".json.tmp")
                    with tmp.open("w", encoding="utf-8") as f:
                        json.dump(payload, f, ensure_ascii=False)
                    tmp.replace(fp)
                    return external_id, True, None
        except requests.exceptions.Timeout:
            last_err = "timeout"
        except Exception as e:
            last_err = str(e)[:80]
        # backoff before retry
        if attempt < MAX_RETRIES:
            time.sleep(1.0 * (attempt + 1))
    return external_id, False, last_err


def phase2_fetch_performance(idx: dict[str, dict], refresh: bool = False,
                              time_budget_s: float | None = None) -> dict[str, Any]:
    """For each resolved external_id, dump /performance to disk if missing or stale."""
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    todo: list[tuple[int, str]] = []

    for entry in idx.values():
        ext_id = entry.get("sh_external_id")
        if not ext_id:
            continue
        fp = PERF_DIR / f"{ext_id}.json"
        if fp.exists() and not refresh:
            age = now - fp.stat().st_mtime
            if age < PERF_TTL:
                continue
        todo.append((ext_id, entry.get("sh_name") or entry.get("bsd_name") or ""))

    total_resolved = sum(1 for e in idx.values() if e.get("sh_external_id"))
    print(f"\n[Phase 2] Fetch /performance : {len(todo)} à faire (sur {total_resolved} résolus, {total_resolved-len(todo)} déjà cached)")
    if not todo:
        return {"fetched": 0, "ok": 0, "fail": 0}

    t0 = time.time()
    n_ok = 0
    n_fail = 0
    n_done = 0
    stopped_early = False

    with ThreadPoolExecutor(max_workers=WORKERS_PERF) as ex:
        futures = {ex.submit(_fetch_perf_one, ext, name): (ext, name) for ext, name in todo}
        for fut in as_completed(futures):
            try:
                ext_id, success, err = fut.result()
            except Exception as e:
                print(f"  !! exception worker: {e}")
                continue
            if success:
                n_ok += 1
            else:
                n_fail += 1
            n_done += 1
            if n_done % 50 == 0:
                eta = (time.time() - t0) / n_done * (len(todo) - n_done)
                print(f"  [{n_done:>4}/{len(todo)}] OK={n_ok} fail={n_fail} | ETA {eta:.0f}s", flush=True)
            if time_budget_s and (time.time() - t0) > time_budget_s:
                stopped_early = True
                print(f"  [time-budget] {time_budget_s}s atteint, sortie propre …", flush=True)
                for f in futures:
                    if not f.done():
                        f.cancel()
                break

    elapsed = time.time() - t0
    suffix = " (BUDGET ATTEINT, partial)" if stopped_early else ""
    print(f"[Phase 2] {'PARTIAL' if stopped_early else 'FAIT'} en {elapsed:.1f}s → ok={n_ok}, fail={n_fail}, taux={n_ok/max(1,n_done)*100:.1f}%{suffix}")
    return {"fetched": n_done, "ok": n_ok, "fail": n_fail, "elapsed_s": elapsed,
            "partial": stopped_early}


# --- Main -------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Build StatsHub cache massif")
    ap.add_argument("--leagues", nargs="+", default=["all"],
                    help="ligues ou groupes (top5/ucl/uel/uecl/all) ou slugs individuels")
    ap.add_argument("--max-players", type=int, default=None,
                    help="Plafond pour smoke test")
    ap.add_argument("--refresh-all", action="store_true",
                    help="Re-resolve même si cache frais (TTL ignored)")
    ap.add_argument("--phase", choices=["1", "2", "both"], default="both",
                    help="1 = search only, 2 = perf only, both = default")
    ap.add_argument("--time-budget", type=float, default=None,
                    help="Wall-clock budget en secondes par phase (sortie propre si dépassé)")
    args = ap.parse_args()

    # Expand groups → unique league slugs
    target_slugs: list[str] = []
    for tok in args.leagues:
        target_slugs.extend(LEAGUE_GROUPS.get(tok, [tok]))
    seen = set()
    target_slugs = [s for s in target_slugs if not (s in seen or seen.add(s))]

    print(f"=== Build StatsHub cache ===")
    print(f"Ligues cibles: {', '.join(target_slugs)}")
    print(f"Refresh-all: {args.refresh_all}")
    print(f"Phase: {args.phase}")
    print(f"\n[Squads] Chargement …")
    players = collect_unique_players(target_slugs)
    print(f"\n→ {len(players)} joueurs uniques (après dédup)")

    if args.max_players:
        players = dict(list(players.items())[:args.max_players])
        print(f"→ tronqué à {len(players)} (smoke test)")

    if args.phase in ("1", "both"):
        idx = phase1_resolve(players, refresh=args.refresh_all,
                             time_budget_s=args.time_budget)
    else:
        idx = _load_index()

    if args.phase in ("2", "both"):
        phase2_fetch_performance(idx, refresh=args.refresh_all,
                                 time_budget_s=args.time_budget)

    # Final summary
    final_idx = _load_index()
    n_total = len(final_idx)
    n_resolved = sum(1 for e in final_idx.values() if e.get("sh_external_id"))
    n_perf = sum(1 for _ in PERF_DIR.glob("*.json")) if PERF_DIR.exists() else 0
    print(f"\n=== Cache final ===")
    print(f"Index entries: {n_total} ({n_resolved} résolus, {n_total-n_resolved} miss)")
    print(f"Performance files on disk: {n_perf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
