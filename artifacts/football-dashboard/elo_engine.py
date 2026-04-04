import json
import math
import os
import numpy as np
import requests
from pathlib import Path
from nations_data import WC2026_NATIONS, get_all_nations, get_nation_by_code

BSD_CACHE_PATH = Path(__file__).parent / "bsd_data_cache.json"
OVERRIDES_PATH = Path(__file__).parent / "elo_overrides.json"
SELECTION_FILE = Path(__file__).parent / "players_selection.json"
PIN_CALIBRATED_PATH = Path(__file__).parent / "pin_calibrated_elo.json"

FORCED_ELO_WEIGHT_DEFAULT = 0.80
PIN_WEIGHT_DEFAULT = 1.0

ODDS_API_NAME_MAP = {
    "Bosnia and Herzegovina": "BIH",
    "DR Congo": "COD",
    "Republic of Ireland": "IRL",
    "South Korea": "KOR",
    "Ivory Coast": "CIV",
    "Czech Republic": "CZE",
    "United States": "USA",
}

ODDS_API_TO_FIFA = {
    "Mexico": "MEX", "South Africa": "RSA", "South Korea": "KOR",
    "Czech Republic": "CZE", "Canada": "CAN",
    "Bosnia and Herzegovina": "BIH", "USA": "USA", "United States": "USA",
    "Paraguay": "PAR", "Qatar": "QAT", "Switzerland": "SUI",
    "Brazil": "BRA", "Morocco": "MAR", "Haiti": "HAI", "Scotland": "SCO",
    "Australia": "AUS", "Turkey": "TUR", "Netherlands": "NED",
    "Japan": "JPN", "Ivory Coast": "CIV", "Ecuador": "ECU",
    "Sweden": "SWE", "Tunisia": "TUN", "Belgium": "BEL", "Egypt": "EGY",
    "Saudi Arabia": "KSA", "Uruguay": "URU", "France": "FRA",
    "Senegal": "SEN", "Iraq": "IRQ", "Norway": "NOR",
    "Argentina": "ARG", "Algeria": "ALG", "Jordan": "JOR",
    "Portugal": "POR", "DR Congo": "COD", "England": "ENG",
    "Croatia": "CRO", "Ghana": "GHA", "Panama": "PAN",
    "Uzbekistan": "UZB", "Colombia": "COL", "Spain": "ESP",
    "Germany": "GER", "Denmark": "DEN", "Serbia": "SRB",
    "Iran": "IRN", "New Zealand": "NZL", "Cape Verde": "CPV",
    "Curaçao": "CUW", "Curacao": "CUW",
}

ELORATING_FALLBACKS = {
    "SCO": 1700,
    "CUW": 1350,
    "CIV": 1750,
}

ELO_CODE_TO_NAME = {
    "ES": "Spain", "AR": "Argentina", "FR": "France", "EN": "England", "BR": "Brazil",
    "PT": "Portugal", "CO": "Colombia", "NL": "Netherlands", "EC": "Ecuador", "HR": "Croatia",
    "DE": "Germany", "NO": "Norway", "JP": "Japan", "TR": "Turkey", "UY": "Uruguay",
    "CH": "Switzerland", "SN": "Senegal", "DK": "Denmark", "BE": "Belgium", "MX": "Mexico",
    "IT": "Italy", "PY": "Paraguay", "AT": "Austria", "MA": "Morocco", "CA": "Canada",
    "AU": "Australia", "RU": "Russia", "RS": "Serbia", "SQ": "Albania", "UA": "Ukraine",
    "IR": "Iran", "KR": "South Korea", "NG": "Nigeria", "GR": "Greece", "DZ": "Algeria",
    "PA": "Panama", "PL": "Poland", "UZ": "Uzbekistan", "VE": "Venezuela", "CZ": "Czechia",
    "US": "United States", "KO": "Kosovo", "SE": "Sweden", "CL": "Chile", "HU": "Hungary",
    "WA": "Wales", "PE": "Peru", "SI": "Slovenia", "IE": "Republic of Ireland", "JO": "Jordan",
    "EG": "Egypt", "CI": "Côte d'Ivoire", "SK": "Slovakia", "CD": "DR Congo", "GE": "Georgia",
    "AL": "Armenia", "BO": "Bolivia", "TN": "Tunisia", "IL": "Israel", "RO": "Romania",
    "CM": "Cameroon", "CR": "Costa Rica", "IQ": "Iraq", "EI": "Ireland", "ML": "Mali",
    "BA": "Bosnia & Herzegovina", "NM": "North Macedonia", "NZ": "New Zealand",
    "HN": "Honduras", "IS": "Iceland", "SA": "Saudi Arabia", "CV": "Cape Verde",
    "AO": "Angola", "FI": "Finland", "AE": "United Arab Emirates", "JM": "Jamaica",
    "HT": "Haiti", "BF": "Burkina Faso", "ZA": "South Africa", "GT": "Guatemala",
    "BY": "Belarus", "GH": "Ghana", "SY": "Syria", "OM": "Oman", "BG": "Bulgaria",
    "GN": "Guinea", "PS": "Palestine", "NS": "Northern Ireland", "ME": "Montenegro",
    "CW": "Curaçao", "LU": "Luxembourg", "SR": "Suriname", "KZ": "Kazakhstan",
    "BJ": "Benin", "QA": "Qatar", "KD": "Kyrgyzstan", "CN": "China", "GM": "Gambia",
    "LY": "Libya", "BH": "Bahrain", "GA": "Gabon", "UG": "Uganda", "NE": "Niger",
    "TT": "Trinidad & Tobago", "GQ": "Equatorial Guinea", "MG": "Madagascar",
    "FO": "Faroe Islands", "AM": "Armenia", "TH": "Thailand", "KP": "North Korea",
    "MZ": "Mozambique", "ZW": "Zimbabwe", "ZM": "Zambia", "KM": "Comoros",
}

NATION_NAME_TO_FIFA = {
    "Spain": "ESP", "Argentina": "ARG", "France": "FRA", "England": "ENG",
    "Brazil": "BRA", "Portugal": "POR", "Colombia": "COL", "Netherlands": "NED",
    "Ecuador": "ECU", "Croatia": "CRO", "Germany": "GER", "Norway": "NOR",
    "Japan": "JPN", "Turkey": "TUR", "Uruguay": "URU", "Switzerland": "SUI",
    "Senegal": "SEN", "Belgium": "BEL", "Mexico": "MEX", "Paraguay": "PAR",
    "Austria": "AUT", "Morocco": "MAR", "Canada": "CAN", "Australia": "AUS",
    "Iran": "IRN", "South Korea": "KOR", "Algeria": "ALG", "Panama": "PAN",
    "Uzbekistan": "UZB", "Czechia": "CZE", "Sweden": "SWE", "Jordan": "JOR",
    "Egypt": "EGY", "DR Congo": "COD", "Tunisia": "TUN", "Iraq": "IRQ",
    "Bosnia & Herzegovina": "BIH", "New Zealand": "NZL", "Saudi Arabia": "KSA",
    "Cape Verde": "CPV", "Haiti": "HAI", "South Africa": "RSA", "Ghana": "GHA",
    "Qatar": "QAT", "Scotland": "SCO", "Curaçao": "CUW", "Côte d'Ivoire": "CIV",
    "United States": "USA", "Ivory Coast": "CIV",
}

NATION_TO_ELO_NAME = {
    "Czech Republic": "Czechia",
    "Bosnia-Herzegovina": "Bosnia & Herzegovina",
    "Curacao": "Curaçao",
    "Ivory Coast": "Côte d'Ivoire",
}


def fetch_elorating_base():
    try:
        r = requests.get(
            "https://www.eloratings.net/World.tsv",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        result = {}
        for line in r.text.split("\n"):
            parts = line.split("\t")
            if len(parts) >= 4:
                try:
                    code = parts[2].strip()
                    elo = int(parts[3])
                    name = ELO_CODE_TO_NAME.get(code)
                    if name:
                        result[name] = elo
                except Exception:
                    pass
        return result
    except Exception:
        return {}


def _elorating_to_fifa_map(elorating_base):
    elo_by_fifa = {}
    for name, elo_val in elorating_base.items():
        fifa_code = NATION_NAME_TO_FIFA.get(name)
        if fifa_code and isinstance(elo_val, (int, float)):
            elo_by_fifa[fifa_code] = elo_val
    for code, fallback in ELORATING_FALLBACKS.items():
        if code not in elo_by_fifa:
            elo_by_fifa[code] = fallback
    return elo_by_fifa


def load_elo_overrides():
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        with open(OVERRIDES_PATH) as f:
            data = json.load(f)
        return {k: int(v) for k, v in data.items() if v is not None and str(v).strip() != ""}
    except Exception:
        return {}


def save_elo_overrides(overrides):
    clean = {k: int(v) for k, v in overrides.items() if v is not None and str(v).strip() != ""}
    with open(OVERRIDES_PATH, "w") as f:
        json.dump(clean, f, indent=2)


def _load_bsd_cache():
    if not BSD_CACHE_PATH.exists():
        return {}
    with open(BSD_CACHE_PATH) as f:
        return json.load(f)


def _load_player_selection():
    if not SELECTION_FILE.exists():
        return {}
    with open(SELECTION_FILE) as f:
        return json.load(f)


def _get_squad_players(cache, nation_code, active_only=True):
    squad_map = cache.get("squad_matches", {})
    player_stats = cache.get("player_stats", {})
    squad = squad_map.get(nation_code, {})

    active_filter = None
    if active_only:
        all_sel = _load_player_selection()
        nation_sel = all_sel.get(nation_code, {})
        if nation_sel:
            active_filter = {name for name, status in nation_sel.items() if status}

    players = []
    for name, api_id in squad.items():
        if active_filter is not None and name not in active_filter:
            continue
        s = player_stats.get(str(api_id), {})
        if s and s.get("appearances"):
            players.append({"name": name, **s})
    return players


def compute_squad_score(nation_code, cache=None):
    if cache is None:
        cache = _load_bsd_cache()
    players = _get_squad_players(cache, nation_code)
    if not players:
        return 50.0, {}

    ratings = [float(p.get("rating", 0) or 0) for p in players if p.get("rating")]
    if not ratings:
        return 50.0, {}

    sorted_ratings = sorted(ratings, reverse=True)
    top11_avg = sum(sorted_ratings[:11]) / min(11, len(sorted_ratings))
    bench_players = sorted_ratings[11:23]
    bench_avg = sum(bench_players) / len(bench_players) if bench_players else top11_avg * 0.9
    depth_ratio = bench_avg / top11_avg if top11_avg > 0 else 0.9

    total_xg = sum(float(p.get("xg", 0) or 0) for p in players)
    total_xa = sum(float(p.get("xa", 0) or 0) for p in players)
    total_minutes = sum(int(p.get("minutes_played", 0) or 0) for p in players)
    nineties = total_minutes / 90.0 if total_minutes > 0 else 1
    xg_per90 = total_xg / nineties
    xa_per90 = total_xa / nineties

    rating_score = max(0, min(100, (top11_avg - 6.0) / (7.5 - 6.0) * 100))
    depth_score = max(0, min(100, depth_ratio * 100))
    xg_score = max(0, min(100, xg_per90 / 2.5 * 100))
    xa_score = max(0, min(100, xa_per90 / 1.5 * 100))

    composite = (
        rating_score * 0.45
        + depth_score * 0.20
        + xg_score * 0.20
        + xa_score * 0.15
    )

    details = {
        "n_players": len(players),
        "top11_avg": round(top11_avg, 2),
        "bench_avg": round(bench_avg, 2),
        "depth_ratio": round(depth_ratio, 3),
        "xg_per90": round(xg_per90, 2),
        "xa_per90": round(xa_per90, 2),
        "rating_score": round(rating_score, 1),
        "depth_score": round(depth_score, 1),
        "xg_score": round(xg_score, 1),
        "xa_score": round(xa_score, 1),
    }
    return round(max(0, min(100, composite)), 1), details


def compute_performance_score(nation_code, cache=None):
    if cache is None:
        cache = _load_bsd_cache()
    players = _get_squad_players(cache, nation_code)
    if not players:
        return 50.0, {}

    total_minutes = sum(int(p.get("minutes_played", 0) or 0) for p in players)
    nineties = total_minutes / 90.0 if total_minutes > 0 else 1

    total_xg = sum(float(p.get("xg", 0) or 0) for p in players)
    total_goals = sum(int(p.get("goals", 0) or 0) for p in players)
    total_shots_on = sum(int(p.get("shots_on_target", 0) or 0) for p in players)
    total_duels_won = sum(int(p.get("duels_won", 0) or 0) for p in players)
    total_duels_lost = sum(int(p.get("duels_lost", 0) or 0) for p in players)
    total_key_passes = sum(int(p.get("key_passes", 0) or 0) for p in players)

    xg_per90 = total_xg / nineties
    goals_per90 = total_goals / nineties
    shots_on_target_per90 = total_shots_on / nineties
    duel_pct = (total_duels_won / (total_duels_won + total_duels_lost) * 100) if (total_duels_won + total_duels_lost) > 0 else 50
    key_passes_per90 = total_key_passes / nineties
    conversion = (total_goals / total_xg * 100) if total_xg > 0 else 100

    xg_score = max(0, min(100, xg_per90 / 2.0 * 100))
    duels_score = max(0, min(100, (duel_pct - 40) / (60 - 40) * 100))
    shots_score = max(0, min(100, shots_on_target_per90 / 6.0 * 100))
    creativity_score = max(0, min(100, key_passes_per90 / 4.0 * 100))

    composite = (
        xg_score * 0.40
        + duels_score * 0.25
        + shots_score * 0.20
        + creativity_score * 0.15
    )

    details = {
        "xg_per90": round(xg_per90, 2),
        "goals_per90": round(goals_per90, 2),
        "shots_on_target_per90": round(shots_on_target_per90, 2),
        "duel_pct": round(duel_pct, 1),
        "key_passes_per90": round(key_passes_per90, 2),
        "conversion_pct": round(conversion, 1),
        "xg_score": round(xg_score, 1),
        "duels_score": round(duels_score, 1),
        "shots_score": round(shots_score, 1),
        "creativity_score": round(creativity_score, 1),
    }
    return round(max(0, min(100, composite)), 1), details


def compute_nation_elo(nation_code, elorating_by_fifa, cache=None):
    if cache is None:
        cache = _load_bsd_cache()

    base_elo = elorating_by_fifa.get(nation_code)
    if base_elo is None:
        base_elo = 1500

    squad_score, squad_detail = compute_squad_score(nation_code, cache)
    perf_score, perf_detail = compute_performance_score(nation_code, cache)

    return {
        "code": nation_code,
        "elo_base": base_elo,
        "squad_score": squad_score,
        "performance_score": perf_score,
        "squad_detail": squad_detail,
        "performance_detail": perf_detail,
    }


def compute_bsd_adjustment(squad_score, perf_score, all_squad_scores, all_perf_scores):
    sq_arr = np.array(all_squad_scores)
    pf_arr = np.array(all_perf_scores)
    sq_mean, sq_std = sq_arr.mean(), sq_arr.std()
    pf_mean, pf_std = pf_arr.mean(), pf_arr.std()

    sq_z = (squad_score - sq_mean) / sq_std if sq_std > 0 else 0
    pf_z = (perf_score - pf_mean) / pf_std if pf_std > 0 else 0

    adj = np.clip(sq_z, -2, 2) * 25 * 0.7 + np.clip(pf_z, -2, 2) * 25 * 0.3
    return int(round(adj))


def load_pin_calibrated_elo():
    if not PIN_CALIBRATED_PATH.exists():
        return {}
    try:
        with open(PIN_CALIBRATED_PATH) as f:
            data = json.load(f)
        return data
    except Exception:
        return {}


def save_pin_calibrated_elo(data):
    with open(PIN_CALIBRATED_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _pinnacle_implied_delta(pin_h, pin_d, pin_a, params):
    from backtest_engine import _sigmoid_custom
    margin = 1/pin_h + 1/pin_d + 1/pin_a
    target_ph = (1/pin_h) / margin
    target_pd = (1/pin_d) / margin
    target_pa = (1/pin_a) / margin

    best_delta = 0
    best_err = float('inf')
    for delta in range(-800, 801, 1):
        p1, px, p2 = _sigmoid_custom(
            delta, params["scale"], params["draw_base"], params["d_half"],
            params["power"], params["quality"], elo_avg=1800, phase="G",
            db_close=params["db_close"], db_mid=params["db_mid"],
            db_ko=params["db_ko"], db_max=params["db_max"],
            fb_group=params["fb_group"], fb_ko=params["fb_ko"],
            fav_threshold=params["fav_threshold"],
        )
        err = (p1 - target_ph)**2 + (px - target_pd)**2 + (p2 - target_pa)**2
        if err < best_err:
            best_err = err
            best_delta = delta
    return best_delta


def calibrate_elo_from_pinnacle(current_elo_by_code):
    from backtest_engine import V8PIN_PARAMS
    import datetime

    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        return None, "ODDS_API_KEY manquante"

    r = requests.get(
        "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds",
        params={
            "apiKey": api_key, "regions": "eu", "markets": "h2h",
            "bookmakers": "pinnacle", "oddsFormat": "decimal",
        },
        timeout=20,
    )
    if r.status_code != 200:
        return None, f"Erreur API: {r.status_code}"

    wc_odds = r.json()
    remaining = r.headers.get("x-requests-remaining", "?")

    corrections_by_code = {}

    for m in wc_odds:
        home = m["home_team"]
        away = m["away_team"]
        bm = m.get("bookmakers", [])
        if not bm:
            continue
        outcomes = bm[0]["markets"][0]["outcomes"]
        odds_map = {o["name"]: o["price"] for o in outcomes}
        pin_h = odds_map.get(home, 0)
        pin_d = odds_map.get("Draw", 0)
        pin_a = odds_map.get(away, 0)
        if not pin_h or not pin_d or not pin_a:
            continue

        code_h = ODDS_API_TO_FIFA.get(home)
        code_a = ODDS_API_TO_FIFA.get(away)
        if not code_h or not code_a:
            continue

        elo_h = current_elo_by_code.get(code_h, 1500)
        elo_a = current_elo_by_code.get(code_a, 1500)

        pin_delta = _pinnacle_implied_delta(pin_h, pin_d, pin_a, V8PIN_PARAMS)
        mid = (elo_h + elo_a) / 2
        corr_h = mid + pin_delta / 2
        corr_a = mid - pin_delta / 2

        if code_h not in corrections_by_code:
            corrections_by_code[code_h] = []
        corrections_by_code[code_h].append(corr_h)
        if code_a not in corrections_by_code:
            corrections_by_code[code_a] = []
        corrections_by_code[code_a].append(corr_a)

    pin_elo = {}
    for code, vals in corrections_by_code.items():
        pin_elo[code] = int(round(np.mean(vals)))

    result = {
        "calibrated_at": datetime.datetime.now().isoformat(),
        "n_matches": len(wc_odds),
        "n_nations": len(pin_elo),
        "api_remaining": remaining,
        "elo": pin_elo,
    }
    save_pin_calibrated_elo(result)
    return result, None


def compute_all_nations_elo(elorating_base=None, forced_weight=None, pin_weight=None):
    if elorating_base is None:
        elorating_base = fetch_elorating_base()

    if forced_weight is None:
        forced_weight = FORCED_ELO_WEIGHT_DEFAULT

    if pin_weight is None:
        pin_weight = PIN_WEIGHT_DEFAULT

    cache = _load_bsd_cache()
    elorating_by_fifa = _elorating_to_fifa_map(elorating_base)
    overrides = load_elo_overrides()
    pin_data = load_pin_calibrated_elo()
    pin_elo = pin_data.get("elo", {}) if pin_data else {}

    all_nations = get_all_nations()
    nation_data_list = []
    for nation in all_nations:
        code = nation["code"]
        data = compute_nation_elo(code, elorating_by_fifa, cache)
        data["name"] = nation["name"]
        data["fr"] = nation["fr"]
        data["conf"] = nation["conf"]
        nation_data_list.append(data)

    all_sq = [d["squad_score"] for d in nation_data_list]
    all_pf = [d["performance_score"] for d in nation_data_list]

    for data in nation_data_list:
        adj = compute_bsd_adjustment(data["squad_score"], data["performance_score"], all_sq, all_pf)
        data["bsd_adj"] = adj
        data["elo_system"] = data["elo_base"] + adj
        data["elo_calculated"] = data["elo_system"]

        pin_val = pin_elo.get(data["code"])
        data["elo_pin"] = pin_val

        if pin_val is not None and pin_weight > 0:
            data["elo_calculated"] = int(round(
                pin_val * pin_weight + data["elo_system"] * (1 - pin_weight)
            ))

        forced_val = overrides.get(data["code"])
        data["elo_forced"] = forced_val

        if forced_val is not None:
            data["elo"] = int(round(
                forced_val * forced_weight + data["elo_calculated"] * (1 - forced_weight)
            ))
        else:
            data["elo"] = data["elo_calculated"]

    nation_data_list.sort(key=lambda x: x["elo"], reverse=True)
    for i, r in enumerate(nation_data_list):
        r["rank"] = i + 1

    return nation_data_list
