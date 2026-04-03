import json
import math
import os
import requests
from pathlib import Path
from nations_data import WC2026_NATIONS, get_all_nations, get_nation_by_code

BSD_CACHE_PATH = Path(__file__).parent / "bsd_data_cache.json"

WEIGHTS = {
    "results": 0.55,
    "squad": 0.30,
    "performance": 0.15,
}

BASE_ELO = 1500
ELO_RANGE = 600

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


SELECTION_FILE = Path(__file__).parent / "players_selection.json"


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


def compute_results_score(nation_code, elorating_base=None):
    if not elorating_base:
        return 50.0, {}

    nation = get_nation_by_code(nation_code)
    if not nation:
        return 50.0, {}

    team_name = nation["name"]
    lookup = NATION_TO_ELO_NAME.get(team_name, team_name)

    elo_val = elorating_base.get(lookup)
    if elo_val is None:
        for name, val in elorating_base.items():
            if name.lower() == lookup.lower():
                elo_val = val
                break

    if elo_val is None:
        return 50.0, {"elo_source": None}

    all_elos = list(elorating_base.values())
    min_elo = min(all_elos)
    max_elo = max(all_elos)
    score = (elo_val - min_elo) / (max_elo - min_elo) * 100 if max_elo > min_elo else 50

    return round(max(0, min(100, score)), 1), {
        "elo_source": elo_val,
        "elo_name": lookup,
    }


def compute_composite_elo(nation_code, elorating_base=None, cache=None, custom_weights=None):
    if cache is None:
        cache = _load_bsd_cache()

    w = custom_weights or WEIGHTS

    results_score, results_detail = compute_results_score(nation_code, elorating_base)
    squad_score, squad_detail = compute_squad_score(nation_code, cache)
    perf_score, perf_detail = compute_performance_score(nation_code, cache)

    composite_score = (
        results_score * w["results"]
        + squad_score * w["squad"]
        + perf_score * w["performance"]
    )

    elo_final = BASE_ELO + (composite_score / 100) * ELO_RANGE

    return {
        "code": nation_code,
        "elo": round(elo_final),
        "composite_score": round(composite_score, 1),
        "results_score": results_score,
        "squad_score": squad_score,
        "performance_score": perf_score,
        "results_detail": results_detail,
        "squad_detail": squad_detail,
        "performance_detail": perf_detail,
        "weights": w,
    }


def compute_all_nations_elo(elorating_base=None, custom_weights=None):
    cache = _load_bsd_cache()
    all_nations = get_all_nations()
    results = []
    for nation in all_nations:
        code = nation["code"]
        data = compute_composite_elo(code, elorating_base, cache, custom_weights)
        data["name"] = nation["name"]
        data["fr"] = nation["fr"]
        data["conf"] = nation["conf"]
        results.append(data)

    results.sort(key=lambda x: x["elo"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results
