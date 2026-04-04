import math
import random
import numpy as np
from collections import defaultdict
from elo_engine import compute_all_nations_elo, fetch_elorating_base
from nations_data import get_nation_by_code

WC2026_GROUPS = {
    "A": ["MEX", "RSA", "KOR", "CZE"],
    "B": ["CAN", "BIH", "QAT", "SUI"],
    "C": ["BRA", "MAR", "HAI", "SCO"],
    "D": ["USA", "PAR", "AUS", "TUR"],
    "E": ["GER", "CUW", "CIV", "ECU"],
    "F": ["NED", "JPN", "SWE", "TUN"],
    "G": ["BEL", "EGY", "IRN", "NZL"],
    "H": ["ESP", "CPV", "KSA", "URU"],
    "I": ["FRA", "SEN", "IRQ", "NOR"],
    "J": ["ARG", "ALG", "AUT", "JOR"],
    "K": ["POR", "COD", "UZB", "COL"],
    "L": ["ENG", "CRO", "GHA", "PAN"],
}

GROUP_MATCHES = {
    "MD1": [(0, 1), (2, 3)],
    "MD2": [(0, 2), (3, 1)],
    "MD3": [(3, 0), (1, 2)],
}

R32_BRACKET = [
    {"match": 73, "home": ("2", "A"), "away": ("2", "B")},
    {"match": 74, "home": ("1", "E"), "away": ("3rd", "A/B/C/D/F")},
    {"match": 75, "home": ("1", "F"), "away": ("2", "C")},
    {"match": 76, "home": ("1", "C"), "away": ("2", "F")},
    {"match": 77, "home": ("1", "I"), "away": ("3rd", "C/D/F/G/H")},
    {"match": 78, "home": ("2", "E"), "away": ("2", "I")},
    {"match": 79, "home": ("1", "A"), "away": ("3rd", "C/E/F/H/I")},
    {"match": 80, "home": ("1", "L"), "away": ("3rd", "E/H/I/J/K")},
    {"match": 81, "home": ("1", "D"), "away": ("3rd", "B/E/F/I/J")},
    {"match": 82, "home": ("1", "G"), "away": ("3rd", "A/E/H/I/J")},
    {"match": 83, "home": ("2", "K"), "away": ("2", "L")},
    {"match": 84, "home": ("1", "H"), "away": ("2", "J")},
    {"match": 85, "home": ("1", "B"), "away": ("3rd", "E/F/G/I/J")},
    {"match": 86, "home": ("1", "J"), "away": ("2", "H")},
    {"match": 87, "home": ("1", "K"), "away": ("3rd", "D/E/I/J/L")},
    {"match": 88, "home": ("2", "D"), "away": ("2", "G")},
]

R16_PAIRINGS = [
    (73, 74), (75, 76), (77, 78), (79, 80),
    (81, 82), (83, 84), (85, 86), (87, 88),
]

QF_PAIRINGS = [
    (0, 1), (2, 3), (4, 5), (6, 7),
]

SF_PAIRINGS = [(0, 1), (2, 3)]

HOST_NATIONS = {"USA", "MEX", "CAN"}

V7_SCALE = 441.952
V7_DRAW_BASE = 24.09
V7_D_HALF = 463.648
V7_POWER = 3.56
V7_QUALITY = 0.035

V8_DRAW_BOOST_CLOSE = 4.312
V8_DRAW_BOOST_MID = 2.555
V8_DRAW_BOOST_KO = 3.37
V8_DRAW_BOOST_MAX = 36.049
V8_FAV_BOOST_GROUP = -2.446
V8_FAV_BOOST_KO = 2.746
V8_FAV_DELTA_THRESHOLD = 380.332


def sigmoid_v6_1x2(delta_elo, params=None, elo_avg=None):
    if params is None:
        params = (V7_SCALE, V7_DRAW_BASE, V7_D_HALF, V7_POWER, V7_QUALITY)
    if len(params) == 4:
        scale, draw_base, d_half, power = params
        quality = V7_QUALITY
    else:
        scale, draw_base, d_half, power, quality = params
    d_half = max(d_half, 1.0)
    draw_adj = draw_base
    if elo_avg is not None:
        draw_adj = draw_base + quality * (elo_avg - 1800) / 100
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


def sigmoid_v8_1x2(delta_elo, elo_avg=None, phase="G"):
    p1, px, p2 = sigmoid_v6_1x2(delta_elo, elo_avg=elo_avg)

    abs_d = abs(delta_elo)
    draw_boost = 0.0
    if abs_d < 100:
        draw_boost += V8_DRAW_BOOST_CLOSE / 100.0
    elif abs_d < 200:
        draw_boost += V8_DRAW_BOOST_MID / 100.0

    if phase == "K":
        draw_boost += V8_DRAW_BOOST_KO / 100.0

    draw_boost = min(draw_boost, V8_DRAW_BOOST_MAX / 100.0)

    fav_boost = 0.0
    if abs_d >= V8_FAV_DELTA_THRESHOLD:
        if phase == "K":
            fav_boost = V8_FAV_BOOST_KO / 100.0
        else:
            fav_boost = V8_FAV_BOOST_GROUP / 100.0

    net_draw = draw_boost - fav_boost * 0.7
    net_draw = max(net_draw, 0.0)

    px_new = px + net_draw
    surplus_h_a = net_draw
    if p1 + p2 > 0:
        p1_new = p1 - surplus_h_a * (p1 / (p1 + p2))
        p2_new = p2 - surplus_h_a * (p2 / (p1 + p2))
    else:
        p1_new = p1
        p2_new = p2

    if fav_boost > 0:
        if delta_elo >= 0:
            p1_new += fav_boost
            px_new -= fav_boost * 0.7
            p2_new -= fav_boost * 0.3
        else:
            p2_new += fav_boost
            px_new -= fav_boost * 0.7
            p1_new -= fav_boost * 0.3

    p1_new = max(p1_new, 0.005)
    p2_new = max(p2_new, 0.005)
    px_new = max(px_new, 0.005)
    total = p1_new + px_new + p2_new
    return p1_new / total, px_new / total, p2_new / total


def _build_elo_map(forced_weight=None, pin_weight=None):
    elo_base = fetch_elorating_base()
    all_elo = compute_all_nations_elo(elorating_base=elo_base, forced_weight=forced_weight, pin_weight=pin_weight)
    return {r["code"]: r["elo"] for r in all_elo}


def simulate_match_1x2(elo_h, elo_a, home_code=None, away_code=None, phase="G"):
    delta = elo_h - elo_a
    elo_avg = (elo_h + elo_a) / 2
    ph, pd, pa = sigmoid_v8_1x2(delta, elo_avg=elo_avg, phase=phase)
    r = random.random()
    if r < ph:
        return "H"
    elif r < ph + pd:
        return "D"
    else:
        return "A"


def simulate_match_goals(elo_h, elo_a, home_code=None, away_code=None):
    delta = elo_h - elo_a
    base = 1.25
    factor = delta / 600.0
    lambda_h = base * math.exp(factor * 0.5)
    lambda_a = base * math.exp(-factor * 0.5)
    lambda_h = max(0.3, min(lambda_h, 4.0))
    lambda_a = max(0.3, min(lambda_a, 4.0))

    def poisson_sample(lam):
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= random.random()
            if p < L:
                return k - 1

    return poisson_sample(lambda_h), poisson_sample(lambda_a)


def simulate_knockout_match(elo_h, elo_a, home_code=None, away_code=None):
    gh, ga = simulate_match_goals(elo_h, elo_a, home_code, away_code)
    if gh != ga:
        return ("H", gh, ga) if gh > ga else ("A", gh, ga)
    delta = elo_h - elo_a
    pk = max(0.15, min(0.85, 0.5 + delta / 1200.0))
    if random.random() < pk:
        return ("H", gh + 1, ga)
    else:
        return ("A", gh, ga + 1)


def _rank_group(standings):
    def sort_key(item):
        code, s = item
        return (-s["pts"], -(s["gf"] - s["ga"]), -s["gf"])
    return sorted(standings.items(), key=sort_key)


def _pick_best_thirds(group_results, n=8):
    thirds = []
    for grp_letter, ranked in group_results.items():
        if len(ranked) >= 3:
            code = ranked[2][0]
            s = ranked[2][1]
            thirds.append((grp_letter, code, s))

    def sort_key(item):
        _, _, s = item
        return (-s["pts"], -(s["gf"] - s["ga"]), -s["gf"])
    thirds.sort(key=sort_key)
    return thirds[:n]


def _resolve_3rd_slot(slot_groups, qualified_thirds):
    qualified_group_letters = sorted([t[0] for t in qualified_thirds])
    for t in qualified_thirds:
        grp_letter = t[0]
        if grp_letter in slot_groups.split("/"):
            return t[1]
    for t in qualified_thirds:
        return t[1]
    return None


def simulate_tournament(elo_map, params=None):
    tracker = defaultdict(lambda: {
        "group_pos": 0, "group_pts": 0,
        "r32": False, "r16": False, "qf": False,
        "sf": False, "final": False, "winner": False,
    })

    group_results = {}

    for grp_letter, teams in WC2026_GROUPS.items():
        standings = {}
        for code in teams:
            standings[code] = {"pts": 0, "gf": 0, "ga": 0, "w": 0, "d": 0, "l": 0}

        for md_name, pairings in GROUP_MATCHES.items():
            for i_h, i_a in pairings:
                h_code = teams[i_h]
                a_code = teams[i_a]
                elo_h = elo_map.get(h_code, 1500)
                elo_a = elo_map.get(a_code, 1500)
                gh, ga = simulate_match_goals(elo_h, elo_a, h_code, a_code)

                standings[h_code]["gf"] += gh
                standings[h_code]["ga"] += ga
                standings[a_code]["gf"] += ga
                standings[a_code]["ga"] += gh

                if gh > ga:
                    standings[h_code]["pts"] += 3
                    standings[h_code]["w"] += 1
                    standings[a_code]["l"] += 1
                elif gh == ga:
                    standings[h_code]["pts"] += 1
                    standings[a_code]["pts"] += 1
                    standings[h_code]["d"] += 1
                    standings[a_code]["d"] += 1
                else:
                    standings[a_code]["pts"] += 3
                    standings[a_code]["w"] += 1
                    standings[h_code]["l"] += 1

        ranked = _rank_group(standings)
        group_results[grp_letter] = ranked

        for pos, (code, s) in enumerate(ranked):
            tracker[code]["group_pos"] = pos + 1
            tracker[code]["group_pts"] = s["pts"]

    best_thirds = _pick_best_thirds(group_results, n=8)
    qualified_thirds_map = {t[1]: t[0] for t in best_thirds}

    for grp_letter, ranked in group_results.items():
        if len(ranked) >= 1:
            tracker[ranked[0][0]]["r32"] = True
        if len(ranked) >= 2:
            tracker[ranked[1][0]]["r32"] = True
    for t in best_thirds:
        tracker[t[1]]["r32"] = True

    group_winners = {}
    group_runners = {}
    for grp_letter, ranked in group_results.items():
        group_winners[grp_letter] = ranked[0][0]
        group_runners[grp_letter] = ranked[1][0]

    r32_results = {}
    for slot in R32_BRACKET:
        mn = slot["match"]
        h_type, h_grp = slot["home"]
        a_type, a_grp = slot["away"]

        if h_type == "1":
            h_code = group_winners[h_grp]
        elif h_type == "2":
            h_code = group_runners[h_grp]
        elif h_type == "3rd":
            h_code = _resolve_3rd_slot(h_grp, best_thirds)
        else:
            h_code = group_winners.get(h_grp, "UNK")

        if a_type == "1":
            a_code = group_winners[a_grp]
        elif a_type == "2":
            a_code = group_runners[a_grp]
        elif a_type == "3rd":
            a_code = _resolve_3rd_slot(a_grp, best_thirds)
        else:
            a_code = group_winners.get(a_grp, "UNK")

        if h_code is None:
            h_code = "UNK"
        if a_code is None:
            a_code = "UNK"

        elo_h = elo_map.get(h_code, 1500)
        elo_a = elo_map.get(a_code, 1500)
        result, _, _ = simulate_knockout_match(elo_h, elo_a, h_code, a_code)
        winner = h_code if result == "H" else a_code
        r32_results[mn] = winner

    r16_winners = []
    for m1, m2 in R16_PAIRINGS:
        h_code = r32_results[m1]
        a_code = r32_results[m2]
        tracker[h_code]["r16"] = True
        tracker[a_code]["r16"] = True
        elo_h = elo_map.get(h_code, 1500)
        elo_a = elo_map.get(a_code, 1500)
        result, _, _ = simulate_knockout_match(elo_h, elo_a, h_code, a_code)
        winner = h_code if result == "H" else a_code
        r16_winners.append(winner)

    qf_winners = []
    for i, (m1, m2) in enumerate(QF_PAIRINGS):
        h_code = r16_winners[m1]
        a_code = r16_winners[m2]
        tracker[h_code]["qf"] = True
        tracker[a_code]["qf"] = True
        elo_h = elo_map.get(h_code, 1500)
        elo_a = elo_map.get(a_code, 1500)
        result, _, _ = simulate_knockout_match(elo_h, elo_a, h_code, a_code)
        winner = h_code if result == "H" else a_code
        qf_winners.append(winner)

    sf_winners = []
    sf_losers = []
    for m1, m2 in SF_PAIRINGS:
        h_code = qf_winners[m1]
        a_code = qf_winners[m2]
        tracker[h_code]["sf"] = True
        tracker[a_code]["sf"] = True
        elo_h = elo_map.get(h_code, 1500)
        elo_a = elo_map.get(a_code, 1500)
        result, _, _ = simulate_knockout_match(elo_h, elo_a, h_code, a_code)
        winner = h_code if result == "H" else a_code
        loser = a_code if result == "H" else h_code
        sf_winners.append(winner)
        sf_losers.append(loser)

    f_h = sf_winners[0]
    f_a = sf_winners[1]
    tracker[f_h]["final"] = True
    tracker[f_a]["final"] = True
    elo_h = elo_map.get(f_h, 1500)
    elo_a = elo_map.get(f_a, 1500)
    result, _, _ = simulate_knockout_match(elo_h, elo_a, f_h, f_a)
    champion = f_h if result == "H" else f_a
    tracker[champion]["winner"] = True

    return dict(tracker)


def run_simulation(n_sims=10000, params=None):
    elo_map = _build_elo_map()

    agg = defaultdict(lambda: {
        "group_pts_total": 0,
        "group_pos_counts": defaultdict(int),
        "r32": 0, "r16": 0, "qf": 0, "sf": 0, "final": 0, "winner": 0,
    })

    for _ in range(n_sims):
        result = simulate_tournament(elo_map, params)
        for code, data in result.items():
            a = agg[code]
            a["group_pts_total"] += data["group_pts"]
            a["group_pos_counts"][data["group_pos"]] += 1
            for stage in ["r32", "r16", "qf", "sf", "final", "winner"]:
                if data[stage]:
                    a[stage] += 1

    output = []
    for code, a in agg.items():
        nation = get_nation_by_code(code)
        if not nation:
            continue
        grp = None
        for g, teams in WC2026_GROUPS.items():
            if code in teams:
                grp = g
                break

        output.append({
            "code": code,
            "name": nation["name"],
            "fr": nation["fr"],
            "group": grp,
            "elo": elo_map.get(code, 1500),
            "avg_pts": a["group_pts_total"] / n_sims,
            "p_1st": a["group_pos_counts"].get(1, 0) / n_sims * 100,
            "p_2nd": a["group_pos_counts"].get(2, 0) / n_sims * 100,
            "p_3rd": a["group_pos_counts"].get(3, 0) / n_sims * 100,
            "p_4th": a["group_pos_counts"].get(4, 0) / n_sims * 100,
            "p_r32": a["r32"] / n_sims * 100,
            "p_r16": a["r16"] / n_sims * 100,
            "p_qf": a["qf"] / n_sims * 100,
            "p_sf": a["sf"] / n_sims * 100,
            "p_final": a["final"] / n_sims * 100,
            "p_winner": a["winner"] / n_sims * 100,
        })

    output.sort(key=lambda x: -x["p_winner"])
    return output


def get_group_predictions(elo_map=None, params=None):
    if elo_map is None:
        elo_map = _build_elo_map()
    results = {}
    for grp_letter, teams in WC2026_GROUPS.items():
        matches = []
        for md_name, pairings in GROUP_MATCHES.items():
            for i_h, i_a in pairings:
                h_code = teams[i_h]
                a_code = teams[i_a]
                elo_h = elo_map.get(h_code, 1500)
                elo_a = elo_map.get(a_code, 1500)
                delta = elo_h - elo_a
                ea = (elo_h + elo_a) / 2
                ph, pd, pa = sigmoid_v8_1x2(delta, elo_avg=ea, phase="G")
                nation_h = get_nation_by_code(h_code)
                nation_a = get_nation_by_code(a_code)
                matches.append({
                    "md": md_name,
                    "home_code": h_code,
                    "away_code": a_code,
                    "home_fr": nation_h["fr"] if nation_h else h_code,
                    "away_fr": nation_a["fr"] if nation_a else a_code,
                    "elo_h": elo_h,
                    "elo_a": elo_a,
                    "delta": delta,
                    "p_home": ph * 100,
                    "p_draw": pd * 100,
                    "p_away": pa * 100,
                    "odds_home": 1 / ph if ph > 0.01 else 99,
                    "odds_draw": 1 / pd if pd > 0.01 else 99,
                    "odds_away": 1 / pa if pa > 0.01 else 99,
                })
        results[grp_letter] = matches
    return results
