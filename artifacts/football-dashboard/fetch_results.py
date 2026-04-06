"""
Fetch match results from football-data.co.uk CSV files.
Uses fuzzy team name matching to map CSV names to Odds API names.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "historical_data"

FDUK_URLS = {
    ("soccer_epl", "2023-24"): "https://www.football-data.co.uk/mmz4281/2324/E0.csv",
    ("soccer_epl", "2024-25"): "https://www.football-data.co.uk/mmz4281/2425/E0.csv",
    ("soccer_spain_la_liga", "2023-24"): "https://www.football-data.co.uk/mmz4281/2324/SP1.csv",
    ("soccer_spain_la_liga", "2024-25"): "https://www.football-data.co.uk/mmz4281/2425/SP1.csv",
    ("soccer_italy_serie_a", "2023-24"): "https://www.football-data.co.uk/mmz4281/2324/I1.csv",
    ("soccer_italy_serie_a", "2024-25"): "https://www.football-data.co.uk/mmz4281/2425/I1.csv",
    ("soccer_germany_bundesliga", "2023-24"): "https://www.football-data.co.uk/mmz4281/2324/D1.csv",
    ("soccer_germany_bundesliga", "2024-25"): "https://www.football-data.co.uk/mmz4281/2425/D1.csv",
    ("soccer_france_ligue_one", "2023-24"): "https://www.football-data.co.uk/mmz4281/2324/F1.csv",
    ("soccer_france_ligue_one", "2024-25"): "https://www.football-data.co.uk/mmz4281/2425/F1.csv",
}


def _clean(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokens(name: str) -> set[str]:
    return set(_clean(name).split())


def _fuzzy_match(csv_name: str, api_teams: set[str]) -> str | None:
    csv_clean = _clean(csv_name)

    for api in api_teams:
        if _clean(api) == csv_clean:
            return api

    for api in api_teams:
        if csv_clean in _clean(api) or _clean(api) in csv_clean:
            return api

    csv_tok = _tokens(csv_name)
    best_api = None
    best_score = 0

    for api in api_teams:
        api_tok = _tokens(api)
        common = csv_tok & api_tok
        score = len(common) / max(len(csv_tok), 1)
        if score > best_score:
            best_score = score
            best_api = api

    if best_score >= 0.5:
        return best_api

    csv_first3 = csv_clean[:3]
    for api in api_teams:
        if _clean(api).startswith(csv_first3) or csv_first3 in _clean(api):
            return api

    return None


def fetch_and_match_results(league: str, season: str) -> dict[str, str]:
    url = FDUK_URLS.get((league, season))
    if not url:
        return {}

    hist_path = DATA_DIR / f"{league}_{season}.json"
    if not hist_path.exists():
        return {}

    raw_hist = json.loads(hist_path.read_text())

    api_teams: set[str] = set()
    our_matches: list[dict] = []
    for mid, m in raw_hist.get("matches", {}).items():
        api_teams.add(m["home"])
        api_teams.add(m["away"])
        our_matches.append({"id": mid, "home": m["home"], "away": m["away"], "commence": m["commence"]})

    match_index: dict[str, list[dict]] = {}
    for m in our_matches:
        h = _clean(m["home"])
        a = _clean(m["away"])
        key = f"{h}||{a}"
        match_index.setdefault(key, []).append(m)

    csv_to_api: dict[str, str] = {}

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content = resp.text
    except Exception as e:
        print(f"  Download error: {e}")
        return {}

    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)

    all_csv_teams = set()
    for row in rows:
        all_csv_teams.add(row.get("HomeTeam", "").strip())
        all_csv_teams.add(row.get("AwayTeam", "").strip())

    for csv_team in all_csv_teams:
        if not csv_team:
            continue
        api_name = _fuzzy_match(csv_team, api_teams)
        if api_name:
            csv_to_api[csv_team] = api_name

    results: dict[str, str] = {}
    matched = 0
    unmatched_teams = set()

    for row in rows:
        home_csv = row.get("HomeTeam", "").strip()
        away_csv = row.get("AwayTeam", "").strip()
        ftr = row.get("FTR", "").strip()
        date_str = row.get("Date", "").strip()

        if not home_csv or not away_csv or ftr not in ("H", "D", "A"):
            continue

        home_api = csv_to_api.get(home_csv)
        away_api = csv_to_api.get(away_csv)

        if not home_api or not away_api:
            if not home_api:
                unmatched_teams.add(home_csv)
            if not away_api:
                unmatched_teams.add(away_csv)
            continue

        h_clean = _clean(home_api)
        a_clean = _clean(away_api)
        key = f"{h_clean}||{a_clean}"

        candidates = match_index.get(key, [])

        if not candidates:
            continue

        best = candidates[0]
        if len(candidates) > 1 and date_str:
            csv_date = None
            for fmt in ["%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"]:
                try:
                    csv_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

            if csv_date:
                best_diff = float("inf")
                for c in candidates:
                    try:
                        c_date = datetime.fromisoformat(c["commence"].replace("Z", "+00:00")).replace(tzinfo=None)
                        diff = abs((csv_date - c_date).total_seconds())
                        if diff < best_diff:
                            best_diff = diff
                            best = c
                    except Exception:
                        pass

        if best["id"] not in results:
            results[best["id"]] = ftr
            matched += 1

    total_csv = len([r for r in rows if r.get("FTR", "").strip() in ("H", "D", "A")])
    print(f"  {league} {season}: {matched}/{total_csv} matched")
    if unmatched_teams:
        print(f"    Unmatched teams: {sorted(unmatched_teams)}")

    return results


def fetch_all_results():
    for (league, season) in FDUK_URLS:
        print(f"Fetching {league} {season}...")
        results = fetch_and_match_results(league, season)
        save_path = DATA_DIR / f"results_{league}_{season}.json"
        existing = {}
        if save_path.exists():
            existing = json.loads(save_path.read_text())
        existing.update(results)
        save_path.write_text(json.dumps(existing, indent=2))
        print(f"  Saved: {len(existing)} total results")


if __name__ == "__main__":
    fetch_all_results()
