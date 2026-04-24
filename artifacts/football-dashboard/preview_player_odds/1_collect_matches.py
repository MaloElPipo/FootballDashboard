"""
Étape A — Collecte tous les matchs Bundesliga 2025/26 avec odds + xG réels + lineups.
Utilise REST direct (9x plus rapide que MCP), parallélisé.
Output: data/bundesliga_matches.json
"""
import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BSD_BASE = "https://sports.bzzoiro.com/api"
HEADERS = {"Authorization": f"Token {os.environ['BSD_API_KEY']}"}
BUNDESLIGA_ID = 5
SEASON_START = "2025-08-01"
SEASON_END = "2026-04-30"

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def fetch_event_list():
    all_events = []
    offset = 0
    while True:
        r = requests.get(f"{BSD_BASE}/events/", params={
            "league": BUNDESLIGA_ID,
            "date_from": SEASON_START,
            "date_to": SEASON_END,
            "limit": 50,
            "offset": offset,
        }, headers=HEADERS, timeout=30)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        all_events.extend(results)
        if len(all_events) >= data.get("count", 0):
            break
        offset += 50
    return all_events


def fetch_event_detail(event_id):
    """Récupère tout pour un event: odds + xG réels + lineups + form + h2h."""
    try:
        r = requests.get(f"{BSD_BASE}/events/{event_id}/", headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return {"id": event_id, "error": f"HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        return {"id": event_id, "error": str(e)}


def main():
    print("=" * 60)
    print("Étape A — Collecte matchs Bundesliga 2025/26")
    print("=" * 60)

    t0 = time.time()
    print("\n[1/2] Liste des matchs...")
    events = fetch_event_list()
    finished = [e for e in events if e.get("status") == "finished"]
    print(f"  Total events: {len(events)} ({len(finished)} terminés)")

    print(f"\n[2/2] Détails (odds + xG + lineups) en parallèle x16...")
    details = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(fetch_event_detail, e["id"]): e["id"] for e in finished}
        done = 0
        for fut in as_completed(futures):
            res = fut.result()
            details[res["id"]] = res
            done += 1
            if done % 30 == 0:
                print(f"  {done}/{len(finished)}...")

    out = {
        "league": "Bundesliga",
        "season": "2025/26",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_events": len(events),
        "n_finished": len(finished),
        "events": details,
    }
    out_path = DATA_DIR / "bundesliga_matches.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n✅ Sauvegardé: {out_path} ({size_mb:.1f} MB)")
    print(f"⏱️ Temps total: {time.time() - t0:.1f}s")

    # Quick sanity check
    sample = next(iter(details.values()))
    print(f"\n--- Sanity check (event {sample.get('id')}) ---")
    print(f"  Match: {sample.get('home_team')} {sample.get('home_score')}-{sample.get('away_score')} {sample.get('away_team')}")
    print(f"  Odds 1X2: {sample.get('odds_home')}/{sample.get('odds_draw')}/{sample.get('odds_away')}")
    print(f"  Odds O2.5/U2.5: {sample.get('odds_over_25')}/{sample.get('odds_under_25')}")
    print(f"  xG réels: {sample.get('actual_home_xg')}/{sample.get('actual_away_xg')}")
    print(f"  Lineups dispo: {bool(sample.get('lineups'))}")


if __name__ == "__main__":
    main()
