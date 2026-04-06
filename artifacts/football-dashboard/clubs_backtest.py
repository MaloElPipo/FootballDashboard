"""
Club football backtest engine — Solution B.
Calibrate V-Pin model on 2023-24, test on 2024-25.
Uses historical odds from The Odds API (Pinnacle closing + Betclic).
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

DATA_DIR = Path(__file__).parent / "historical_data"

LEAGUES = {
    "soccer_epl": {"name": "Premier League", "country": "ENG", "k": 30, "home_adv": 70},
    "soccer_spain_la_liga": {"name": "La Liga", "country": "ESP", "k": 30, "home_adv": 75},
    "soccer_italy_serie_a": {"name": "Serie A", "country": "ITA", "k": 30, "home_adv": 65},
    "soccer_germany_bundesliga": {"name": "Bundesliga", "country": "GER", "k": 30, "home_adv": 60},
    "soccer_france_ligue_one": {"name": "Ligue 1", "country": "FRA", "k": 30, "home_adv": 65},
}

DEFAULT_ELO = 1500


def _sigmoid_clubs(delta_elo: float, params: dict, elo_avg: float = 1500.0) -> tuple[float, float, float]:
    scale = params["scale"]
    draw_base = params["draw_base"]
    d_half = max(params["d_half"], 1.0)
    power = params["power"]
    quality = params.get("quality", 0.0)

    draw_adj = draw_base + quality * (elo_avg - 1500) / 100
    draw_adj = max(draw_adj, 5.0)

    draw = draw_adj / (1.0 + (abs(delta_elo) / d_half) ** power)
    draw = max(draw, 0.5)

    sig = 1.0 / (1.0 + 10.0 ** (-delta_elo / scale))
    p1 = (100.0 - draw) * sig
    p2 = (100.0 - draw) * (1.0 - sig)

    p1 = float(np.clip(p1, 0.5, 99.0))
    p2 = float(np.clip(p2, 0.5, 99.0))
    draw = float(np.clip(draw, 0.5, 99.0))
    total = p1 + draw + p2

    return p1 / total, draw / total, p2 / total


def _odds_to_probs(h: float, d: float, a: float) -> tuple[float, float, float]:
    if h <= 1 or d <= 1 or a <= 1:
        return 0.0, 0.0, 0.0
    raw_h, raw_d, raw_a = 1.0 / h, 1.0 / d, 1.0 / a
    total = raw_h + raw_d + raw_a
    if total <= 0:
        return 0.0, 0.0, 0.0
    return raw_h / total, raw_d / total, raw_a / total


def _log_loss(p_pred: float, actual: bool) -> float:
    p = max(min(p_pred, 0.999), 0.001)
    return -math.log(p) if actual else -math.log(1.0 - p)


def _brier(p_pred: float, actual: bool) -> float:
    o = 1.0 if actual else 0.0
    return (p_pred - o) ** 2


def _result_from_pinnacle(match: dict) -> str | None:
    return match.get("result")


def load_season_matches(league: str, season: str) -> list[dict]:
    path = DATA_DIR / f"{league}_{season}.json"
    if not path.exists():
        return []

    raw = json.loads(path.read_text())
    matches_raw = raw.get("matches", {})

    matches = []
    for mid, m in matches_raw.items():
        if not m["odds_snapshots"]:
            continue

        commence = m["commence"]
        best_snap = None
        best_diff = float("inf")

        for snap in m["odds_snapshots"]:
            try:
                st = datetime.fromisoformat(snap["timestamp"].replace("Z", "+00:00"))
                ct = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                diff = (ct - st).total_seconds()
                if 0 < diff < best_diff:
                    best_diff = diff
                    best_snap = snap
            except Exception:
                continue

        if not best_snap:
            best_snap = m["odds_snapshots"][-1]

        pin = best_snap.get("bookmakers", {}).get("pinnacle", {})
        bet = best_snap.get("bookmakers", {}).get("betclic", {})

        pin_h2h = pin.get("h2h", {})
        bet_h2h = bet.get("h2h", {})

        home = m["home"]
        away = m["away"]

        pin_odds_h = pin_h2h.get(home, 0)
        pin_odds_d = pin_h2h.get("Draw", 0)
        pin_odds_a = pin_h2h.get(away, 0)

        bet_odds_h = bet_h2h.get(home, 0)
        bet_odds_d = bet_h2h.get("Draw", 0)
        bet_odds_a = bet_h2h.get(away, 0)

        if pin_odds_h <= 1 or pin_odds_d <= 1 or pin_odds_a <= 1:
            continue

        matches.append({
            "id": mid,
            "home": home,
            "away": away,
            "commence": commence,
            "league": league,
            "pin_h": pin_odds_h,
            "pin_d": pin_odds_d,
            "pin_a": pin_odds_a,
            "bet_h": bet_odds_h,
            "bet_d": bet_odds_d,
            "bet_a": bet_odds_a,
        })

    matches.sort(key=lambda x: x["commence"])
    return matches


class ClubEloSystem:
    def __init__(self, k_factor: int = 30, home_advantage: int = 65):
        self.ratings: dict[str, float] = {}
        self.k_factor = k_factor
        self.home_advantage = home_advantage
        self.match_count: dict[str, int] = {}

    def get_elo(self, team: str) -> float:
        return self.ratings.get(team, DEFAULT_ELO)

    def update(self, home: str, away: str, result: str):
        h_elo = self.get_elo(home) + self.home_advantage
        a_elo = self.get_elo(away)

        exp_h = 1.0 / (1.0 + 10.0 ** ((a_elo - h_elo) / 400.0))
        exp_a = 1.0 - exp_h

        if result == "H":
            s_h, s_a = 1.0, 0.0
        elif result == "A":
            s_h, s_a = 0.0, 1.0
        else:
            s_h, s_a = 0.5, 0.5

        n_h = self.match_count.get(home, 0)
        n_a = self.match_count.get(away, 0)
        k_h = self.k_factor * (1.5 if n_h < 5 else 1.2 if n_h < 15 else 1.0)
        k_a = self.k_factor * (1.5 if n_a < 5 else 1.2 if n_a < 15 else 1.0)

        self.ratings[home] = self.get_elo(home) + k_h * (s_h - exp_h)
        self.ratings[away] = self.get_elo(away) + k_a * (s_a - exp_a)

        self.match_count[home] = n_h + 1
        self.match_count[away] = n_a + 1


def _infer_result_from_pinnacle_movement(match: dict, all_matches: list[dict]) -> str | None:
    return None


def infer_result_from_odds(match: dict) -> str | None:
    pin_h, pin_d, pin_a = match["pin_h"], match["pin_d"], match["pin_a"]
    if pin_h <= 1 or pin_d <= 1 or pin_a <= 1:
        return None
    return None


def fetch_results_for_season(league: str, season: str) -> dict[str, str]:
    results_path = DATA_DIR / f"results_{league}_{season}.json"
    if results_path.exists():
        return json.loads(results_path.read_text())
    return {}


def save_results(league: str, season: str, results: dict[str, str]):
    results_path = DATA_DIR / f"results_{league}_{season}.json"
    results_path.write_text(json.dumps(results, indent=2))


def fetch_results_from_api(league: str, season: str) -> dict[str, str]:
    import os
    import httpx

    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        return {}

    matches = load_season_matches(league, season)
    if not matches:
        return {}

    results = fetch_results_for_season(league, season)
    to_fetch = [m for m in matches if m["id"] not in results]

    if not to_fetch:
        return results

    cfg = {"2023-24": ("2023-08-10", "2024-05-30"), "2024-25": ("2024-08-10", "2025-05-30")}
    start_str, end_str = cfg.get(season, ("2024-08-10", "2025-05-30"))

    from datetime import timedelta
    import time as _time

    start_dt = datetime.fromisoformat(start_str)
    end_dt = datetime.fromisoformat(end_str)
    now_dt = datetime.utcnow()
    if end_dt > now_dt:
        end_dt = now_dt - timedelta(days=1)

    current = start_dt
    fetched = 0

    while current <= end_dt:
        date_str = current.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"https://api.the-odds-api.com/v4/historical/sports/{league}/scores"
        params = {
            "apiKey": api_key,
            "date": date_str,
            "daysFrom": 3,
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    for ev in data.get("data", []):
                        if ev.get("completed") and ev.get("scores"):
                            eid = ev["id"]
                            scores = ev["scores"]
                            score_map = {s["name"]: int(s["score"]) for s in scores}
                            h_score = score_map.get(ev["home_team"], 0)
                            a_score = score_map.get(ev["away_team"], 0)
                            if h_score > a_score:
                                results[eid] = "H"
                            elif a_score > h_score:
                                results[eid] = "A"
                            else:
                                results[eid] = "D"
                    fetched += 1
                    remaining = int(resp.headers.get("x-requests-remaining", 0))
                    if fetched % 20 == 0:
                        print(f"  [{fetched}] {date_str} | results so far: {len(results)} | API remaining: {remaining}")
                    if remaining < 1000:
                        print(f"  Low quota: {remaining}. Stopping.")
                        break
        except Exception as e:
            print(f"  Error at {date_str}: {e}")

        current += timedelta(days=3)
        _time.sleep(0.2)

    save_results(league, season, results)
    return results


def calibrate_vpin_clubs(
    season: str = "2023-24",
    leagues: list[str] | None = None,
    home_advantage: int = 65,
) -> dict:
    target_leagues = leagues or list(LEAGUES.keys())

    all_matches = []
    all_results = {}

    for league in target_leagues:
        matches = load_season_matches(league, season)
        results = fetch_results_for_season(league, season)
        for m in matches:
            if m["id"] in results:
                m["result"] = results[m["id"]]
                all_matches.append(m)
        all_results.update(results)

    if not all_matches:
        return {"error": "No matches with results found"}

    print(f"Calibrating on {len(all_matches)} matches from {season}")

    elo_sys = ClubEloSystem(k_factor=30, home_advantage=home_advantage)
    match_elos = {}

    for m in all_matches:
        h_elo = elo_sys.get_elo(m["home"])
        a_elo = elo_sys.get_elo(m["away"])
        match_elos[m["id"]] = (h_elo, a_elo)
        elo_sys.update(m["home"], m["away"], m["result"])

    def objective(x):
        params = {
            "scale": x[0],
            "draw_base": x[1],
            "d_half": x[2],
            "power": x[3],
            "quality": x[4],
        }
        total_ll = 0.0
        count = 0
        for m in all_matches:
            h_elo, a_elo = match_elos[m["id"]]
            delta = (h_elo + home_advantage) - a_elo
            avg_elo = (h_elo + a_elo) / 2.0
            p_h, p_d, p_a = _sigmoid_clubs(delta, params, elo_avg=avg_elo)

            r = m["result"]
            ll = 0.0
            if r == "H":
                ll = -math.log(max(p_h, 0.001))
            elif r == "D":
                ll = -math.log(max(p_d, 0.001))
            elif r == "A":
                ll = -math.log(max(p_a, 0.001))
            total_ll += ll
            count += 1

        return total_ll / count if count > 0 else 999.0

    x0 = [400.0, 26.0, 400.0, 2.5, 0.03]
    bounds = [
        (100, 800),
        (15, 40),
        (100, 800),
        (1.5, 6.0),
        (-0.1, 0.2),
    ]

    result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 500, "ftol": 1e-10})

    best_params = {
        "scale": round(result.x[0], 3),
        "draw_base": round(result.x[1], 3),
        "d_half": round(result.x[2], 3),
        "power": round(result.x[3], 3),
        "quality": round(result.x[4], 4),
    }

    return {
        "params": best_params,
        "log_loss": round(result.fun, 6),
        "n_matches": len(all_matches),
        "season": season,
        "converged": result.success,
        "final_elos": dict(sorted(elo_sys.ratings.items(), key=lambda x: -x[1])[:30]),
    }


def run_backtest(
    calibration_season: str = "2023-24",
    test_season: str = "2024-25",
    params: dict | None = None,
    leagues: list[str] | None = None,
    home_advantage: int = 65,
) -> dict:
    target_leagues = leagues or list(LEAGUES.keys())

    if params is None:
        cal = calibrate_vpin_clubs(calibration_season, target_leagues, home_advantage)
        params = cal["params"]
        print(f"\nCalibrated params: {params}")
        print(f"Calibration log-loss: {cal['log_loss']}")

    cal_matches = []
    for league in target_leagues:
        matches = load_season_matches(league, calibration_season)
        results = fetch_results_for_season(league, calibration_season)
        for m in matches:
            if m["id"] in results:
                m["result"] = results[m["id"]]
                cal_matches.append(m)
    cal_matches.sort(key=lambda x: x["commence"])

    elo_sys = ClubEloSystem(k_factor=30, home_advantage=home_advantage)
    for m in cal_matches:
        elo_sys.update(m["home"], m["away"], m["result"])

    print(f"\nELO state after calibration season ({len(elo_sys.ratings)} teams)")

    test_matches = []
    for league in target_leagues:
        matches = load_season_matches(league, test_season)
        results = fetch_results_for_season(league, test_season)
        for m in matches:
            if m["id"] in results:
                m["result"] = results[m["id"]]
                test_matches.append(m)
    test_matches.sort(key=lambda x: x["commence"])

    if not test_matches:
        return {"error": "No test matches with results"}

    print(f"Testing on {len(test_matches)} matches from {test_season}")

    metrics = {
        "n_matches": 0,
        "model_log_loss": 0.0,
        "pinnacle_log_loss": 0.0,
        "model_brier": 0.0,
        "pinnacle_brier": 0.0,
        "correct_predictions": 0,
        "clv_total": 0.0,
        "clv_count": 0,
        "by_league": {},
        "calibration_bins": {i: {"predicted": 0.0, "actual": 0, "count": 0}
                            for i in range(10)},
        "match_details": [],
    }

    for m in test_matches:
        h_elo = elo_sys.get_elo(m["home"])
        a_elo = elo_sys.get_elo(m["away"])
        delta = (h_elo + home_advantage) - a_elo
        avg_elo = (h_elo + a_elo) / 2.0

        p_h, p_d, p_a = _sigmoid_clubs(delta, params, elo_avg=avg_elo)
        pin_ph, pin_pd, pin_pa = _odds_to_probs(m["pin_h"], m["pin_d"], m["pin_a"])

        result = m["result"]

        if result == "H":
            model_ll = -math.log(max(p_h, 0.001))
            pin_ll = -math.log(max(pin_ph, 0.001))
            model_b = (p_h - 1) ** 2 + p_d ** 2 + p_a ** 2
            pin_b = (pin_ph - 1) ** 2 + pin_pd ** 2 + pin_pa ** 2
            predicted_right = p_h == max(p_h, p_d, p_a)
            p_pred_outcome = p_h
        elif result == "D":
            model_ll = -math.log(max(p_d, 0.001))
            pin_ll = -math.log(max(pin_pd, 0.001))
            model_b = p_h ** 2 + (p_d - 1) ** 2 + p_a ** 2
            pin_b = pin_ph ** 2 + (pin_pd - 1) ** 2 + pin_pa ** 2
            predicted_right = p_d == max(p_h, p_d, p_a)
            p_pred_outcome = p_d
        elif result == "A":
            model_ll = -math.log(max(p_a, 0.001))
            pin_ll = -math.log(max(pin_pa, 0.001))
            model_b = p_h ** 2 + p_d ** 2 + (p_a - 1) ** 2
            pin_b = pin_ph ** 2 + pin_pd ** 2 + (pin_pa - 1) ** 2
            predicted_right = p_a == max(p_h, p_d, p_a)
            p_pred_outcome = p_a
        else:
            continue

        metrics["n_matches"] += 1
        metrics["model_log_loss"] += model_ll
        metrics["pinnacle_log_loss"] += pin_ll
        metrics["model_brier"] += model_b
        metrics["pinnacle_brier"] += pin_b
        if predicted_right:
            metrics["correct_predictions"] += 1

        if m["bet_h"] > 1 and m["bet_d"] > 1 and m["bet_a"] > 1:
            bet_ph, bet_pd, bet_pa = _odds_to_probs(m["bet_h"], m["bet_d"], m["bet_a"])
            if result == "H" and pin_ph > 0 and bet_ph > 0:
                clv = (pin_ph / bet_ph - 1) * 100
                metrics["clv_total"] += clv
                metrics["clv_count"] += 1
            elif result == "D" and pin_pd > 0 and bet_pd > 0:
                clv = (pin_pd / bet_pd - 1) * 100
                metrics["clv_total"] += clv
                metrics["clv_count"] += 1
            elif result == "A" and pin_pa > 0 and bet_pa > 0:
                clv = (pin_pa / bet_pa - 1) * 100
                metrics["clv_total"] += clv
                metrics["clv_count"] += 1

        for p_val, is_actual in [(p_h, result == "H"), (p_d, result == "D"), (p_a, result == "A")]:
            cal_bin = min(int(p_val * 10), 9)
            metrics["calibration_bins"][cal_bin]["predicted"] += p_val
            metrics["calibration_bins"][cal_bin]["actual"] += (1 if is_actual else 0)
            metrics["calibration_bins"][cal_bin]["count"] += 1

        league = m["league"]
        if league not in metrics["by_league"]:
            metrics["by_league"][league] = {"n": 0, "model_ll": 0.0, "pin_ll": 0.0,
                                            "brier": 0.0, "correct": 0}
        metrics["by_league"][league]["n"] += 1
        metrics["by_league"][league]["model_ll"] += model_ll
        metrics["by_league"][league]["pin_ll"] += pin_ll
        metrics["by_league"][league]["brier"] += model_b
        if predicted_right:
            metrics["by_league"][league]["correct"] += 1

        elo_sys.update(m["home"], m["away"], result)

        metrics["match_details"].append({
            "home": m["home"], "away": m["away"],
            "result": result, "league": league,
            "elo_h": round(h_elo, 1), "elo_a": round(a_elo, 1),
            "model_h": round(p_h, 4), "model_d": round(p_d, 4), "model_a": round(p_a, 4),
            "pin_h": round(pin_ph, 4), "pin_d": round(pin_pd, 4), "pin_a": round(pin_pa, 4),
            "model_ll": round(model_ll, 4), "pin_ll": round(pin_ll, 4),
        })

    n = metrics["n_matches"]
    if n > 0:
        metrics["model_log_loss"] = round(metrics["model_log_loss"] / n, 6)
        metrics["pinnacle_log_loss"] = round(metrics["pinnacle_log_loss"] / n, 6)
        metrics["model_brier"] = round(metrics["model_brier"] / n, 6)
        metrics["pinnacle_brier"] = round(metrics["pinnacle_brier"] / n, 6)
        metrics["accuracy"] = round(metrics["correct_predictions"] / n * 100, 2)
        metrics["clv_avg"] = round(metrics["clv_total"] / metrics["clv_count"], 3) if metrics["clv_count"] > 0 else 0
        metrics["ll_ratio"] = round(metrics["model_log_loss"] / metrics["pinnacle_log_loss"], 4) if metrics["pinnacle_log_loss"] > 0 else 0

        for league, ld in metrics["by_league"].items():
            ln = ld["n"]
            ld["model_ll"] = round(ld["model_ll"] / ln, 4)
            ld["pin_ll"] = round(ld["pin_ll"] / ln, 4)
            ld["brier"] = round(ld["brier"] / ln, 4)
            ld["accuracy"] = round(ld["correct"] / ln * 100, 2)

    cal_diagram = {}
    for i, b in metrics["calibration_bins"].items():
        if b["count"] > 0:
            avg_pred = b["predicted"] / b["count"]
            actual_rate = b["actual"] / b["count"]
            cal_diagram[f"{i*10}-{(i+1)*10}%"] = {
                "avg_predicted": round(avg_pred * 100, 1),
                "actual_rate": round(actual_rate * 100, 1),
                "count": b["count"],
            }
    metrics["calibration_diagram"] = cal_diagram

    metrics["params_used"] = params
    metrics["final_elos_top20"] = dict(sorted(elo_sys.ratings.items(), key=lambda x: -x[1])[:20])

    del metrics["match_details"]
    del metrics["calibration_bins"]

    return metrics


def print_report(metrics: dict):
    print("\n" + "=" * 70)
    print("CLUB BACKTEST REPORT — V-Pin Model")
    print("=" * 70)

    print(f"\nParams: {metrics.get('params_used', {})}")
    print(f"\nMatches tested: {metrics['n_matches']}")
    print(f"Accuracy (most probable outcome): {metrics.get('accuracy', 0)}%")

    print(f"\n{'Metric':<30} {'Model':<15} {'Pinnacle':<15} {'Ratio':<10}")
    print("-" * 70)
    print(f"{'Log-Loss':<30} {metrics['model_log_loss']:<15} {metrics['pinnacle_log_loss']:<15} {metrics.get('ll_ratio', 0):<10}")
    print(f"{'Brier Score':<30} {metrics['model_brier']:<15} {metrics['pinnacle_brier']:<15}")

    if metrics.get("clv_count", 0) > 0:
        print(f"\nCLV moyen (Betclic → Pinnacle): {metrics['clv_avg']:.3f}%")
        print(f"CLV calculé sur {metrics['clv_count']} matchs")

    print(f"\n{'League':<25} {'N':<6} {'Model LL':<12} {'Pin LL':<12} {'Accuracy':<10}")
    print("-" * 65)
    for league, ld in sorted(metrics.get("by_league", {}).items()):
        name = LEAGUES.get(league, {}).get("name", league)
        print(f"{name:<25} {ld['n']:<6} {ld['model_ll']:<12} {ld['pin_ll']:<12} {ld['accuracy']}%")

    print(f"\n{'Bin':<15} {'Avg Predicted':<15} {'Actual Rate':<15} {'Count':<10}")
    print("-" * 55)
    for bin_name, data in sorted(metrics.get("calibration_diagram", {}).items()):
        print(f"{bin_name:<15} {data['avg_predicted']:<15} {data['actual_rate']:<15} {data['count']:<10}")

    if metrics.get("final_elos_top20"):
        print(f"\nTop 20 ELO (fin de test):")
        for team, elo in list(metrics["final_elos_top20"].items()):
            print(f"  {team:<25} {elo:.0f}")


if __name__ == "__main__":
    import sys

    if "--fetch-results" in sys.argv:
        for league in LEAGUES:
            for season in ["2023-24", "2024-25"]:
                print(f"\nFetching results: {LEAGUES[league]['name']} {season}")
                results = fetch_results_from_api(league, season)
                print(f"  → {len(results)} results")

    elif "--calibrate" in sys.argv:
        cal = calibrate_vpin_clubs("2023-24")
        print(f"\nCalibration result:")
        print(json.dumps(cal, indent=2))

    elif "--backtest" in sys.argv:
        metrics = run_backtest("2023-24", "2024-25")
        print_report(metrics)

    elif "--full" in sys.argv:
        print("Step 1: Fetching results...")
        for league in LEAGUES:
            for season in ["2023-24", "2024-25"]:
                print(f"  {LEAGUES[league]['name']} {season}...")
                results = fetch_results_from_api(league, season)
                print(f"    → {len(results)} results")

        print("\nStep 2: Calibrate + Backtest")
        metrics = run_backtest("2023-24", "2024-25")
        print_report(metrics)

    else:
        print("Usage:")
        print("  --fetch-results : Fetch match results from API")
        print("  --calibrate     : Calibrate V-Pin on 2023-24")
        print("  --backtest      : Run walk-forward backtest")
        print("  --full          : Fetch results + calibrate + backtest")
