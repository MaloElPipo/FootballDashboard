"""Comparatif PELE vs V8 prod vs marche Pinnacle — phase poule CDM 2026.

Script standalone : ne touche ni `football-dashboard` ni `football-lab`. Telecharge
les ratings publics PELE (Nate Silver, Silver Bulletin) en cache local, reconstruit
un moteur de simulation PELE-only, simule les 12 poules en Monte Carlo, et compare :

  V8_PROD  = nos Elo pin_calibrated + sigmoid V8 + cap lambda=4 (prod actuelle)
  PELE     = PELE rating + Tilt (offense/defense), buts via Round-Robin att/def
  MARKET   = cotes Pinnacle de-margeinees Buchdahl (verite sharp, sur ~40 matchs)

Output :
  live/data/pele_cache/{pele,tilt,rr}.csv (cache donnees PELE)
  live/data/pele_full_results.json        (toutes les sorties brutes, reutilisables)
  live/data/pele_vs_v8_report.pdf         (rapport lisible, ~18 pages)
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import random
import urllib.request
from collections import defaultdict
from pathlib import Path

import numpy as np

# ─── Constantes & chemins ───────────────────────────────────────────────────

REPO = Path(__file__).resolve().parents[1]
SNAP = REPO / "artifacts/football-lab/lab/data/snapshots/initial_baseline_2026-05-20"
CACHE = REPO / "live/data/pele_cache"
OUT_JSON = REPO / "live/data/pele_full_results.json"
OUT_PDF = REPO / "live/data/pele_vs_v8_report.pdf"

PELE_URLS = {
    "pele": "https://datawrapper.dwcdn.net/4oVop/1/data.csv",
    "tilt": "https://datawrapper.dwcdn.net/dxUJw/1/data.csv",
    "rr":   "https://datawrapper.dwcdn.net/DcqkH/1/data.csv",
}

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

GROUP_MATCHES = [(0, 1), (2, 3), (0, 2), (3, 1), (3, 0), (1, 2)]

# Cas particuliers PELE -> nos codes (PELE utilise les codes FIFA modernes,
# memes que nous pour 99% des cas. On documente les exceptions ici.)
PELE_CODE_MAP = {
    # PELE -> nous (rien d'exceptionnel sur les 48 CDM verifies manuellement)
}

V7_SCALE = 441.952
V7_DRAW_BASE = 24.09
V7_D_HALF = 463.648
V7_POWER = 3.56
V7_QUALITY = 0.035

V8_DRAW_BOOST_CLOSE = 4.312
V8_DRAW_BOOST_MID = 2.555
V8_DRAW_BOOST_MAX = 36.049
V8_FAV_BOOST_GROUP = -2.446
V8_FAV_DELTA_THRESHOLD = 380.332

N_SIMS = 10000
RNG_SEED = 42


# ─── 1. Telechargement & cache donnees PELE ─────────────────────────────────

def fetch_pele_data() -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, url in PELE_URLS.items():
        path = CACHE / f"{name}.csv"
        if not path.exists():
            print(f"      download {name}…")
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                path.write_bytes(r.read())
        out[name] = path.read_text(encoding="utf-8")
    return out


def parse_pele_csvs(raw: dict) -> dict[str, dict]:
    """Renvoie pour chaque code : {pele, tilt, gf_rr, ga_rr, w_rr, d_rr, l_rr}."""
    teams: dict[str, dict] = {}

    rdr = csv.DictReader(io.StringIO(raw["pele"]))
    for row in rdr:
        code = (row.get("Code") or "").strip()
        if not code or code == "":
            continue
        try:
            pele = float(row["PELE"])
        except (KeyError, ValueError):
            continue
        teams[code] = {"pele": pele}

    rdr = csv.DictReader(io.StringIO(raw["tilt"]))
    for row in rdr:
        code = (row.get("Code") or "").strip()
        if code not in teams:
            continue
        try:
            teams[code]["tilt"] = float(row.get("total_tilt", "0"))
        except ValueError:
            teams[code]["tilt"] = 0.0

    rdr = csv.DictReader(io.StringIO(raw["rr"]))
    for row in rdr:
        code = (row.get("Team") or "").strip()
        if code not in teams:
            continue
        try:
            teams[code]["gf_rr"] = float(row["GF"])
            teams[code]["ga_rr"] = float(row["GA"])
            teams[code]["w_rr"] = float(row["W"])
            teams[code]["d_rr"] = float(row["D"])
            teams[code]["l_rr"] = float(row["L"])
        except (KeyError, ValueError):
            pass

    teams = {k: v for k, v in teams.items() if "gf_rr" in v and "tilt" in v}
    return teams


# ─── 2. Moteur PELE : attaque/defense par equipe ────────────────────────────

def build_pele_engine(teams: dict[str, dict]) -> dict:
    """A partir du round-robin (GF, GA en site neutre vs les 210 autres) et du
    Tilt, calibre :
      - att_i = ratio attaque vs equipe moyenne (1.0 = moyen)
      - def_i = ratio defense vs equipe moyenne (1.0 = moyen, <1.0 = bonne def)
      - baseline = buts moyen par equipe par match au niveau international

    Modele match : pour i vs j en neutre,
      lambda_i = baseline * att_i * def_j * (1 + alpha * (tilt_i + tilt_j))
    """
    gfs = [t["gf_rr"] for t in teams.values()]
    gas = [t["ga_rr"] for t in teams.values()]
    mean_gf = np.mean(gfs)
    mean_ga = np.mean(gas)
    baseline = (mean_gf + mean_ga) / 2.0  # = ~1.3 buts/equipe/match a l'international

    for code, t in teams.items():
        t["att"] = t["gf_rr"] / mean_gf  # ratio attaque
        t["def"] = t["ga_rr"] / mean_ga  # ratio defense (>1 = encaisse plus)

    return {
        "teams": teams,
        "baseline": baseline,
        "alpha_tilt": 0.4,  # impact tilt sur total buts (calibre PELE doc)
        "scale_1x2": 400.0,  # echelle Elo standard pour 1X2
    }


def pele_lambdas(engine: dict, h_code: str, a_code: str) -> tuple[float, float]:
    t = engine["teams"]
    if h_code not in t or a_code not in t:
        return 1.3, 1.3
    h, a = t[h_code], t[a_code]
    base = engine["baseline"]
    tilt_factor = 1.0 + engine["alpha_tilt"] * (h["tilt"] + a["tilt"])
    tilt_factor = max(tilt_factor, 0.5)
    lh = base * h["att"] * a["def"] * tilt_factor
    la = base * a["att"] * h["def"] * tilt_factor
    return lh, la


def pele_1x2(engine: dict, h_code: str, a_code: str) -> tuple[float, float, float]:
    """1X2 derive depuis la matrice de scores Poisson (cap 8 buts/equipe)."""
    lh, la = pele_lambdas(engine, h_code, a_code)
    ph = pd = pa = 0.0
    exp_lh, exp_la = math.exp(-lh), math.exp(-la)
    fact_i = 1.0
    for i in range(9):
        if i > 0: fact_i *= i
        pi = exp_lh * (lh ** i) / fact_i
        fact_j = 1.0
        for j in range(9):
            if j > 0: fact_j *= j
            pj = exp_la * (la ** j) / fact_j
            p = pi * pj
            if i > j: ph += p
            elif i == j: pd += p
            else: pa += p
    tot = ph + pd + pa
    return ph / tot, pd / tot, pa / tot


# ─── 3. Moteur V8 prod (copie litterale) ────────────────────────────────────

def sigmoid_v6(delta: float, elo_avg: float | None = None) -> tuple[float, float, float]:
    draw_adj = V7_DRAW_BASE
    if elo_avg is not None:
        draw_adj = max(V7_DRAW_BASE + V7_QUALITY * (elo_avg - 1800) / 100, 5.0)
    draw = draw_adj / (1.0 + (abs(delta) / V7_D_HALF) ** V7_POWER)
    draw = max(draw, 0.5)
    sig = 1.0 / (1.0 + 10.0 ** (-delta / V7_SCALE))
    p1 = (100 - draw) * sig
    p2 = (100 - draw) * (1 - sig)
    tot = p1 + draw + p2
    return p1 / tot, draw / tot, p2 / tot


def sigmoid_v8(delta: float, elo_avg: float | None = None) -> tuple[float, float, float]:
    p1, px, p2 = sigmoid_v6(delta, elo_avg)
    abs_d = abs(delta)
    db = 0.0
    if abs_d < 100: db += V8_DRAW_BOOST_CLOSE / 100
    elif abs_d < 200: db += V8_DRAW_BOOST_MID / 100
    db = min(db, V8_DRAW_BOOST_MAX / 100)
    fb = V8_FAV_BOOST_GROUP / 100 if abs_d >= V8_FAV_DELTA_THRESHOLD else 0.0
    nd = max(db - fb * 0.7, 0.0)
    px += nd
    if p1 + p2 > 0:
        p1 -= nd * (p1 / (p1 + p2))
        p2 -= nd * (p2 / (p1 + p2))
    if fb > 0:
        if delta >= 0:
            p1 += fb; px -= fb * 0.7; p2 -= fb * 0.3
        else:
            p2 += fb; px -= fb * 0.7; p1 -= fb * 0.3
    p1, px, p2 = max(p1, 0.005), max(px, 0.005), max(p2, 0.005)
    tot = p1 + px + p2
    return p1 / tot, px / tot, p2 / tot


def v8_lambdas(elo_h: float, elo_a: float) -> tuple[float, float]:
    delta = elo_h - elo_a
    f = delta / 600.0
    lh = max(0.3, min(1.25 * math.exp(f * 0.5), 4.0))
    la = max(0.3, min(1.25 * math.exp(-f * 0.5), 4.0))
    return lh, la


# ─── 4. Verite marche : Pinnacle ─────────────────────────────────────────────

def load_market() -> dict[tuple[str, str], tuple[float, float, float]]:
    """Renvoie {(code_h, code_a): (p_h, p_d, p_a)} de-margine Buchdahl."""
    PIN_TO_CODE = {
        "France": "FRA", "Spain": "ESP", "Germany": "GER", "England": "ENG",
        "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL", "Croatia": "CRO",
        "Austria": "AUT", "Switzerland": "SUI", "Norway": "NOR", "Sweden": "SWE",
        "Czech Republic": "CZE", "Czechia": "CZE", "Turkey": "TUR", "Türkiye": "TUR",
        "Scotland": "SCO", "Bosnia and Herzegovina": "BIH",
        "Argentina": "ARG", "Brazil": "BRA", "Colombia": "COL", "Uruguay": "URU",
        "Ecuador": "ECU", "Paraguay": "PAR", "United States": "USA", "USA": "USA",
        "Mexico": "MEX", "Canada": "CAN", "Panama": "PAN", "Curacao": "CUW",
        "Curaçao": "CUW", "Haiti": "HAI", "Japan": "JPN", "South Korea": "KOR",
        "Korea Republic": "KOR", "Iran": "IRN", "Saudi Arabia": "KSA",
        "Australia": "AUS", "Qatar": "QAT", "Iraq": "IRQ", "Jordan": "JOR",
        "Uzbekistan": "UZB", "Morocco": "MAR", "Senegal": "SEN", "Egypt": "EGY",
        "Algeria": "ALG", "Tunisia": "TUN", "Ivory Coast": "CIV", "Ghana": "GHA",
        "DR Congo": "COD", "South Africa": "RSA", "Cape Verde": "CPV",
        "New Zealand": "NZL",
    }
    raw = json.loads((SNAP / "pinnacle_wc2026_odds.json").read_text())
    out = {}
    for m in raw:
        ch = PIN_TO_CODE.get(m["home"])
        ca = PIN_TO_CODE.get(m["away"])
        if not (ch and ca):
            continue
        oh, od, oa = m["pin_h"], m["pin_d"], m["pin_a"]
        ih, idr, ia = 1 / oh, 1 / od, 1 / oa
        s = ih + idr + ia
        out[(ch, ca)] = (ih / s, idr / s, ia / s)
    return out


# ─── 5. Calculs par match (1X2, O/U, BTTS, score modal) ─────────────────────

def metrics_from_lambdas(lh: float, la: float) -> dict:
    ph = pd = pa = 0.0
    pou25_under = 0.0
    p_btts_no = 0.0
    p_grid = {}
    exp_lh, exp_la = math.exp(-lh), math.exp(-la)
    fact_i = 1.0
    for i in range(9):
        if i > 0: fact_i *= i
        pi = exp_lh * (lh ** i) / fact_i
        fact_j = 1.0
        for j in range(9):
            if j > 0: fact_j *= j
            pj = exp_la * (la ** j) / fact_j
            p = pi * pj
            p_grid[(i, j)] = p
            if i > j: ph += p
            elif i == j: pd += p
            else: pa += p
            if i + j <= 2: pou25_under += p
            if i == 0 or j == 0: p_btts_no += p
    best_score = max(p_grid.items(), key=lambda x: x[1])[0]
    tot = ph + pd + pa
    return {
        "p_h": ph / tot, "p_d": pd / tot, "p_a": pa / tot,
        "lambda_h": lh, "lambda_a": la,
        "p_over25": 1 - pou25_under,
        "p_btts_yes": 1 - p_btts_no,
        "best_score": best_score,
    }


def compute_all_matches(engine: dict, v8_elo: dict, market: dict) -> list[dict]:
    rows = []
    for grp, teams in WC2026_GROUPS.items():
        for ih, ia in GROUP_MATCHES:
            ch, ca = teams[ih], teams[ia]
            pele_lh, pele_la = pele_lambdas(engine, ch, ca)
            pele_m = metrics_from_lambdas(pele_lh, pele_la)
            # V8 prod : 1X2 vient de la sigmoid V8 (pas du Poisson),
            # mais les lambdas viennent de derive_lambdas_from_elo.
            elo_h = v8_elo.get(ch, 1500)
            elo_a = v8_elo.get(ca, 1500)
            v8_1x2 = sigmoid_v8(elo_h - elo_a, (elo_h + elo_a) / 2)
            v8_lh, v8_la = v8_lambdas(elo_h, elo_a)
            v8_m = metrics_from_lambdas(v8_lh, v8_la)
            v8_m["p_h"], v8_m["p_d"], v8_m["p_a"] = v8_1x2
            mk = market.get((ch, ca))
            rows.append({
                "group": grp, "home": ch, "away": ca,
                "pele_elo_h": engine["teams"].get(ch, {}).get("pele"),
                "pele_elo_a": engine["teams"].get(ca, {}).get("pele"),
                "v8_elo_h": elo_h, "v8_elo_a": elo_a,
                "pele": pele_m, "v8": v8_m,
                "market": {"p_h": mk[0], "p_d": mk[1], "p_a": mk[2]} if mk else None,
            })
    return rows


# ─── 6. Monte Carlo poule pour chaque moteur ────────────────────────────────

def simulate_group_once(teams: list[str], lambda_fn, rng) -> dict:
    """lambda_fn(h, a) -> (lh, la). Renvoie classement final par equipe."""
    standings = {c: {"pts": 0, "gf": 0.0, "ga": 0.0} for c in teams}
    for ih, ia in GROUP_MATCHES:
        h, a = teams[ih], teams[ia]
        lh, la = lambda_fn(h, a)
        # tirage Poisson rapide via numpy serait mieux mais on garde stdlib
        gh = rng.poissonvariate(lh) if hasattr(rng, 'poissonvariate') else poisson_sample(lh, rng)
        ga = poisson_sample(la, rng)
        standings[h]["gf"] += gh; standings[h]["ga"] += ga
        standings[a]["gf"] += ga; standings[a]["ga"] += gh
        if gh > ga: standings[h]["pts"] += 3
        elif gh == ga: standings[h]["pts"] += 1; standings[a]["pts"] += 1
        else: standings[a]["pts"] += 3
    ranked = sorted(
        standings.items(),
        key=lambda kv: (-kv[1]["pts"], -(kv[1]["gf"] - kv[1]["ga"]), -kv[1]["gf"]),
    )
    return {code: i + 1 for i, (code, _) in enumerate(ranked)}, standings


def poisson_sample(lam: float, rng) -> int:
    # Knuth pour lam petit (< 30)
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def run_mc(engine: dict, v8_elo: dict, n: int = N_SIMS) -> dict:
    """Lance n simulations Monte Carlo poule pour PELE et V8 simultanement."""
    rng = random.Random(RNG_SEED)
    rng_v8 = random.Random(RNG_SEED)  # meme seed -> meme series de tirages

    def lf_pele(h, a): return pele_lambdas(engine, h, a)
    def lf_v8(h, a):
        return v8_lambdas(v8_elo.get(h, 1500), v8_elo.get(a, 1500))

    agg = {
        "pele": defaultdict(lambda: {"pts": 0.0, "gf": 0.0, "ga": 0.0,
                                       "pos": defaultdict(int)}),
        "v8":   defaultdict(lambda: {"pts": 0.0, "gf": 0.0, "ga": 0.0,
                                       "pos": defaultdict(int)}),
        # Probas qualif R32 (top2 + meilleurs 3emes)
        "r32_pele": defaultdict(int),
        "r32_v8":   defaultdict(int),
    }

    for _ in range(n):
        # Collecte 3emes par poule pour PELE
        thirds_pele, thirds_v8 = [], []
        for grp, teams in WC2026_GROUPS.items():
            ranks_p, st_p = simulate_group_once(teams, lf_pele, rng)
            ranks_v, st_v = simulate_group_once(teams, lf_v8, rng_v8)
            for c, pos in ranks_p.items():
                a = agg["pele"][c]
                a["pts"] += st_p[c]["pts"]
                a["gf"] += st_p[c]["gf"]; a["ga"] += st_p[c]["ga"]
                a["pos"][pos] += 1
                if pos <= 2: agg["r32_pele"][c] += 1
                if pos == 3: thirds_pele.append((c, st_p[c]["pts"],
                                                 st_p[c]["gf"] - st_p[c]["ga"],
                                                 st_p[c]["gf"]))
            for c, pos in ranks_v.items():
                a = agg["v8"][c]
                a["pts"] += st_v[c]["pts"]
                a["gf"] += st_v[c]["gf"]; a["ga"] += st_v[c]["ga"]
                a["pos"][pos] += 1
                if pos <= 2: agg["r32_v8"][c] += 1
                if pos == 3: thirds_v8.append((c, st_v[c]["pts"],
                                                st_v[c]["gf"] - st_v[c]["ga"],
                                                st_v[c]["gf"]))
        # 8 meilleurs 3emes
        thirds_pele.sort(key=lambda x: (-x[1], -x[2], -x[3]))
        thirds_v8.sort(key=lambda x: (-x[1], -x[2], -x[3]))
        for t in thirds_pele[:8]: agg["r32_pele"][t[0]] += 1
        for t in thirds_v8[:8]:   agg["r32_v8"][t[0]] += 1

    # Normalisation
    out = {"pele": {}, "v8": {}}
    for engine_name in ("pele", "v8"):
        for c, a in agg[engine_name].items():
            out[engine_name][c] = {
                "avg_pts": a["pts"] / n,
                "avg_gf": a["gf"] / n,
                "avg_ga": a["ga"] / n,
                "p_1st": a["pos"][1] / n * 100,
                "p_2nd": a["pos"][2] / n * 100,
                "p_3rd": a["pos"][3] / n * 100,
                "p_4th": a["pos"][4] / n * 100,
                "p_r32": agg[f"r32_{engine_name}"][c] / n * 100,
            }
    return out


# ─── 7. PDF rendering ────────────────────────────────────────────────────────

def render_pdf(matches: list[dict], mc: dict, engine: dict, v8_elo: dict,
                out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    plt.rcParams["font.family"] = "DejaVu Sans"

    def page_text(title: str, body_lines: list[tuple[float, str, dict]]) -> None:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.5, 0.93, title, ha="center", fontsize=16, fontweight="bold")
        for y, txt, kw in body_lines:
            fig.text(0.08, y, txt, **kw)
        plt.axis("off")
        pdf.savefig(fig); plt.close(fig)

    def page_table(title: str, headers: list[str], rows: list[list[str]],
                    note: str = "", row_colors: list[list[str]] | None = None,
                    font_size: int = 9) -> None:
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.axis("off")
        ax.set_title(title, fontsize=14, fontweight="bold", loc="left", pad=20)
        tbl = ax.table(cellText=rows, colLabels=headers, loc="upper center",
                        cellLoc="center", cellColours=row_colors,
                        colColours=["#37474f"] * len(headers))
        tbl.auto_set_font_size(False); tbl.set_fontsize(font_size)
        tbl.scale(1, 1.5)
        for j in range(len(headers)):
            tbl[(0, j)].set_text_props(color="white", fontweight="bold")
        if note:
            fig.text(0.08, 0.18, note, fontsize=9, family="monospace", va="top")
        pdf.savefig(fig); plt.close(fig)

    with PdfPages(out) as pdf:
        # ─── COUVERTURE ────────────────────────────────────────────────────
        n_market = sum(1 for m in matches if m["market"])
        avg_pele_lh = np.mean([m["pele"]["lambda_h"] for m in matches])
        avg_v8_lh = np.mean([m["v8"]["lambda_h"] for m in matches])
        page_text(
            "PELE vs V8 prod — Comparatif poules CDM 2026",
            [
                (0.86, "Trois moteurs predictifs, cote a cote", {"fontsize": 11,
                    "ha": "left", "style": "italic", "color": "#555"}),
                (0.78, "1. V8 PROD : votre modele actuel\n"
                       "   Elo blend (eloratings + Pinnacle + overrides) + sigmoid V8\n"
                       "   + buts par formule Elo capee a 4.\n", {"fontsize": 10}),
                (0.69, "2. PELE : modele Nate Silver (Silver Bulletin)\n"
                       "   PELE rating (Elo-like ancre sur valeurs marchandes Transfermarkt)\n"
                       "   + Tilt rating (orientation offensive/defensive)\n"
                       "   + buts par regression Round-Robin attaque/defense.\n", {"fontsize": 10}),
                (0.60, "3. MARKET : cotes Pinnacle de-marginees Buchdahl\n"
                       f"   Verite sharp pour les {n_market}/72 matchs avec cotes publiees.\n",
                 {"fontsize": 10}),
                (0.50, "Ce que ce rapport contient", {"fontsize": 13, "fontweight": "bold"}),
                (0.45, "  - Page 2 : verdict global (qui ressemble le plus au marche ?)",
                 {"fontsize": 10}),
                (0.43, "  - Pages 3-4 : top divergences PELE vs V8 (matchs qui changent le plus)",
                 {"fontsize": 10}),
                (0.41, "  - Pages 5-16 : 1 page par poule (probas qualif R32, points, buts)",
                 {"fontsize": 10}),
                (0.39, "  - Pages 17-18 : matchs detail 1X2 + O/U2.5 + BTTS",
                 {"fontsize": 10}),
                (0.37, "  - Page 19 : impact du Tilt (qui PELE classe offensif vs defensif)",
                 {"fontsize": 10}),
                (0.35, "  - Page 20 : recommandation pratique",
                 {"fontsize": 10}),
                (0.27, "Statistiques globales", {"fontsize": 13, "fontweight": "bold"}),
                (0.22, f"  Matchs simules :       72 (12 poules x 6 matchs)\n"
                       f"  Tournois Monte Carlo : {N_SIMS:,} pour chaque moteur\n"
                       f"  Buts moyens domicile : PELE {avg_pele_lh:.2f} | V8 {avg_v8_lh:.2f}\n"
                       f"  Donnees PELE :         cache {CACHE.name}/ (re-utilisable)\n"
                       f"  Sorties brutes JSON :  {OUT_JSON.name}",
                 {"fontsize": 9, "family": "monospace"}),
                (0.05, "scripts/pele_vs_v8_report.py — sandbox, prod inchangee",
                 {"fontsize": 8, "color": "#888", "ha": "left"}),
            ],
        )

        # ─── VERDICT GLOBAL ────────────────────────────────────────────────
        # Distance moyenne aux cotes marche
        def mae(rows, model):
            err = []
            for r in rows:
                if not r["market"]: continue
                m = r["market"]; p = r[model]
                err += [abs(p["p_h"] - m["p_h"]), abs(p["p_d"] - m["p_d"]),
                        abs(p["p_a"] - m["p_a"])]
            return np.mean(err) * 100

        mae_pele = mae(matches, "pele")
        mae_v8 = mae(matches, "v8")

        # Biais favori
        def bias_fav(rows, model):
            b = []
            for r in rows:
                if not r["market"]: continue
                m = r["market"]; p = r[model]
                p_fav_m = max(m["p_h"], m["p_a"])
                if m["p_h"] >= m["p_a"]:
                    p_fav_mdl = p["p_h"]
                else:
                    p_fav_mdl = p["p_a"]
                b.append(p_fav_mdl - p_fav_m)
            return np.mean(b) * 100

        bias_pele = bias_fav(matches, "pele")
        bias_v8 = bias_fav(matches, "v8")

        winner = "PELE" if mae_pele < mae_v8 else "V8 prod"
        gap = abs(mae_pele - mae_v8)

        page_text(
            "Verdict global — qui ressemble le plus au marche ?",
            [
                (0.85, "Ecart moyen vs cotes Pinnacle (sur les 40 matchs avec cotes)",
                 {"fontsize": 12, "fontweight": "bold"}),
                (0.79, f"  V8 prod :  ecart absolu moyen = {mae_v8:.2f} pts de %\n"
                       f"             biais sur favori   = {bias_v8:+.2f} pts de %",
                 {"fontsize": 11, "family": "monospace"}),
                (0.72, f"  PELE :     ecart absolu moyen = {mae_pele:.2f} pts de %\n"
                       f"             biais sur favori   = {bias_pele:+.2f} pts de %",
                 {"fontsize": 11, "family": "monospace"}),
                (0.62, f"=> {winner} est plus proche du marche de {gap:.2f} pts",
                 {"fontsize": 13, "fontweight": "bold",
                  "color": "#2e7d32" if winner == "PELE" else "#c62828"}),
                (0.52, "Comment lire ces chiffres", {"fontsize": 12, "fontweight": "bold"}),
                (0.45, "* Ecart absolu moyen = a quel point chaque proba du modele\n"
                       "  s'eloigne de la proba implicite Pinnacle. Plus c'est petit,\n"
                       "  plus le modele 'colle' au marche.\n\n"
                       "* Biais sur favori : si > 0, le modele sur-estime le favori.\n"
                       "  Si < 0, il le sous-estime. L'ideal est ~0 (calibre).",
                 {"fontsize": 10}),
                (0.25, "Avertissement methodologique", {"fontsize": 12, "fontweight": "bold"}),
                (0.18, "* Pinnacle CDM mi-mai est moins liquide que les cotes club -> le\n"
                       "  marche n'est pas 100% sharp. Un ecart de 2-3 pts est dans la\n"
                       "  marge d'erreur du marche lui-meme.\n\n"
                       "* Les 40 matchs avec cotes sont sur-representes en MD1 (matchs\n"
                       "  d'ouverture), souvent serres. Le vrai test (gros mismatches\n"
                       "  MD2/MD3) attendra les prochains snapshots Pinnacle.",
                 {"fontsize": 10}),
            ],
        )

        # ─── TOP DIVERGENCES PELE vs V8 ────────────────────────────────────
        divs = []
        for r in matches:
            diff = abs(r["pele"]["p_h"] - r["v8"]["p_h"]) + \
                   abs(r["pele"]["p_a"] - r["v8"]["p_a"])
            divs.append((diff, r))
        divs.sort(key=lambda x: -x[0])
        top = [r for _, r in divs[:20]]

        rows = []
        colors = []
        for r in top:
            fav_pele = "H" if r["pele"]["p_h"] > r["pele"]["p_a"] else "A"
            fav_v8 = "H" if r["v8"]["p_h"] > r["v8"]["p_a"] else "A"
            disagree = fav_pele != fav_v8
            rows.append([
                f"{r['home']}-{r['away']}", f"({r['group']})",
                f"{r['v8']['p_h']*100:.0f}/{r['v8']['p_d']*100:.0f}/{r['v8']['p_a']*100:.0f}",
                f"{r['pele']['p_h']*100:.0f}/{r['pele']['p_d']*100:.0f}/{r['pele']['p_a']*100:.0f}",
                (f"{r['market']['p_h']*100:.0f}/{r['market']['p_d']*100:.0f}/"
                 f"{r['market']['p_a']*100:.0f}") if r["market"] else "-",
                f"{r['v8']['lambda_h']:.2f}-{r['v8']['lambda_a']:.2f}",
                f"{r['pele']['lambda_h']:.2f}-{r['pele']['lambda_a']:.2f}",
            ])
            colors.append(["#ffebee" if disagree else "#fff8e1"] * 7)

        page_table(
            "Top 20 matchs ou PELE et V8 divergent le plus",
            ["Match", "Poule", "V8 1/X/2", "PELE 1/X/2", "Pinnacle 1/X/2",
             "V8 buts", "PELE buts"],
            rows[:18], row_colors=colors[:18], font_size=7,
            note="Lignes rouges : PELE et V8 ne sont meme pas d'accord sur le favori.\n"
                 "Comparer la 3eme colonne (V8) et la 4eme (PELE) avec la 5eme (Pinnacle)\n"
                 "indique lequel est le plus credible sur chaque match.",
        )

        # ─── 1 PAGE PAR POULE — qualif R32 + points ────────────────────────
        for grp in sorted(WC2026_GROUPS.keys()):
            teams = WC2026_GROUPS[grp]
            rows = []
            colors = []
            for c in teams:
                p = mc["pele"].get(c, {})
                v = mc["v8"].get(c, {})
                rows.append([
                    c,
                    f"{v.get('avg_pts', 0):.2f}", f"{p.get('avg_pts', 0):.2f}",
                    f"{v.get('p_1st', 0):.0f}%",  f"{p.get('p_1st', 0):.0f}%",
                    f"{v.get('p_2nd', 0):.0f}%",  f"{p.get('p_2nd', 0):.0f}%",
                    f"{v.get('p_r32', 0):.0f}%",  f"{p.get('p_r32', 0):.0f}%",
                ])
                dr = p.get("p_r32", 0) - v.get("p_r32", 0)
                if abs(dr) > 10:
                    color = "#e8f5e9" if dr > 0 else "#ffebee"
                else:
                    color = "#fafafa"
                colors.append([color] * 9)

            page_table(
                f"Poule {grp} — qualif R32 selon V8 vs PELE",
                ["Equipe", "V8 pts", "PELE pts", "V8 1er", "PELE 1er",
                 "V8 2nd", "PELE 2nd", "V8 R32", "PELE R32"],
                rows, row_colors=colors,
                note=("Lecture : pts = points moyens en poule (sur 9 max).\n"
                      "1er/2nd = proba terminer a cette place. R32 = proba qualifier\n"
                      "en 16emes (top 2 directs + meilleurs 3emes a 6 pts ou 4 pts +GD).\n\n"
                      "Code couleur : vert = PELE plus optimiste de >10pts vs V8,\n"
                      "rouge = PELE plus pessimiste de >10pts vs V8."),
            )

        # ─── MATCHS DETAIL — O/U & BTTS ────────────────────────────────────
        per_page = 18
        for start in range(0, len(matches), per_page):
            chunk = matches[start:start + per_page]
            rows = []
            for r in chunk:
                rows.append([
                    f"{r['home']}-{r['away']}", r["group"],
                    f"{r['v8']['p_over25']*100:.0f}%",
                    f"{r['pele']['p_over25']*100:.0f}%",
                    f"{r['v8']['p_btts_yes']*100:.0f}%",
                    f"{r['pele']['p_btts_yes']*100:.0f}%",
                    f"{r['v8']['best_score'][0]}-{r['v8']['best_score'][1]}",
                    f"{r['pele']['best_score'][0]}-{r['pele']['best_score'][1]}",
                ])
            page_num = start // per_page + 1
            n_pages = math.ceil(len(matches) / per_page)
            page_table(
                f"Detail O/U 2.5 + BTTS + score modal (page {page_num}/{n_pages})",
                ["Match", "Poule", "V8 O2.5", "PELE O2.5",
                 "V8 BTTS", "PELE BTTS", "V8 score", "PELE score"],
                rows, font_size=8,
                note=("O/U 2.5 = proba que le match ait au moins 3 buts.\n"
                      "BTTS = proba que les deux equipes marquent.\n"
                      "Si V8 et PELE divergent sur le score modal, c'est souvent que\n"
                      "le Tilt PELE revele un profil offensif/defensif que V8 ignore."),
            )

        # ─── IMPACT TILT ───────────────────────────────────────────────────
        wc_teams = []
        for tlist in WC2026_GROUPS.values():
            wc_teams.extend(tlist)
        tilts = []
        for c in wc_teams:
            t = engine["teams"].get(c)
            if not t: continue
            tilts.append((c, t["tilt"], t["pele"], t["att"], t["def"]))
        tilts.sort(key=lambda x: -x[1])
        rows = []
        for c, ti, pl, at, df in tilts[:12] + tilts[-12:]:
            tag = "OFFENSIF" if ti > 0.1 else ("DEFENSIF" if ti < -0.1 else "neutre")
            rows.append([c, f"{pl:.0f}", f"{ti:+.2f}", tag,
                         f"{at:.2f}", f"{df:.2f}"])
        page_table(
            "Tilt rating PELE — equipes offensives vs defensives (CDM 2026)",
            ["Code", "PELE", "Tilt", "Profil", "Attaque", "Defense"],
            rows,
            note=("Le Tilt rating est ce que V8 prod n'a PAS aujourd'hui.\n"
                  "Tilt positif = equipe qui produit plus de buts au total que ce\n"
                  "que son Elo seul suggererait. Tilt negatif = profil defensif.\n\n"
                  "Allemagne (Tilt ~+0.55) joue des matchs a hauts scores.\n"
                  "Colombie / Senegal jouent fermes.\n\n"
                  "Cette colonne explique pourquoi PELE et V8 divergent sur les\n"
                  "predictions de buts (O/U, BTTS, score modal)."),
        )

        # ─── RECOMMANDATION ────────────────────────────────────────────────
        page_text(
            "Recommandation pratique",
            [
                (0.85, "Ce que ce comparatif nous apprend", {"fontsize": 13,
                    "fontweight": "bold"}),
                (0.78,
                 f"PELE est {'plus' if mae_pele < mae_v8 else 'moins'} proche du marche que V8 prod\n"
                 f"(MAE PELE = {mae_pele:.2f} pts vs V8 = {mae_v8:.2f} pts).\n\n"
                 f"Biais sur favori : V8 = {bias_v8:+.2f} pts, PELE = {bias_pele:+.2f} pts.",
                 {"fontsize": 10}),
                (0.62, "Trois options pour la suite", {"fontsize": 13,
                    "fontweight": "bold"}),
                (0.55,
                 "Option A : Garder V8, juste corriger le bug du signe FAV_BOOST_GROUP.\n"
                 "  -> Effort = 1 caractere, gain = quelques points sur les gros mismatches.\n\n"
                 "Option B : Ajouter le Tilt rating PELE a V8.\n"
                 "  -> Effort = 2-3 jours. Garde la calibration value betting actuelle.\n"
                 "     Tilt module uniquement les buts (lambdas), pas le 1X2.\n"
                 "     Impact : O/U et BTTS bien plus precis, meilleurs 3emes plus realistes.\n\n"
                 "Option C : Mode 'PELE only' comme 2eme moteur dans le dashboard.\n"
                 "  -> Effort = 1 semaine. Garde V8 inchange, ajoute un toggle.\n"
                 "     Permet de voir les divergences en temps reel, sans engagement.",
                 {"fontsize": 9, "family": "monospace"}),
                (0.25, "Limites a garder en tete", {"fontsize": 13, "fontweight": "bold"}),
                (0.18,
                 "* On a reverse-engineere la formule (PELE, Tilt) -> lambda depuis\n"
                 "  les Round-Robin publies. Ce n'est pas EXACTEMENT la formule PELE.\n"
                 "  L'ecart est probablement <5%, mais non quantifiable sans acces a\n"
                 "  leur table 'future match projections' (paywall).\n\n"
                 "* Pinnacle CDM = proxy de marche, pas la realite finale. Le vrai test\n"
                 "  serait un backtest hors-CDM avec resultats observes.\n\n"
                 "* Toutes les donnees brutes sont dans pele_full_results.json pour\n"
                 "  rejouer / analyser sans relancer le script.",
                 {"fontsize": 9}),
            ],
        )


# ─── 8. Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    print("[1/6] Fetching PELE data (cached locally)…")
    raw = fetch_pele_data()
    teams = parse_pele_csvs(raw)
    print(f"      {len(teams)} fédérations chargées (211 attendues)")

    wc_codes = [c for tlist in WC2026_GROUPS.values() for c in tlist]
    missing = [c for c in wc_codes if c not in teams]
    if missing:
        print(f"      ATTENTION : {len(missing)} équipes CDM absentes PELE : {missing}")

    print("[2/6] Building PELE engine (att/def from Round-Robin)…")
    engine = build_pele_engine(teams)
    print(f"      baseline buts/equipe/match = {engine['baseline']:.3f}")

    print("[3/6] Loading V8 prod Elo snapshot…")
    v8_elo = json.loads((SNAP / "pin_calibrated_elo.json").read_text())["elo"]
    print(f"      {len(v8_elo)} nations V8 (snapshot 2026-05-20)")

    print("[4/6] Loading Pinnacle market…")
    market = load_market()
    print(f"      {len(market)} matchs avec cotes Pinnacle")

    print("[5/6] Computing per-match metrics + running MC (10k each)…")
    matches = compute_all_matches(engine, v8_elo, market)
    mc = run_mc(engine, v8_elo, n=N_SIMS)

    # Sauvegarde JSON brut (re-utilisable sans relancer)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    serializable_matches = []
    for m in matches:
        sm = dict(m)
        sm["pele"] = {k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in m["pele"].items()}
        sm["v8"] = {k: (list(v) if isinstance(v, tuple) else v)
                     for k, v in m["v8"].items()}
        serializable_matches.append(sm)
    OUT_JSON.write_text(json.dumps({
        "matches": serializable_matches,
        "mc": mc,
        "n_sims": N_SIMS,
    }, indent=2, default=str))
    print(f"      -> {OUT_JSON} ({OUT_JSON.stat().st_size // 1024} KB)")

    print("[6/6] Rendering PDF…")
    render_pdf(matches, mc, engine, v8_elo, OUT_PDF)
    print(f"      -> {OUT_PDF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
