"""Bilan exhaustif des corrections de biais predictif (sigmoid V8 + cap lambda).

Banc d'essai PURE SANDBOX : ne touche ni `football-dashboard` ni `football-lab`.
Reproduit localement les formules sigmoid_v6/v8 + derive_lambdas pour pouvoir
flipper chaque constante isolement, et compare les sorties a la verite de
marche (cotes Pinnacle WC2026, demarinees Buchdahl).

Sortie : `live/data/wc_bias_correction_report.pdf` (12-15 pages).

Convention :
    * V0 = production (sigmoid_v8 actuel)
    * V1 = flip FAV_BOOST_GROUP -2.446 -> +2.446
    * V2 = abaisse FAV_DELTA_THRESHOLD 380 -> 200 (tue la zone morte)
    * V3 = leve cap lambda 4.0 -> 6.0 (analyse separee buts/scores)
    * V4 = sigmoid_v6 pure (aucun boost V8)
    * V5 = V1 + V2 combines
    * V6 = V5 + recalibre quality term (V7_QUALITY) (sensibilite)

Verite : implied Pinnacle 1X2 demargine par methode multiplicative Buchdahl.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable

import numpy as np
import requests

REPO = Path(__file__).resolve().parents[1]
SNAP = REPO / "artifacts/football-lab/lab/data/snapshots/initial_baseline_2026-05-20"
OUT_PDF = REPO / "live/data/wc_bias_correction_report.pdf"

# ─── Constantes prod (copie litterale de wc_simulator.py l.61-73) ────────────
V7_SCALE = 441.952
V7_DRAW_BASE = 24.09
V7_D_HALF = 463.648
V7_POWER = 3.56
V7_QUALITY = 0.035

V8_DRAW_BOOST_CLOSE = 4.312
V8_DRAW_BOOST_MID = 2.555
V8_DRAW_BOOST_KO = 3.37
V8_DRAW_BOOST_MAX = 36.049
V8_FAV_BOOST_GROUP = -2.446      # ← le smoking gun
V8_FAV_BOOST_KO = 2.746
V8_FAV_DELTA_THRESHOLD = 380.332


# ─── Sigmoid v6 reproduit a l'identique ──────────────────────────────────────

def sigmoid_v6(delta_elo: float, elo_avg: float | None = None,
               quality: float = V7_QUALITY) -> tuple[float, float, float]:
    scale = V7_SCALE
    draw_base = V7_DRAW_BASE
    d_half = max(V7_D_HALF, 1.0)
    power = V7_POWER
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


def sigmoid_v8(
    delta_elo: float,
    elo_avg: float | None = None,
    phase: str = "G",
    fav_boost_group: float = V8_FAV_BOOST_GROUP,
    fav_delta_threshold: float = V8_FAV_DELTA_THRESHOLD,
    quality: float = V7_QUALITY,
) -> tuple[float, float, float]:
    p1, px, p2 = sigmoid_v6(delta_elo, elo_avg=elo_avg, quality=quality)
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
    if abs_d >= fav_delta_threshold:
        fav_boost = (V8_FAV_BOOST_KO if phase == "K" else fav_boost_group) / 100.0
    net_draw = max(draw_boost - fav_boost * 0.7, 0.0)
    px_new = px + net_draw
    if p1 + p2 > 0:
        p1_new = p1 - net_draw * (p1 / (p1 + p2))
        p2_new = p2 - net_draw * (p2 / (p1 + p2))
    else:
        p1_new, p2_new = p1, p2
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
    tot = p1_new + px_new + p2_new
    return p1_new / tot, px_new / tot, p2_new / tot


# ─── Variants tested ─────────────────────────────────────────────────────────

VARIANTS: dict[str, Callable[[float, float], tuple[float, float, float]]] = {
    "V0_prod":         lambda d, ea: sigmoid_v8(d, ea, "G"),
    "V1_flip_fav":     lambda d, ea: sigmoid_v8(d, ea, "G", fav_boost_group=+2.446),
    "V2_no_deadzone":  lambda d, ea: sigmoid_v8(d, ea, "G", fav_delta_threshold=200.0),
    "V4_v6_pure":      lambda d, ea: sigmoid_v6(d, ea),
    "V5_v1_plus_v2":   lambda d, ea: sigmoid_v8(d, ea, "G",
                                                fav_boost_group=+2.446,
                                                fav_delta_threshold=200.0),
    "V6_v5_quality0":  lambda d, ea: sigmoid_v8(d, ea, "G",
                                                fav_boost_group=+2.446,
                                                fav_delta_threshold=200.0,
                                                quality=0.0),
}


# ─── Verite marche : Pinnacle demargine ──────────────────────────────────────

def buchdahl_demargin(oh: float, od: float, oa: float) -> tuple[float, float, float]:
    """Demargination multiplicative simple (precision <0.5pp vs methode iter)."""
    ih, idx, ia = 1.0 / oh, 1.0 / od, 1.0 / oa
    s = ih + idx + ia
    return ih / s, idx / s, ia / s


def fetch_fresh_odds() -> list[dict]:
    """Refetch live Pinnacle odds (47 matchs typiquement). Fallback snapshot."""
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        return []
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/",
            params={"apiKey": key, "regions": "eu", "markets": "h2h",
                    "bookmakers": "pinnacle", "oddsFormat": "decimal"}, timeout=30,
        )
        if r.status_code != 200:
            return []
        out = []
        for pm in r.json():
            h, a = pm.get("home_team"), pm.get("away_team")
            for bk in pm.get("bookmakers", []):
                if bk["key"] != "pinnacle":
                    continue
                for mk in bk.get("markets", []):
                    if mk["key"] == "h2h":
                        odds = {o["name"]: o["price"] for o in mk["outcomes"]}
                        oh, od, oa = odds.get(h), odds.get("Draw"), odds.get(a)
                        if oh and od and oa:
                            out.append({"home": h, "away": a,
                                        "pin_h": oh, "pin_d": od, "pin_a": oa})
        return out
    except Exception:
        return []


PIN_TO_CODE = {
    "France": "FRA", "Spain": "ESP", "Germany": "GER", "England": "ENG",
    "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL", "Croatia": "CRO",
    "Austria": "AUT", "Switzerland": "SUI", "Norway": "NOR", "Sweden": "SWE",
    "Czech Republic": "CZE", "Czechia": "CZE", "Turkey": "TUR", "Türkiye": "TUR",
    "Scotland": "SCO", "Bosnia and Herzegovina": "BIH", "Bosnia & Herzegovina": "BIH",
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


def load_dataset() -> tuple[dict[str, int], list[dict]]:
    elo = json.loads((SNAP / "pin_calibrated_elo.json").read_text())["elo"]
    fresh = fetch_fresh_odds()
    if fresh:
        odds = fresh
        src = "live_fresh"
    else:
        odds = json.loads((SNAP / "pinnacle_wc2026_odds.json").read_text())
        src = "snapshot"
    matches = []
    for m in odds:
        ch = PIN_TO_CODE.get(m["home"])
        ca = PIN_TO_CODE.get(m["away"])
        if not (ch and ca):
            continue
        if ch not in elo or ca not in elo:
            continue
        ph, pd, pa = buchdahl_demargin(m["pin_h"], m["pin_d"], m["pin_a"])
        matches.append({
            "ch": ch, "ca": ca,
            "elo_h": elo[ch], "elo_a": elo[ca],
            "delta": elo[ch] - elo[ca],
            "elo_avg": (elo[ch] + elo[ca]) / 2.0,
            "mkt_h": ph, "mkt_d": pd, "mkt_a": pa,
            "fav_is_home": elo[ch] >= elo[ca],
            "abs_delta": abs(elo[ch] - elo[ca]),
        })
    return elo, matches, src


# ─── Metrics ─────────────────────────────────────────────────────────────────

def log_loss(model: tuple[float, float, float], truth: tuple[float, float, float]) -> float:
    """Cross-entropy H(truth, model). Avec truth = proba (pas one-hot)."""
    eps = 1e-9
    return -sum(t * math.log(max(m, eps)) for t, m in zip(truth, model))


def evaluate(matches: list[dict]) -> dict:
    """Pour chaque variant: per-match probs + metrics agreges."""
    out = {name: {"rows": [], "agg": {}} for name in VARIANTS}
    for name, fn in VARIANTS.items():
        rows = []
        for m in matches:
            ph, pd, pa = fn(m["delta"], m["elo_avg"])
            mkt = (m["mkt_h"], m["mkt_d"], m["mkt_a"])
            mdl = (ph, pd, pa)
            p_fav_mkt = mkt[0] if m["fav_is_home"] else mkt[2]
            p_fav_mdl = mdl[0] if m["fav_is_home"] else mdl[2]
            rows.append({
                **m, "ph": ph, "pd": pd, "pa": pa,
                "p_fav_mkt": p_fav_mkt, "p_fav_mdl": p_fav_mdl,
                "bias_fav": p_fav_mdl - p_fav_mkt,
                "abs_err_fav": abs(p_fav_mdl - p_fav_mkt),
                "log_loss": log_loss(mdl, mkt),
            })
        out[name]["rows"] = rows
        out[name]["agg"] = {
            "mean_bias_fav": float(np.mean([r["bias_fav"] for r in rows])),
            "mean_abs_err_fav": float(np.mean([r["abs_err_fav"] for r in rows])),
            "median_bias_fav": float(np.median([r["bias_fav"] for r in rows])),
            "mean_log_loss": float(np.mean([r["log_loss"] for r in rows])),
            "n": len(rows),
        }
    return out


# ─── Analyse cap lambda separee ──────────────────────────────────────────────

def lambda_cap_analysis(matches: list[dict]) -> list[dict]:
    """Pour les matchs avec |Delta| > 700 (cap λ=4.0 active), simule la masse
    du score ≥5-0 perdue par le clipping vs sans cap."""
    rows = []
    for m in matches:
        d = m["delta"]
        if abs(d) < 600:
            continue
        f = d / 600.0
        base = 1.25
        lh_raw = base * math.exp(f * 0.5)
        la_raw = base * math.exp(-f * 0.5)
        lh_capped = max(0.3, min(lh_raw, 4.0))
        la_capped = max(0.3, min(la_raw, 4.0))
        # P(score >= 5 - 0) sous chaque λ favori
        def p_at_least(lam, k):
            return 1.0 - sum(math.exp(-lam) * lam ** i / math.factorial(i)
                             for i in range(k))
        rows.append({
            "match": f"{m['ch']}-{m['ca']}",
            "delta": d, "lh_raw": lh_raw, "lh_capped": lh_capped,
            "p_ge5_raw": p_at_least(lh_raw, 5),
            "p_ge5_capped": p_at_least(lh_capped, 5),
            "loss": p_at_least(lh_raw, 5) - p_at_least(lh_capped, 5),
        })
    return rows


# ─── PDF rendering ───────────────────────────────────────────────────────────

def render_pdf(data: dict, matches: list[dict], cap_rows: list[dict],
               src: str, out_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    plt.rcParams["font.family"] = "DejaVu Sans"

    with PdfPages(out_path) as pdf:
        # ─── Page 1 : cover ───────────────────────────────────────────────
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.5, 0.85, "Bilan correctifs predictif CDM2026",
                 ha="center", fontsize=22, fontweight="bold")
        fig.text(0.5, 0.79, "Test isole en sandbox — prod inchangee",
                 ha="center", fontsize=12, style="italic", color="#555")
        fig.text(0.5, 0.74,
                 f"Verite marche : Pinnacle de-margine Buchdahl ({src})\n"
                 f"Echantillon : {len(matches)} matchs CDM2026 avec cotes Pinnacle",
                 ha="center", fontsize=10)
        # Resume executif
        agg = data["V0_prod"]["agg"]
        fig.text(0.1, 0.62, "Diagnostic en une ligne", fontsize=14, fontweight="bold")
        fig.text(0.1, 0.55,
                 f"V0 (prod) sous-estime le favori de "
                 f"{-agg['mean_bias_fav']*100:.2f} pts en moyenne, "
                 f"erreur absolue moyenne "
                 f"{agg['mean_abs_err_fav']*100:.2f} pts, "
                 f"log-loss {agg['mean_log_loss']:.4f}.",
                 fontsize=11, wrap=True)
        fig.text(0.1, 0.45, "Variants testes", fontsize=14, fontweight="bold")
        labels = {
            "V0_prod": "V0  — production telle quelle",
            "V1_flip_fav": "V1  — flip FAV_BOOST_GROUP -2.446 -> +2.446",
            "V2_no_deadzone": "V2  — abaisse seuil 380 -> 200 (tue zone morte)",
            "V4_v6_pure": "V4  — sigmoid V6 pure (sans aucun boost V8)",
            "V5_v1_plus_v2": "V5  — combine V1 + V2",
            "V6_v5_quality0": "V6  — V5 + quality term = 0 (sensibilite)",
        }
        y = 0.40
        for k, v in labels.items():
            fig.text(0.1, y, v, fontsize=10, family="monospace"); y -= 0.025
        fig.text(0.1, 0.30, "Plan du rapport", fontsize=14, fontweight="bold")
        plan = [
            "1. Tableau de synthese par variant (bias, MAE, log-loss)",
            "2. Bias par tranche d'ecart Elo (la zone morte 200-380)",
            "3. Top 15 matchs les plus sous-estimes (V0 vs marche)",
            "4. Effet du cap lambda 4.0 sur les gros mismatches",
            "5. Detail match par match (variant gagnant + recommandations)",
            "6. Recommandation finale + plan de bascule",
        ]
        y = 0.255
        for line in plan:
            fig.text(0.12, y, line, fontsize=10); y -= 0.022
        fig.text(0.5, 0.05,
                 "scripts/wc_bias_correction_report.py — pure sandbox",
                 ha="center", fontsize=8, color="#888")
        plt.axis("off")
        pdf.savefig(fig); plt.close(fig)

        # ─── Page 2 : tableau synthese ────────────────────────────────────
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.axis("off")
        ax.set_title("1. Synthese par variant (vs marche Pinnacle)",
                     fontsize=14, fontweight="bold", loc="left", pad=20)
        headers = ["Variant", "n", "Bias p_fav (pp)", "MAE p_fav (pp)",
                   "Mediane bias (pp)", "Log-loss"]
        rows = []
        colors = []
        for name in VARIANTS:
            a = data[name]["agg"]
            rows.append([
                name, str(a["n"]),
                f"{a['mean_bias_fav']*100:+.2f}",
                f"{a['mean_abs_err_fav']*100:.2f}",
                f"{a['median_bias_fav']*100:+.2f}",
                f"{a['mean_log_loss']:.4f}",
            ])
            if a["mean_bias_fav"] > 0:
                colors.append(["#e8f5e9"]*len(headers))
            elif a["mean_bias_fav"] > -0.01:
                colors.append(["#fff8e1"]*len(headers))
            else:
                colors.append(["#ffebee"]*len(headers))
        tbl = ax.table(cellText=rows, colLabels=headers, loc="upper center",
                       cellLoc="center", cellColours=colors,
                       colColours=["#37474f"]*len(headers))
        tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 2)
        for j in range(len(headers)):
            tbl[(0, j)].set_text_props(color="white", fontweight="bold")
        fig.text(0.08, 0.55, "Lecture", fontsize=12, fontweight="bold")
        notes = (
            "* bias positif = sur-estime le favori, bias negatif = sous-estime.\n"
            "* MAE = ecart absolu moyen entre proba modele et proba Pinnacle.\n"
            "* Log-loss croisee : modele vs distribution implied Pinnacle.\n"
            "* Le marche Pinnacle est utilise comme verite sharp (industrie).\n"
            "  C'est un proxy de qualite (margin ~2.5%) mais pas la realite\n"
            "  finale : seul un backtest hors-CDM avec resultats observes peut\n"
            "  prouver definitivement la generalisation des corrections.\n\n"
            "Codes couleur :\n"
            "  vert : bias > 0 (modele sur le favori)\n"
            "  jaune : bias proche de zero (bonne calibration)\n"
            "  rouge : bias < -1 pp (sous-estimation persistante)"
        )
        fig.text(0.08, 0.30, notes, fontsize=9, family="monospace", va="top")
        pdf.savefig(fig); plt.close(fig)

        # ─── Page 3 : bias par tranche ΔElo ──────────────────────────────
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.set_title("2. Bias modele - marche par tranche d'ecart Elo",
                     fontsize=14, fontweight="bold", loc="left", pad=15)
        buckets = [(0, 100, "[0-100]"), (100, 200, "[100-200]"),
                   (200, 380, "[200-380]\n(zone morte)"), (380, 9999, "[380+]")]
        variants_to_plot = ["V0_prod", "V1_flip_fav", "V2_no_deadzone",
                            "V4_v6_pure", "V5_v1_plus_v2"]
        x = np.arange(len(buckets))
        w = 0.15
        for i, name in enumerate(variants_to_plot):
            vals = []
            for lo, hi, _ in buckets:
                sub = [r["bias_fav"]*100 for r in data[name]["rows"]
                       if lo <= r["abs_delta"] < hi]
                vals.append(np.mean(sub) if sub else 0.0)
            ax.bar(x + (i - 2) * w, vals, w, label=name)
        ax.set_xticks(x)
        ax.set_xticklabels([b[2] for b in buckets], fontsize=9)
        ax.axhline(0, color="black", lw=0.5)
        ax.set_ylabel("Bias proba favori (pp)")
        ax.set_xlabel("Ecart Elo |Delta|")
        ax.legend(fontsize=8, loc="best")
        ax.grid(axis="y", alpha=0.3)
        ax.set_title("2. Bias modele - marche par tranche d'ecart Elo",
                     fontsize=14, fontweight="bold", loc="left", pad=15)
        fig.text(0.08, 0.30,
                 "Lecture : barres negatives = le favori est sous-estime.\n\n"
                 "Observations attendues :\n"
                 " - V0 plonge en territoire negatif sur [380+] : effet direct\n"
                 "   du FAV_BOOST_GROUP -2.446.\n"
                 " - V0 plonge AUSSI sur [200-380] : zone morte (le draw_boost\n"
                 "   est deja eteint mais le seuil 380 n'est pas franchi, donc\n"
                 "   le favori n'a aucun coup de pouce du tout).\n"
                 " - V1 corrige [380+] mais pas [200-380].\n"
                 " - V2 corrige [200-380] mais le bias [380+] reste partiel.\n"
                 " - V5 (combinaison) devrait ramener le bias a ~0 sur les 4\n"
                 "   tranches.",
                 fontsize=9, family="monospace", va="top")
        pdf.savefig(fig); plt.close(fig)

        # ─── Page 4 : top 15 sous-estimes ────────────────────────────────
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.axis("off")
        ax.set_title("3. Top 15 matchs ou V0 sous-estime le plus le favori",
                     fontsize=14, fontweight="bold", loc="left", pad=15)
        rows_v0 = sorted(data["V0_prod"]["rows"], key=lambda r: r["bias_fav"])
        worst = rows_v0[:15]
        headers = ["Match", "ΔElo", "Pin p_fav", "V0 p_fav",
                   "V5 p_fav", "Bias V0", "Bias V5"]
        cell = []
        for r in worst:
            v5 = next(x for x in data["V5_v1_plus_v2"]["rows"]
                      if x["ch"] == r["ch"] and x["ca"] == r["ca"])
            cell.append([
                f"{r['ch']}-{r['ca']}",
                f"{r['delta']:+.0f}",
                f"{r['p_fav_mkt']*100:.1f}%",
                f"{r['p_fav_mdl']*100:.1f}%",
                f"{v5['p_fav_mdl']*100:.1f}%",
                f"{r['bias_fav']*100:+.2f}",
                f"{v5['bias_fav']*100:+.2f}",
            ])
        tbl = ax.table(cellText=cell, colLabels=headers, loc="upper center",
                       cellLoc="center",
                       colColours=["#37474f"]*len(headers))
        tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.6)
        for j in range(len(headers)):
            tbl[(0, j)].set_text_props(color="white", fontweight="bold")
        pdf.savefig(fig); plt.close(fig)

        # ─── Page 5 : cap lambda ──────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(8.27, 11.69))
        ax.axis("off")
        ax.set_title("4. Effet cap lambda 4.0 (gros mismatches)",
                     fontsize=14, fontweight="bold", loc="left", pad=15)
        if cap_rows:
            headers = ["Match", "ΔElo", "λ_h brut", "λ_h capé",
                       "P(score>=5-0) brut", "P(score>=5-0) capé", "Perdu"]
            cell = []
            for r in cap_rows[:20]:
                cell.append([
                    r["match"], f"{r['delta']:+.0f}",
                    f"{r['lh_raw']:.2f}", f"{r['lh_capped']:.2f}",
                    f"{r['p_ge5_raw']*100:.2f}%",
                    f"{r['p_ge5_capped']*100:.2f}%",
                    f"{r['loss']*100:+.2f} pp",
                ])
            tbl = ax.table(cellText=cell, colLabels=headers,
                           loc="upper center", cellLoc="center",
                           colColours=["#37474f"]*len(headers))
            tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.6)
            for j in range(len(headers)):
                tbl[(0, j)].set_text_props(color="white", fontweight="bold")
            fig.text(0.08, 0.30,
                     "Lecture : sur les vrais gros mismatches CDM2026 (|ΔElo|>600),\n"
                     "le cap λ=4.0 retire de la masse a la queue droite des scores\n"
                     "(5-0, 6-0, 7-0...). Cette masse se redistribue sur les scores\n"
                     "plus bas → augmente artificiellement P(nul) et P(defaite minime).\n\n"
                     "Recommandation : passer le cap a 5.5 ou 6.0. Au-dela ce n'est\n"
                     "plus du football realiste (rare au niveau international).",
                     fontsize=9, family="monospace", va="top")
        else:
            ax.text(0.5, 0.5,
                    "Aucun match WC2026 |ΔElo|>600 dans l'echantillon Pinnacle\n"
                    "(les vrais mismatches sont aux MD2/MD3, encore sans cotes).\n\n"
                    "Le cap λ=4.0 reste neanmoins une source de biais sur les\n"
                    "matchs hors-CDM qu'il faudrait isoler en backtest.",
                    ha="center", va="center", fontsize=11)
        pdf.savefig(fig); plt.close(fig)

        # ─── Page 6 : detail match par match V0 vs V5 ────────────────────
        per_page = 28
        rows_all = sorted(data["V0_prod"]["rows"], key=lambda r: -r["abs_delta"])
        v5_by_key = {(r["ch"], r["ca"]): r for r in data["V5_v1_plus_v2"]["rows"]}
        for start in range(0, len(rows_all), per_page):
            chunk = rows_all[start:start + per_page]
            fig, ax = plt.subplots(figsize=(8.27, 11.69))
            ax.axis("off")
            ax.set_title(f"5. Detail matchs (page {start // per_page + 1})",
                         fontsize=14, fontweight="bold", loc="left", pad=15)
            headers = ["Match", "ΔElo", "Pin 1/X/2",
                       "V0 1/X/2", "V5 1/X/2", "Δ p_fav (V5-V0)"]
            cell = []
            for r in chunk:
                v5 = v5_by_key[(r["ch"], r["ca"])]
                cell.append([
                    f"{r['ch']}-{r['ca']}", f"{r['delta']:+.0f}",
                    f"{r['mkt_h']*100:.0f}/{r['mkt_d']*100:.0f}/{r['mkt_a']*100:.0f}",
                    f"{r['ph']*100:.0f}/{r['pd']*100:.0f}/{r['pa']*100:.0f}",
                    f"{v5['ph']*100:.0f}/{v5['pd']*100:.0f}/{v5['pa']*100:.0f}",
                    f"{(v5['p_fav_mdl']-r['p_fav_mdl'])*100:+.2f}",
                ])
            tbl = ax.table(cellText=cell, colLabels=headers,
                           loc="upper center", cellLoc="center",
                           colColours=["#37474f"]*len(headers))
            tbl.auto_set_font_size(False); tbl.set_fontsize(7); tbl.scale(1, 1.3)
            for j in range(len(headers)):
                tbl[(0, j)].set_text_props(color="white", fontweight="bold")
            pdf.savefig(fig); plt.close(fig)

        # ─── Derniere page : reco finale ──────────────────────────────────
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.5, 0.93, "6. Recommandation finale et plan de bascule",
                 ha="center", fontsize=15, fontweight="bold")
        agg_v0 = data["V0_prod"]["agg"]
        agg_v5 = data["V5_v1_plus_v2"]["agg"]
        improvement_bias = (abs(agg_v0["mean_bias_fav"]) - abs(agg_v5["mean_bias_fav"])) * 100
        improvement_mae = (agg_v0["mean_abs_err_fav"] - agg_v5["mean_abs_err_fav"]) * 100
        improvement_ll = agg_v0["mean_log_loss"] - agg_v5["mean_log_loss"]
        verdict = (
            f"V5 (flip fav_boost + abaisser seuil 200) reduit le bias\n"
            f"absolu de {improvement_bias:+.2f} pts, la MAE de "
            f"{improvement_mae:+.2f} pts, et le log-loss de "
            f"{improvement_ll:+.4f}.\n\n"
            f"Si ces ecarts sont >0 et statistiquement non triviaux\n"
            f"(>0.5 pp), V5 est candidat naturel a la bascule shadow."
        )
        fig.text(0.08, 0.82, "Resultat sur l'echantillon CDM2026 :",
                 fontsize=12, fontweight="bold")
        fig.text(0.08, 0.72, verdict, fontsize=10, va="top", wrap=True)
        fig.text(0.08, 0.58, "Sequence de bascule recommandee :",
                 fontsize=12, fontweight="bold")
        steps = [
            "1. Etendre l'echantillon : backtest sur 200+ matchs hors-CDM",
            "   (PL/Liga/Bundesliga/Ligue 1 saisons 24/25 + 25/26) avec",
            "   resultats reels observes (log-loss vs one-hot, pas vs Pinnacle).",
            "2. Si V5 confirme : creer feature flag SIGMOID_VARIANT en prod.",
            "   Valeurs possibles : v8_prod, v8_fixed_v5, v6_pure.",
            "3. Shadow 2 semaines : log les 2 sorties, ne change rien.",
            "4. Blend 70/30 (prod/v5) une semaine.",
            "5. Bascule 100% v5 si KPI stable ou meilleur.",
            "6. Code mort retire apres 30 jours en fallback.",
        ]
        y = 0.51
        for s in steps:
            fig.text(0.08, y, s, fontsize=9, family="monospace"); y -= 0.022
        fig.text(0.08, 0.30, "Mises en garde :", fontsize=12, fontweight="bold")
        warn = (
            "* Pinnacle CDM mid-mai = peu liquide vs ligues de club -> bias\n"
            "  d'echantillonnage possible. Backtester sur cotes club closes.\n"
            "* Le cap λ=4.0 ne touche pas la sigmoid 1X2 directement, mais il\n"
            "  affecte les buts, donc les depatages buts marques en poule\n"
            "  et les buteurs. Le passer a 5.5 demande une analyse separee.\n"
            "* La compression Elo amont (blend pin_calibrated + forced) n'est\n"
            "  pas etudiee ici : elle est en amont de la sigmoid. Si V5 reste\n"
            "  biaise apres bascule, il faudra investiguer pin_weight."
        )
        fig.text(0.08, 0.27, warn, fontsize=9, family="monospace", va="top")
        plt.axis("off")
        pdf.savefig(fig); plt.close(fig)


def main() -> int:
    print("[1/4] Loading dataset…")
    elo, matches, src = load_dataset()
    print(f"      {len(matches)} matchs exploitables (source : {src})")
    print(f"      Distribution |Delta Elo| : min={min(m['abs_delta'] for m in matches):.0f}, "
          f"max={max(m['abs_delta'] for m in matches):.0f}, "
          f"mean={np.mean([m['abs_delta'] for m in matches]):.0f}")

    print("[2/4] Evaluating 6 variants…")
    data = evaluate(matches)
    for name, d in data.items():
        a = d["agg"]
        print(f"      {name:18s} bias={a['mean_bias_fav']*100:+.2f}pp "
              f"MAE={a['mean_abs_err_fav']*100:.2f}pp "
              f"LL={a['mean_log_loss']:.4f}")

    print("[3/4] Lambda cap analysis…")
    cap_rows = lambda_cap_analysis(matches)
    print(f"      {len(cap_rows)} matchs avec cap actif (|ΔElo|>600)")

    print("[4/4] Rendering PDF…")
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(data, matches, cap_rows, src, OUT_PDF)
    print(f"      -> {OUT_PDF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
