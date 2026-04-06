"""
Collect historical odds from The Odds API for club football backtesting.
Strategy: weekly snapshots through each season, storing Pinnacle + Betclic + Winamax odds.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

API_KEY = os.environ.get("ODDS_API_KEY", "")
BASE = "https://api.the-odds-api.com/v4"

LEAGUES = {
    "soccer_epl": "Premier League",
    "soccer_spain_la_liga": "La Liga",
    "soccer_italy_serie_a": "Serie A",
    "soccer_germany_bundesliga": "Bundesliga",
    "soccer_france_ligue_one": "Ligue 1",
}

BOOKMAKERS = "pinnacle,betclic,winamax"

SEASONS = {
    "2023-24": {
        "start": "2023-08-10",
        "end": "2024-05-30",
    },
    "2024-25": {
        "start": "2024-08-10",
        "end": "2025-05-30",
    },
}

OUTPUT_DIR = Path(__file__).parent / "historical_data"

SNAPSHOT_HOURS = [12, 18]


def _output_path(league: str, season: str) -> Path:
    return OUTPUT_DIR / f"{league}_{season}.json"


def _load_progress(league: str, season: str) -> dict:
    path = _output_path(league, season)
    if path.exists():
        return json.loads(path.read_text())
    return {"league": league, "season": season, "snapshots": [], "matches": {}}


def _save_progress(league: str, season: str, data: dict):
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = _output_path(league, season)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def fetch_snapshot(league: str, date_str: str) -> tuple[dict | None, int]:
    url = f"{BASE}/historical/sports/{league}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
        "date": date_str,
        "bookmakers": BOOKMAKERS,
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                used = int(resp.headers.get("x-requests-used", 0))
                remaining = int(resp.headers.get("x-requests-remaining", 0))
                return data, remaining
            elif resp.status_code == 422:
                return None, -1
            else:
                print(f"  HTTP {resp.status_code}: {resp.text[:200]}")
                return None, -1
    except Exception as e:
        print(f"  Request error: {e}")
        return None, -1


def _extract_match_odds(event: dict) -> dict:
    match_data = {
        "id": event["id"],
        "home": event["home_team"],
        "away": event["away_team"],
        "commence": event["commence_time"],
        "bookmakers": {},
    }

    for bk in event.get("bookmakers", []):
        bk_data = {"key": bk["key"], "title": bk["title"], "updated": bk["last_update"]}
        for mkt in bk.get("markets", []):
            outcomes = {}
            for o in mkt.get("outcomes", []):
                key = o["name"]
                if "point" in o:
                    key = f"{o['name']}_{o['point']}"
                outcomes[key] = o["price"]
            bk_data[mkt["key"]] = outcomes
        match_data["bookmakers"][bk["key"]] = bk_data

    return match_data


def collect_league_season(league: str, season: str, dry_run: bool = False):
    cfg = SEASONS[season]
    start = datetime.fromisoformat(cfg["start"])
    end = datetime.fromisoformat(cfg["end"])

    now = datetime.utcnow()
    if end > now:
        end = now - timedelta(days=1)

    progress = _load_progress(league, season)
    seen_dates = set(progress["snapshots"])

    print(f"\n{'='*60}")
    print(f"League: {LEAGUES[league]} | Season: {season}")
    print(f"Range: {start.date()} → {end.date()}")
    print(f"Already collected: {len(seen_dates)} snapshots, {len(progress['matches'])} matches")

    current = start
    queries = 0
    new_matches = 0

    while current <= end:
        for hour in SNAPSHOT_HOURS:
            dt = current.replace(hour=hour, minute=0, second=0)
            date_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")

            if date_str in seen_dates:
                continue

            if dry_run:
                print(f"  [DRY] Would query: {date_str}")
                queries += 1
                continue

            data, remaining = fetch_snapshot(league, date_str)
            queries += 1

            if data is None:
                continue

            events = data.get("data", [])
            actual_ts = data.get("timestamp", date_str)

            for event in events:
                match_info = _extract_match_odds(event)
                match_id = event["id"]

                if match_id not in progress["matches"]:
                    progress["matches"][match_id] = {
                        "home": match_info["home"],
                        "away": match_info["away"],
                        "commence": match_info["commence"],
                        "odds_snapshots": [],
                    }
                    new_matches += 1

                progress["matches"][match_id]["odds_snapshots"].append({
                    "timestamp": actual_ts,
                    "bookmakers": match_info["bookmakers"],
                })

            progress["snapshots"].append(date_str)
            seen_dates.add(date_str)
            _save_progress(league, season, progress)

            if queries % 10 == 0:
                print(f"  [{queries} queries] {date_str} → {len(events)} events | remaining: {remaining}")

            if remaining >= 0 and remaining < 1000:
                print(f"  ⚠ Low quota: {remaining} remaining. Stopping.")
                return queries, new_matches

            time.sleep(0.3)

        current += timedelta(days=3)

    print(f"  Done: {queries} queries, {new_matches} new matches")
    return queries, new_matches


def collect_all(dry_run: bool = False, leagues: list[str] | None = None, seasons: list[str] | None = None):
    if not API_KEY:
        print("ERROR: ODDS_API_KEY not set")
        return

    target_leagues = leagues or list(LEAGUES.keys())
    target_seasons = seasons or list(SEASONS.keys())

    total_queries = 0
    total_matches = 0

    for season in target_seasons:
        for league in target_leagues:
            q, m = collect_league_season(league, season, dry_run=dry_run)
            total_queries += q
            total_matches += m

    print(f"\n{'='*60}")
    print(f"TOTAL: {total_queries} queries, {total_matches} new matches")


def get_closing_odds(league: str, season: str) -> list[dict]:
    progress = _load_progress(league, season)
    results = []

    for match_id, match in progress["matches"].items():
        if not match["odds_snapshots"]:
            continue

        commence = match["commence"]
        best_snapshot = None
        best_diff = float("inf")

        for snap in match["odds_snapshots"]:
            snap_time = snap["timestamp"]
            try:
                st = datetime.fromisoformat(snap_time.replace("Z", "+00:00"))
                ct = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                diff = (ct - st).total_seconds()
                if 0 < diff < best_diff:
                    best_diff = diff
                    best_snapshot = snap
            except Exception:
                continue

        if not best_snapshot:
            best_snapshot = match["odds_snapshots"][-1]

        closing = {
            "id": match_id,
            "home": match["home"],
            "away": match["away"],
            "commence": commence,
            "snapshot_time": best_snapshot["timestamp"],
            "pinnacle": best_snapshot["bookmakers"].get("pinnacle", {}),
            "betclic": best_snapshot["bookmakers"].get("betclic", {}),
            "winamax": best_snapshot["bookmakers"].get("winamax", {}),
        }
        results.append(closing)

    results.sort(key=lambda x: x["commence"])
    return results


if __name__ == "__main__":
    import sys
    if "--dry-run" in sys.argv:
        collect_all(dry_run=True)
    elif "--closing" in sys.argv:
        for league in LEAGUES:
            for season in SEASONS:
                closing = get_closing_odds(league, season)
                print(f"\n{LEAGUES[league]} {season}: {len(closing)} matches with closing odds")
                for m in closing[:3]:
                    pin = m.get("pinnacle", {}).get("h2h", {})
                    print(f"  {m['home']} vs {m['away']}: Pin={pin}")
    else:
        collect_all()
