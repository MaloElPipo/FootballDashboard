"""Simulation Monte Carlo (50000x) de la phase de poules CDM2026
basée uniquement sur les cotes Pinnacle disponibles via TheOddsAPI.

Aucun modèle ELO, aucune sigmoïde : on inverse purement les cotes 1X2 + O/U2.5
en (λh, λa) via Buchdahl (méthode `g2_engine.lambdas_buchdahl`), puis on tire
Poisson(λh) vs Poisson(λa). Pour les matchs sans cotes Pinnacle, on utilise un
fallback team-level (moyenne des λ observés par équipe sur ses autres matchs).

Sortie : PNG `live/data/wc26_pool_market_forecast.png` + JSON brut.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
DASH = REPO_ROOT / "artifacts" / "football-dashboard"
sys.path.insert(0, str(DASH))

from g2_engine import lambdas_buchdahl  # noqa: E402
from wc_simulator import (  # noqa: E402
    WC2026_GROUPS,
    GROUP_MATCHES,
    _pick_best_thirds,
    _rank_group,
)

OUT_PNG = REPO_ROOT / "live" / "data" / "wc26_pool_market_forecast.png"
OUT_JSON = REPO_ROOT / "live" / "data" / "wc26_pool_market_forecast.json"

# Mapping nom Pinnacle/TheOddsAPI -> code FIFA (copié de app.py)
PIN_TO_CODE = {
    "France": "FRA", "Spain": "ESP", "Germany": "GER", "England": "ENG",
    "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL", "Croatia": "CRO",
    "Austria": "AUT", "Switzerland": "SUI", "Norway": "NOR", "Sweden": "SWE",
    "Czech Republic": "CZE", "Czechia": "CZE", "Turkey": "TUR", "Türkiye": "TUR",
    "Scotland": "SCO", "Bosnia and Herzegovina": "BIH", "Bosnia & Herzegovina": "BIH",
    "Argentina": "ARG", "Brazil": "BRA",
    "Colombia": "COL", "Uruguay": "URU", "Ecuador": "ECU", "Paraguay": "PAR",
    "United States": "USA", "USA": "USA", "Mexico": "MEX", "Canada": "CAN",
    "Panama": "PAN", "Curacao": "CUW", "Curaçao": "CUW", "Haiti": "HAI",
    "Japan": "JPN", "South Korea": "KOR", "Korea Republic": "KOR",
    "Iran": "IRN", "Saudi Arabia": "KSA", "Australia": "AUS",
    "Qatar": "QAT", "Iraq": "IRQ", "Jordan": "JOR", "Uzbekistan": "UZB",
    "Morocco": "MAR", "Senegal": "SEN", "Egypt": "EGY", "Algeria": "ALG",
    "Tunisia": "TUN", "Ivory Coast": "CIV", "Ghana": "GHA",
    "DR Congo": "COD", "South Africa": "RSA", "Cape Verde": "CPV",
    "New Zealand": "NZL",
}

CODE_TO_GROUP = {code: g for g, teams in WC2026_GROUPS.items() for code in teams}


def fetch_pinnacle_odds() -> list[dict]:
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise RuntimeError("ODDS_API_KEY manquant")
    r = requests.get(
        "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/",
        params={
            "apiKey": key, "regions": "eu", "markets": "h2h,totals",
            "bookmakers": "pinnacle,bet365", "oddsFormat": "decimal",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def build_match_lambdas(pin_matches: list[dict]) -> dict[tuple[str, str], tuple[float, float]]:
    """Pour chaque match Pinnacle exploitable -> (λh, λa) via Buchdahl 1X2+O/U2.5."""
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for pm in pin_matches:
        h_name, a_name = pm.get("home_team"), pm.get("away_team")
        odds_1x2: dict[str, float] = {}
        ou_over = ou_under = None
        for bk in pm.get("bookmakers", []):
            # Priorité Pinnacle; Bet365 ne servira jamais (vide pour la CDM)
            # mais on garde la structure générique au cas où.
            if bk["key"] != "pinnacle":
                continue
            for mk in bk.get("markets", []):
                if mk["key"] == "h2h":
                    odds_1x2 = {o["name"]: o["price"] for o in mk["outcomes"]}
                elif mk["key"] == "totals":
                    for o in mk["outcomes"]:
                        if o.get("point") == 2.5:
                            if o["name"] == "Over":
                                ou_over = o["price"]
                            elif o["name"] == "Under":
                                ou_under = o["price"]
        oh, od, oa = odds_1x2.get(h_name), odds_1x2.get("Draw"), odds_1x2.get(a_name)
        if not (oh and od and oa):
            continue
        ch, ca = PIN_TO_CODE.get(h_name), PIN_TO_CODE.get(a_name)
        if not (ch and ca):
            continue
        try:
            lh, la, _m = lambdas_buchdahl(
                odds_h=oh, odds_d=od, odds_a=oa,
                ou25_under=ou_under, ou25_over=ou_over,
            )
        except Exception:
            continue
        out[(ch, ca)] = (lh, la)
    return out


def build_team_priors(match_lambdas: dict[tuple[str, str], tuple[float, float]]) -> dict[str, tuple[float, float]]:
    """Per team: moyenne (λ_attack, λ_defense) sur ses matchs observés."""
    att: dict[str, list[float]] = defaultdict(list)
    deff: dict[str, list[float]] = defaultdict(list)
    for (ch, ca), (lh, la) in match_lambdas.items():
        att[ch].append(lh)
        deff[ch].append(la)
        att[ca].append(la)
        deff[ca].append(lh)
    return {
        code: (
            float(np.mean(att[code])) if att[code] else 1.2,
            float(np.mean(deff[code])) if deff[code] else 1.2,
        )
        for code in set(list(att.keys()) + list(deff.keys()))
    }


def resolve_all_match_lambdas(
    match_lambdas: dict[tuple[str, str], tuple[float, float]],
    team_priors: dict[str, tuple[float, float]],
) -> tuple[dict[tuple[str, str, str], tuple[float, float]], dict[str, int]]:
    """Pour TOUS les matchs de poule (72), retourne (λh, λa) :
    - directement depuis Pinnacle si dispo,
    - sinon fallback team-level : λh = mean(att_h, def_a), λa = mean(att_a, def_h).
    Renvoie aussi {grp: nb_matches_avec_cotes} pour le reporting.
    """
    resolved: dict[tuple[str, str, str], tuple[float, float]] = {}
    coverage: dict[str, int] = defaultdict(int)
    league_mean = (
        float(np.mean([v[0] for v in team_priors.values()])) if team_priors else 1.2,
        float(np.mean([v[1] for v in team_priors.values()])) if team_priors else 1.2,
    )
    for grp_letter, teams in WC2026_GROUPS.items():
        for md_name, pairings in GROUP_MATCHES.items():
            for i_h, i_a in pairings:
                ch, ca = teams[i_h], teams[i_a]
                key = (grp_letter, ch, ca)
                if (ch, ca) in match_lambdas:
                    resolved[key] = match_lambdas[(ch, ca)]
                    coverage[grp_letter] += 1
                else:
                    att_h, def_h = team_priors.get(ch, league_mean)
                    att_a, def_a = team_priors.get(ca, league_mean)
                    lh = (att_h + def_a) / 2.0
                    la = (att_a + def_h) / 2.0
                    resolved[key] = (lh, la)
    return resolved, dict(coverage)


def simulate(
    all_lambdas: dict[tuple[str, str, str], tuple[float, float]],
    n_sims: int = 50000,
    seed: int = 42,
) -> dict[str, dict]:
    rng = np.random.default_rng(seed)
    # Pré-tirage vectoriel : pour chaque match, n_sims couples (gh, ga).
    sims = {}
    for key, (lh, la) in all_lambdas.items():
        sims[key] = (
            rng.poisson(lh, size=n_sims),
            rng.poisson(la, size=n_sims),
        )

    agg = defaultdict(lambda: {
        "pos_counts": defaultdict(int),
        "gf_total": 0.0, "ga_total": 0.0,
        "pts_total": 0.0,
        "qualif_count": 0,
    })

    # Boucle Python sur n_sims pour pouvoir réutiliser _rank_group + _pick_best_thirds
    for i in range(n_sims):
        group_results = {}
        for grp_letter, teams in WC2026_GROUPS.items():
            standings = {code: {"pts": 0, "gf": 0.0, "ga": 0.0, "w": 0, "d": 0, "l": 0}
                         for code in teams}
            h2h_log = defaultdict(lambda: defaultdict(lambda: {"pts": 0, "gf": 0.0, "ga": 0.0}))
            for md_name, pairings in GROUP_MATCHES.items():
                for i_h, i_a in pairings:
                    ch, ca = teams[i_h], teams[i_a]
                    gh = int(sims[(grp_letter, ch, ca)][0][i])
                    ga = int(sims[(grp_letter, ch, ca)][1][i])
                    standings[ch]["gf"] += gh
                    standings[ch]["ga"] += ga
                    standings[ca]["gf"] += ga
                    standings[ca]["ga"] += gh
                    h2h_log[ch][ca]["gf"] += gh
                    h2h_log[ch][ca]["ga"] += ga
                    h2h_log[ca][ch]["gf"] += ga
                    h2h_log[ca][ch]["ga"] += gh
                    if gh > ga:
                        standings[ch]["pts"] += 3
                        h2h_log[ch][ca]["pts"] += 3
                    elif gh == ga:
                        standings[ch]["pts"] += 1
                        standings[ca]["pts"] += 1
                        h2h_log[ch][ca]["pts"] += 1
                        h2h_log[ca][ch]["pts"] += 1
                    else:
                        standings[ca]["pts"] += 3
                        h2h_log[ca][ch]["pts"] += 3
            # Pas d'ELO map → tiebreak final = ordre alphabétique stable. C'est OK
            # car (a) on est sur 50k sims, le bruit du tiebreak ultime se moyenne,
            # (b) user voulait du pur marché, donc pas d'ELO ranking.
            ranked = _rank_group(standings, h2h_log=h2h_log, elo_map={})
            group_results[grp_letter] = ranked
            for pos, (code, s) in enumerate(ranked):
                a = agg[code]
                a["pos_counts"][pos + 1] += 1
                a["pts_total"] += s["pts"]
                a["gf_total"] += s["gf"]
                a["ga_total"] += s["ga"]

        best_thirds = _pick_best_thirds(group_results, elo_map={}, n=8)
        qualified_thirds = {t[1] for t in best_thirds}
        for grp_letter, ranked in group_results.items():
            agg[ranked[0][0]]["qualif_count"] += 1
            agg[ranked[1][0]]["qualif_count"] += 1
        for code in qualified_thirds:
            agg[code]["qualif_count"] += 1

    # Format final
    out = {}
    for code, a in agg.items():
        out[code] = {
            "group": CODE_TO_GROUP.get(code),
            "avg_pts": a["pts_total"] / n_sims,
            "avg_gf": a["gf_total"] / n_sims,
            "avg_ga": a["ga_total"] / n_sims,
            "p_1st": a["pos_counts"][1] / n_sims * 100,
            "p_2nd": a["pos_counts"][2] / n_sims * 100,
            "p_3rd": a["pos_counts"][3] / n_sims * 100,
            "p_4th": a["pos_counts"][4] / n_sims * 100,
            "p_qualif": a["qualif_count"] / n_sims * 100,
        }
    return out


def render_png(results: dict[str, dict], coverage: dict[str, int],
               n_sims: int, total_pinnacle: int) -> Path:
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    NAMES = {
        "MEX": "Mexique", "RSA": "Afrique du Sud", "KOR": "Corée du Sud", "CZE": "Tchéquie",
        "CAN": "Canada", "BIH": "Bosnie-Herzégovine", "QAT": "Qatar", "SUI": "Suisse",
        "BRA": "Brésil", "MAR": "Maroc", "HAI": "Haïti", "SCO": "Écosse",
        "USA": "États-Unis", "PAR": "Paraguay", "AUS": "Australie", "TUR": "Turquie",
        "GER": "Allemagne", "CUW": "Curaçao", "CIV": "Côte d'Ivoire", "ECU": "Équateur",
        "NED": "Pays-Bas", "JPN": "Japon", "SWE": "Suède", "TUN": "Tunisie",
        "BEL": "Belgique", "EGY": "Égypte", "IRN": "Iran", "NZL": "Nouvelle-Zélande",
        "ESP": "Espagne", "CPV": "Cap-Vert", "KSA": "Arabie saoudite", "URU": "Uruguay",
        "FRA": "France", "SEN": "Sénégal", "IRQ": "Irak", "NOR": "Norvège",
        "ARG": "Argentine", "ALG": "Algérie", "AUT": "Autriche", "JOR": "Jordanie",
        "POR": "Portugal", "COD": "RD Congo", "UZB": "Ouzbékistan", "COL": "Colombie",
        "ENG": "Angleterre", "CRO": "Croatie", "GHA": "Ghana", "PAN": "Panama",
    }

    fig, axes = plt.subplots(4, 3, figsize=(20, 24))
    fig.patch.set_facecolor("#fafafa")
    fig.suptitle(
        f"CDM 2026 — Prévision phase de poules (pures cotes Pinnacle, {n_sims:,} simulations)",
        fontsize=18, fontweight="bold", y=0.995,
    )
    fig.text(
        0.5, 0.975,
        f"Couverture cotes : {total_pinnacle}/72 matchs réels. "
        f"Matchs sans cotes : fallback team-level (moyennes λ Pinnacle des autres matchs de l'équipe).",
        ha="center", fontsize=10, style="italic", color="#555",
    )

    groups_sorted = sorted(WC2026_GROUPS.keys())
    for idx, grp in enumerate(groups_sorted):
        ax = axes[idx // 3][idx % 3]
        ax.set_facecolor("white")
        teams = WC2026_GROUPS[grp]
        rows = [(code, results[code]) for code in teams]
        rows.sort(key=lambda x: -x[1]["p_qualif"])

        headers = ["Nation", "Pts", "BP", "BC", "1er", "2e", "3e", "4e", "Qualif."]
        cell_text = []
        cell_colors = []
        for code, r in rows:
            cell_text.append([
                NAMES.get(code, code),
                f"{r['avg_pts']:.1f}",
                f"{r['avg_gf']:.2f}",
                f"{r['avg_ga']:.2f}",
                f"{r['p_1st']:.0f}%",
                f"{r['p_2nd']:.0f}%",
                f"{r['p_3rd']:.0f}%",
                f"{r['p_4th']:.0f}%",
                f"{r['p_qualif']:.1f}%",
            ])
            # Couleur ligne selon qualif
            q = r["p_qualif"]
            if q >= 70:
                color = "#d4edda"
            elif q >= 40:
                color = "#fff3cd"
            else:
                color = "#f8d7da"
            cell_colors.append([color] * len(headers))

        tbl = ax.table(
            cellText=cell_text, colLabels=headers, cellColours=cell_colors,
            colColours=["#343a40"] * len(headers),
            loc="center", cellLoc="center",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(10)
        tbl.scale(1.0, 1.8)
        for j in range(len(headers)):
            tbl[(0, j)].set_text_props(color="white", fontweight="bold")

        cov = coverage.get(grp, 0)
        ax.set_title(
            f"Poule {grp}  —  cotes dispo : {cov}/6 matchs",
            fontsize=13, fontweight="bold", pad=10,
        )
        ax.axis("off")

    # Légende couleurs en bas
    legend_y = 0.01
    fig.text(0.30, legend_y, "■ vert: qualif. ≥70%   ",
             color="#5cb85c", fontsize=11, fontweight="bold")
    fig.text(0.46, legend_y, "■ jaune: 40-70%   ",
             color="#f0ad4e", fontsize=11, fontweight="bold")
    fig.text(0.58, legend_y, "■ rouge: <40%",
             color="#d9534f", fontsize=11, fontweight="bold")

    plt.tight_layout(rect=[0, 0.02, 1, 0.97])
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT_PNG, dpi=140, bbox_inches="tight", facecolor="#fafafa")
    plt.close(fig)
    return OUT_PNG


def main() -> int:
    print("[1/4] Fetch Pinnacle odds…")
    pin = fetch_pinnacle_odds()
    print(f"      -> {len(pin)} matchs totaux (CDM) renvoyés par TheOddsAPI")

    print("[2/4] Inversion Buchdahl (1X2 + O/U2.5) -> (λh, λa)…")
    match_lambdas = build_match_lambdas(pin)
    print(f"      -> {len(match_lambdas)} matchs exploitables (cotes complètes)")

    team_priors = build_team_priors(match_lambdas)
    all_lambdas, coverage = resolve_all_match_lambdas(match_lambdas, team_priors)
    print(f"      -> {len(all_lambdas)} matchs résolus (réels + fallback team-level)")

    print("[3/4] Simulation 50000x…")
    results = simulate(all_lambdas, n_sims=50000, seed=42)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "n_sims": 50000,
        "matches_with_real_odds": len(match_lambdas),
        "matches_fallback": 72 - len(match_lambdas),
        "coverage_per_group": coverage,
        "results": results,
    }, indent=2, ensure_ascii=False))

    print("[4/4] Rendu PNG…")
    path = render_png(results, coverage, n_sims=50000,
                      total_pinnacle=len(match_lambdas))
    print(f"      -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
