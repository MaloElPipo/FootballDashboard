"""
Étape B — Collecte stats par joueur par match Bundesliga 2025/26.
Approche: 1 appel /player-stats/?event=X par match (vs des centaines par joueur).
Output: data/bundesliga_player_stats.json
"""
import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BSD_BASE = "https://sports.bzzoiro.com/api"
HEADERS = {"Authorization": f"Token {os.environ['BSD_API_KEY']}"}

DATA_DIR = Path(__file__).parent / "data"
MATCHES_FILE = DATA_DIR / "bundesliga_matches.json"
OUT_FILE = DATA_DIR / "bundesliga_player_stats.json"


def fetch_player_stats_for_event(event_id):
    """Récupère toutes les player stats pour un event via pagination."""
    all_rows = []
    offset = 0
    while True:
        try:
            r = requests.get(f"{BSD_BASE}/player-stats/", params={
                "event": event_id, "limit": 50, "offset": offset
            }, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                return {"event_id": event_id, "error": f"HTTP {r.status_code}", "stats": all_rows}
            data = r.json()
            results = data.get("results", [])
            if not results:
                break
            all_rows.extend(results)
            if len(all_rows) >= data.get("count", 0):
                break
            offset += 50
            if offset > 200:  # safety: max 200 stats par event
                break
        except Exception as e:
            return {"event_id": event_id, "error": str(e), "stats": all_rows}
    return {"event_id": event_id, "stats": all_rows}


def main():
    print("=" * 60)
    print("Étape B — Stats par joueur par match Bundesliga")
    print("=" * 60)

    if not MATCHES_FILE.exists():
        raise SystemExit("⚠️ Lance d'abord 1_collect_matches.py")

    matches = json.loads(MATCHES_FILE.read_text())
    finished_ids = list(matches["events"].keys())
    print(f"\nMatchs à traiter: {len(finished_ids)}")

    t0 = time.time()
    by_event = {}
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(fetch_player_stats_for_event, int(eid)): eid for eid in finished_ids}
        done = 0
        for fut in as_completed(futures):
            res = fut.result()
            by_event[str(res["event_id"])] = res
            done += 1
            if done % 30 == 0:
                print(f"  {done}/{len(finished_ids)}...")

    # Stats brutes
    total_rows = sum(len(e.get("stats", [])) for e in by_event.values())
    errors = sum(1 for e in by_event.values() if "error" in e)
    print(f"\n  Total lignes stats: {total_rows}")
    print(f"  Erreurs: {errors}")

    out = {
        "league": "Bundesliga",
        "season": "2025/26",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_events": len(by_event),
        "n_rows": total_rows,
        "by_event": by_event,
    }
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False))
    size_mb = OUT_FILE.stat().st_size / 1024 / 1024
    print(f"\n✅ Sauvegardé: {OUT_FILE} ({size_mb:.1f} MB)")
    print(f"⏱️ Temps total: {time.time() - t0:.1f}s")

    # Sanity check: 1 match
    sample_eid = finished_ids[0]
    sample = by_event[sample_eid]["stats"][:3]
    print(f"\n--- Sanity check (event {sample_eid}, 3 premiers joueurs) ---")
    for s in sample:
        p = s.get("player", {}) if isinstance(s.get("player"), dict) else {"id": s.get("player")}
        pname = p.get("name", f"id={p.get('id')}")
        print(f"  {pname}: min={s.get('minutes_played')}', xG={s.get('expected_goals')}, "
              f"xA={s.get('expected_assists')}, shots={s.get('total_shots')}, "
              f"key_pass={s.get('key_pass')}, goals={s.get('goals')}, assists={s.get('goal_assist')}")


if __name__ == "__main__":
    main()
