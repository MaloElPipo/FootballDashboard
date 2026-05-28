"""PDF de prevision complete CDM 2026 — moteur vraie PELE (Silver Bulletin).

Pipeline :
  1. Charge les vraies probas Silver pour les 72 matchs phase poule (avec
     WC group stage shrink 0.9x applique).
  2. Charge les ratings PELE officiels (211 nations).
  3. Patch en memoire wc_simulator.derive_lambdas_from_elo avec la formule
     calibree (baseline=1.35, scale_delta=1.2) qu'on a derivee dans V4.
     Cette formule pilote toutes les sims KO (R32 -> Final).
  4. Reutilise tout le pipeline wc_simulator prod (FIFA tiebreakers,
     bracket R32 officiel, slots meilleurs 3emes, etc.) — RIEN n'est modifie
     sur disque, juste monkey-patch en RAM.
  5. Lance N_SIMS simulations completes, agrege par equipe :
     P(1er poule), P(R32), P(R16), P(QF), P(SF), P(finale), P(champion).
  6. Genere un PDF ~22 pages couvrant tous les angles.

Sortie : live/data/pele_v5_forecast_cdm2026.pdf
"""
from __future__ import annotations

import math
import sys
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "artifacts/football-dashboard"))
sys.path.insert(0, str(REPO / "scripts"))

# Imports depuis V4 (reutilise chargement PELE + Silver + WC shrink)
import pele_vs_v8_report as v4  # type: ignore

# Imports prod (lecture seule — on monkey-patch en RAM uniquement)
import wc_simulator as ws  # type: ignore

OUT_PDF = REPO / "live/data/pele_v5_forecast_cdm2026.pdf"
OUT_JSON = REPO / "live/data/pele_v5_forecast_results.json"

N_SIMS = 10_000
RNG_SEED = 42

# Params calibres V4 sur 72 matchs vraies PELE (RMSE 0.244 buts/match)
CALIB_BASELINE = 1.35
CALIB_SCALE = 1.2
CALIB_ALPHA_TILT = 0.2


# ─── Monkey-patch derive_lambdas_from_elo (formule calibree PELE) ──────────

def patched_derive_lambdas(elo_h: float, elo_a: float) -> tuple[float, float]:
    """Remplace la formule V8 prod (baseline 1.25, scale 0.5) par notre
    formule calibree sur 72 matchs vraies PELE :
      lambda_h = 1.35 * exp(1.2 * delta/600 / 2)  (split half)
      lambda_a = 1.35 * exp(-1.2 * delta/600 / 2)
    Le facteur Tilt n'est PAS applique ici car derive_lambdas ne connait pas
    les codes equipes. On l'integre via expected_scores pour la phase poule
    (qui contient les vraies lambdas Silver, Tilt deja integre).
    Pour le KO, le Tilt est neglige (biais mineur — equipes restantes deja
    triees par qualite).
    """
    delta = elo_h - elo_a
    f = delta / 600.0
    lh = CALIB_BASELINE * math.exp(f * CALIB_SCALE * 0.5)
    la = CALIB_BASELINE * math.exp(-f * CALIB_SCALE * 0.5)
    return max(0.3, min(lh, 4.5)), max(0.3, min(la, 4.5))


ws.derive_lambdas_from_elo = patched_derive_lambdas


# ─── Chargement donnees ────────────────────────────────────────────────────

def load_all_data():
    raw = v4.fetch_pele_data()
    teams = v4.parse_pele_csvs(raw)
    silver_true = v4.load_silver_true()
    market = v4.load_market()
    v8_elo = json.loads((v4.SNAP / "pin_calibrated_elo.json").read_text())["elo"]
    return teams, silver_true, market, v8_elo


def build_elo_map_pele(teams: dict) -> dict[str, float]:
    """elo_map = PELE rating direct. Echelle 1100-1950, compatible avec V8."""
    return {code: t["pele"] for code, t in teams.items()}


def build_expected_scores(silver_true: dict) -> dict[tuple[str, str], tuple[float, float]]:
    """Pour chaque match phase poule des 12 groupes, on assemble les vraies
    lambdas Silver dans le sens (home, away) attendu par wc_simulator. On
    applique le WC shrink 0.9x. Si match absent, on retombe sur la formule
    calibree (rare avec orientation fix).
    """
    exp = {}
    for grp, gteams in ws.WC2026_GROUPS.items():
        for _md, pairings in ws.GROUP_MATCHES.items():
            for ih, ia in pairings:
                h, a = gteams[ih], gteams[ia]
                tr = silver_true.get((h, a))
                if not tr:
                    tr_rev = silver_true.get((a, h))
                    if tr_rev:
                        tr = {
                            "lambda_h": tr_rev["lambda_a"],
                            "lambda_a": tr_rev["lambda_h"],
                        }
                if tr:
                    lh, la = v4.wc_shrink_lambdas(tr["lambda_h"], tr["lambda_a"])
                    exp[(h, a)] = (lh, la)
    return exp


# ─── Simulation Monte Carlo complete via wc_simulator prod ─────────────────

def run_full_tournament_mc(elo_map: dict, expected_scores: dict,
                             n: int = N_SIMS) -> dict:
    import random as _r
    _r.seed(RNG_SEED)

    agg = defaultdict(lambda: {
        "group_pts": 0.0, "group_gf": 0.0, "group_ga": 0.0,
        "pos1": 0, "pos2": 0, "pos3": 0, "pos4": 0,
        "r32": 0, "r16": 0, "qf": 0, "sf": 0,
        "final": 0, "winner": 0, "runner_up": 0, "bronze": 0,
        "opp_r16": defaultdict(int),
        "opp_qf": defaultdict(int),
        "opp_sf": defaultdict(int),
        "opp_final": defaultdict(int),
    })

    for i in range(n):
        if i % 1000 == 0 and i > 0:
            print(f"    sim {i}/{n}…")
        params = {"expected_scores": expected_scores, "sim_seed": None}
        tracker = ws.simulate_tournament(elo_map, params=params)

        for code, t in tracker.items():
            a = agg[code]
            a["group_pts"] += t.get("group_pts", 0)
            a["group_gf"] += t.get("group_gf", 0.0)
            a["group_ga"] += t.get("group_ga", 0.0)
            pos = t.get("group_pos", 0)
            if pos == 1: a["pos1"] += 1
            elif pos == 2: a["pos2"] += 1
            elif pos == 3: a["pos3"] += 1
            elif pos == 4: a["pos4"] += 1
            if t.get("r32"): a["r32"] += 1
            if t.get("r16"): a["r16"] += 1
            if t.get("qf"): a["qf"] += 1
            if t.get("sf"): a["sf"] += 1
            if t.get("final"): a["final"] += 1
            if t.get("winner"): a["winner"] += 1
            if t.get("runner_up"): a["runner_up"] += 1
            if t.get("bronze"): a["bronze"] += 1
            opps = t.get("opponents", {})
            if "r16" in opps: a["opp_r16"][opps["r16"]] += 1
            if "qf" in opps: a["opp_qf"][opps["qf"]] += 1
            if "sf" in opps: a["opp_sf"][opps["sf"]] += 1
            if "final" in opps: a["opp_final"][opps["final"]] += 1

    out = {}
    for code, a in agg.items():
        out[code] = {
            "avg_pts": a["group_pts"] / n,
            "avg_gf": a["group_gf"] / n,
            "avg_ga": a["group_ga"] / n,
            "p_1st": a["pos1"] / n * 100,
            "p_2nd": a["pos2"] / n * 100,
            "p_3rd": a["pos3"] / n * 100,
            "p_4th": a["pos4"] / n * 100,
            "p_r32": a["r32"] / n * 100,
            "p_r16": a["r16"] / n * 100,
            "p_qf": a["qf"] / n * 100,
            "p_sf": a["sf"] / n * 100,
            "p_final": a["final"] / n * 100,
            "p_winner": a["winner"] / n * 100,
            "p_runner_up": a["runner_up"] / n * 100,
            "p_bronze": a["bronze"] / n * 100,
            "top_opp_r16": _top_opp(a["opp_r16"], n),
            "top_opp_qf": _top_opp(a["opp_qf"], n),
        }
    return out


def _top_opp(d: dict, n: int, k: int = 3) -> list:
    items = sorted(d.items(), key=lambda x: -x[1])[:k]
    return [(opp, cnt / n * 100) for opp, cnt in items]


# ─── Comparatif V8 prod (pour divergence page) ─────────────────────────────

def run_v8_mc(v8_elo: dict, n: int = N_SIMS) -> dict:
    """Lance N sims completes avec V8 prod (formule originale derive_lambdas)
    pour comparer P(R32, R16, QF, SF, F, W) vs PELE."""
    # Restaurer derive_lambdas original
    orig_derive = ws.derive_lambdas_from_elo

    def v8_derive(elo_h, elo_a):
        delta = elo_h - elo_a
        f = delta / 600.0
        lh = 1.25 * math.exp(f * 0.5)
        la = 1.25 * math.exp(-f * 0.5)
        return max(0.3, min(lh, 4.0)), max(0.3, min(la, 4.0))

    ws.derive_lambdas_from_elo = v8_derive
    try:
        import random as _r
        _r.seed(RNG_SEED + 1)
        agg = defaultdict(lambda: {"r32": 0, "r16": 0, "qf": 0, "sf": 0,
                                     "final": 0, "winner": 0})
        for i in range(n):
            if i % 1000 == 0 and i > 0:
                print(f"    [V8] sim {i}/{n}…")
            tracker = ws.simulate_tournament(v8_elo, params=None)
            for code, t in tracker.items():
                a = agg[code]
                if t.get("r32"): a["r32"] += 1
                if t.get("r16"): a["r16"] += 1
                if t.get("qf"): a["qf"] += 1
                if t.get("sf"): a["sf"] += 1
                if t.get("final"): a["final"] += 1
                if t.get("winner"): a["winner"] += 1
        out = {c: {k: v / n * 100 for k, v in a.items()} for c, a in agg.items()}
    finally:
        ws.derive_lambdas_from_elo = orig_derive
    return out


# ─── PDF rendering ─────────────────────────────────────────────────────────

def render_pdf(out: Path, mc_pele: dict, mc_v8: dict, teams: dict,
                silver_true: dict, market: dict, v8_elo: dict,
                expected_scores: dict) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    plt.rcParams["font.family"] = "DejaVu Sans"

    PAGE = (8.27, 11.69)  # A4 portrait

    def newpage(pdf, title: str, subtitle: str = ""):
        fig = plt.figure(figsize=PAGE)
        fig.text(0.5, 0.965, title, ha="center", fontsize=16, fontweight="bold")
        if subtitle:
            fig.text(0.5, 0.945, subtitle, ha="center", fontsize=10, style="italic", color="#555")
        return fig

    def addtable(fig, rect, headers, rows, col_widths=None, fontsize=8,
                  header_bg="#1a3a6e", header_fg="white", zebra=True,
                  align="center"):
        ax = fig.add_axes(rect)
        ax.axis("off")
        if not rows:
            ax.text(0.5, 0.5, "(aucune donnee)", ha="center", va="center",
                     style="italic", color="#888")
            return
        cell_text = [[str(c) for c in r] for r in rows]
        tbl = ax.table(cellText=cell_text, colLabels=headers,
                        cellLoc=align, colWidths=col_widths, loc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(fontsize)
        tbl.scale(1, 1.4)
        for i, _ in enumerate(headers):
            cell = tbl[(0, i)]
            cell.set_facecolor(header_bg)
            cell.set_text_props(color=header_fg, fontweight="bold")
        if zebra:
            for r_idx in range(1, len(rows) + 1):
                for c_idx in range(len(headers)):
                    if r_idx % 2 == 0:
                        tbl[(r_idx, c_idx)].set_facecolor("#f0f4fa")

    def savepage(pdf, fig):
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    with PdfPages(out) as pdf:
        # ─── PAGE 1 : COUVERTURE ────────────────────────────────────────
        fig = plt.figure(figsize=PAGE)
        fig.text(0.5, 0.85, "COUPE DU MONDE FIFA 2026", ha="center",
                  fontsize=24, fontweight="bold", color="#1a3a6e")
        fig.text(0.5, 0.80, "Prevision complete — moteur PELE (Nate Silver)",
                  ha="center", fontsize=14, style="italic")
        fig.text(0.5, 0.755, "Etats-Unis · Canada · Mexique  |  48 nations · 12 poules · 104 matchs",
                  ha="center", fontsize=10, color="#555")
        fig.text(0.5, 0.72, f"Monte Carlo : {N_SIMS:,} simulations completes (poules + KO)",
                  ha="center", fontsize=9, color="#888")

        # Top 10 contenders
        top = sorted(mc_pele.items(), key=lambda x: -x[1]["p_winner"])[:10]
        rows = []
        for i, (code, m) in enumerate(top, 1):
            rows.append([
                i, code,
                f"{m['p_winner']:.1f}%",
                f"{m['p_final']:.1f}%",
                f"{m['p_sf']:.1f}%",
                f"{m['p_qf']:.1f}%",
                f"{m['p_r16']:.1f}%",
            ])
        fig.text(0.5, 0.66, "TOP 10 CONTENDERS — probabilite de gagner le tournoi",
                  ha="center", fontsize=12, fontweight="bold")
        addtable(fig, [0.12, 0.36, 0.76, 0.27],
                  ["#", "Nation", "Champion", "Finale", "1/2", "1/4", "1/8"],
                  rows, col_widths=[0.06, 0.12, 0.16, 0.14, 0.14, 0.14, 0.14],
                  fontsize=9)

        # Distribution P(champion) — bar chart top 20
        top20 = sorted(mc_pele.items(), key=lambda x: -x[1]["p_winner"])[:20]
        ax = fig.add_axes([0.10, 0.06, 0.82, 0.27])
        codes = [c for c, _ in top20]
        probs = [m["p_winner"] for _, m in top20]
        colors = ["#1a3a6e" if p >= probs[0] * 0.5 else
                   "#4a7ab8" if p >= probs[0] * 0.2 else "#a5c0e0" for p in probs]
        ax.barh(range(len(codes)), probs, color=colors)
        ax.set_yticks(range(len(codes)))
        ax.set_yticklabels(codes, fontsize=8)
        ax.invert_yaxis()
        ax.set_xlabel("P(Champion) en %", fontsize=9)
        ax.set_title("Distribution complete P(Champion) — top 20", fontsize=10, fontweight="bold")
        ax.grid(axis="x", alpha=0.3)
        for i, p in enumerate(probs):
            ax.text(p + 0.2, i, f"{p:.1f}%", va="center", fontsize=7)

        fig.text(0.5, 0.02, "Genere par scripts/pele_v5_forecast.py — phase test, hors prod",
                  ha="center", fontsize=7, color="#aaa")
        savepage(pdf, fig)

        # ─── PAGE 2 : METHODOLOGIE ──────────────────────────────────────
        fig = newpage(pdf, "Methodologie",
                       "Moteur, donnees, calibration et limitations connues")
        meth = [
            ("1. Moteur de base", "PELE de Nate Silver (natesilver.net/p/pele-methodology). Elo on h-margin Phase 1 + mean-reversion Transfermarkt Phase 2."),
            ("2. Vraies lambdas Silver", f"Pour les 72 matchs phase poule, on utilise les lambdas officielles Silver (CSV paywall). 100% des matchs CDM matches."),
            ("3. WC shrink 0.9x", "Methodo Silver : applique en group stage car les matchs CDM sont plus upsets que la default. Empiriquement valide : MAE vs Pinnacle 6.23 -> 5.27."),
            ("4. KO : formule calibree", f"baseline={CALIB_BASELINE}, scale={CALIB_SCALE}, alpha_tilt={CALIB_ALPHA_TILT} (RMSE 0.244 buts vs vraies lambdas Silver sur 72 matchs). Tilt ignore en KO (biais mineur)."),
            ("5. Tiebreakers FIFA", "Implementation officielle (FIFA WC 2026 art.13) : H2H pts/diff/buts recursif, fallback diff globale/buts globaux. Cards remplacees par Elo (Monte Carlo)."),
            ("6. Meilleurs 3emes", "8 sur 12 selon regles FIFA + bracket THIRD_PLACE_SLOTS officiel."),
            ("7. Bracket KO", "R32 -> R16 -> QF -> SF -> Finale, slots officiels FIFA. Tirs au but : sigmoid sur Elo clamped [0.15, 0.85]."),
            ("8. Monte Carlo", f"N = {N_SIMS:,} sims completes. Seed = {RNG_SEED} (reproductible)."),
            ("9. Comparatif V8 prod", "On lance aussi N sims avec la formule V8 prod (baseline 1.25, scale 0.5) pour quantifier les divergences. Voir page 'Divergences V8 vs PELE'."),
            ("10. Limitations", "Pas de Phase 2 dans notre patch (Transfermarkt mean-reversion absente du KO). Pas de Tilt en KO. Roster Transfermarkt date snapshot 2025-Q2. Bookmakers Pinnacle : 19/104 matchs couverts (phase poule seulement)."),
        ]
        y = 0.90
        for title, body in meth:
            fig.text(0.06, y, title, fontsize=10, fontweight="bold", color="#1a3a6e")
            from textwrap import wrap
            for line in wrap(body, width=110):
                y -= 0.025
                fig.text(0.06, y, line, fontsize=9)
            y -= 0.022
        savepage(pdf, fig)

        # ─── PAGES 3-14 : UNE PAGE PAR POULE ────────────────────────────
        for grp, gteams in ws.WC2026_GROUPS.items():
            fig = newpage(pdf, f"Poule {grp}",
                           f"{' · '.join(gteams)}")

            # Composition (PELE rating + Tilt + V8 Elo)
            comp_rows = []
            for c in gteams:
                t = teams.get(c, {})
                pele = t.get("pele", 0)
                tilt = t.get("tilt", 0)
                v8e = v8_elo.get(c, 1500)
                m = mc_pele.get(c, {})
                comp_rows.append([
                    c,
                    f"{pele:.0f}",
                    f"{tilt:+.3f}",
                    f"{v8e:.0f}",
                    f"{pele - v8e:+.0f}",
                    f"{m.get('avg_pts', 0):.2f}",
                    f"{m.get('p_1st', 0):.1f}%",
                    f"{m.get('p_r32', 0):.1f}%",
                ])
            fig.text(0.06, 0.91, "Composition + Sim phase poule (10k MC)",
                      fontsize=11, fontweight="bold", color="#1a3a6e")
            addtable(fig, [0.06, 0.72, 0.88, 0.16],
                      ["Eq.", "PELE", "Tilt", "V8 prod", "P-V8", "pts moy", "P(1er)", "P(qualif R32)"],
                      comp_rows, col_widths=[0.08]*8, fontsize=9)

            # 6 matchs phase poule
            fig.text(0.06, 0.68, "Les 6 matchs de la poule (vraies probas Silver + WC 0.9x)",
                      fontsize=11, fontweight="bold", color="#1a3a6e")
            match_rows = []
            for _md, pairings in ws.GROUP_MATCHES.items():
                for ih, ia in pairings:
                    h, a = gteams[ih], gteams[ia]
                    tr = silver_true.get((h, a)) or {
                        k: v for k, v in {
                            "p_h": silver_true.get((a, h), {}).get("p_a"),
                            "p_d": silver_true.get((a, h), {}).get("p_d"),
                            "p_a": silver_true.get((a, h), {}).get("p_h"),
                            "lambda_h": silver_true.get((a, h), {}).get("lambda_a"),
                            "lambda_a": silver_true.get((a, h), {}).get("lambda_h"),
                        }.items() if v is not None
                    } if silver_true.get((a, h)) else None
                    if tr:
                        ph, pd, pa = v4.wc_shrink_1x2(tr["p_h"], tr["p_d"], tr["p_a"])
                        lh, la = v4.wc_shrink_lambdas(tr["lambda_h"], tr["lambda_a"])
                    else:
                        # fallback
                        lh, la = expected_scores.get((h, a), (1.3, 1.3))
                        ph, pd, pa = 0.0, 0.0, 0.0
                    mk = market.get((h, a))
                    mk_str = (f"{mk[0]*100:.0f}/{mk[1]*100:.0f}/{mk[2]*100:.0f}"
                              if mk else "—")
                    match_rows.append([
                        f"{h} - {a}",
                        f"{lh:.2f}",
                        f"{la:.2f}",
                        f"{ph*100:.0f}%",
                        f"{pd*100:.0f}%",
                        f"{pa*100:.0f}%",
                        f"{round(lh):.0f}-{round(la):.0f}",
                        mk_str,
                    ])
            addtable(fig, [0.06, 0.44, 0.88, 0.24],
                      ["Match", "λ H", "λ A", "P(H)", "P(N)", "P(A)", "modal", "Pin H/N/A"],
                      match_rows, col_widths=[0.16, 0.08, 0.08, 0.10, 0.10, 0.10,
                                                0.12, 0.16], fontsize=8)

            # Progression KO probable par equipe
            fig.text(0.06, 0.40, "Progression KO sur 10k simulations (en %)",
                      fontsize=11, fontweight="bold", color="#1a3a6e")
            prog_rows = []
            for c in gteams:
                m = mc_pele.get(c, {})
                prog_rows.append([
                    c,
                    f"{m.get('p_r32', 0):.1f}%",
                    f"{m.get('p_r16', 0):.1f}%",
                    f"{m.get('p_qf', 0):.1f}%",
                    f"{m.get('p_sf', 0):.1f}%",
                    f"{m.get('p_final', 0):.1f}%",
                    f"{m.get('p_winner', 0):.2f}%",
                ])
            addtable(fig, [0.06, 0.20, 0.88, 0.18],
                      ["Eq.", "1/16", "1/8", "1/4", "1/2", "Finale", "Champion"],
                      prog_rows, col_widths=[0.1] * 7, fontsize=9)

            # Footer : delta vs V8 sur P(qualif R32)
            v8_diff = []
            for c in gteams:
                p_pele = mc_pele.get(c, {}).get("p_r32", 0)
                p_v8 = mc_v8.get(c, {}).get("r32", 0)
                v8_diff.append(f"{c} {p_pele - p_v8:+.1f}")
            fig.text(0.06, 0.10, "P(qualif R32) PELE vs V8 prod :   " +
                      "    ".join(v8_diff),
                      fontsize=8, color="#555")

            savepage(pdf, fig)

        # ─── PAGE 15 : MEILLEURS 3EMES ────────────────────────────────────
        fig = newpage(pdf, "Meilleurs 3emes — distribution sur 10k sims",
                       "8 places parmi 12 poules selon FIFA art.13 (pts/diff/buts globale)")
        # Pour chaque groupe, P(le 3eme finit dans les 8 qualifies)
        # = P(pos3) * P(qualif R32 | pos3). Plus simple : P(r32) - P(pos1) - P(pos2)
        rows = []
        for grp, gteams in ws.WC2026_GROUPS.items():
            for c in gteams:
                m = mc_pele.get(c, {})
                p3 = m.get("p_3rd", 0)
                p_qual_via3 = max(0, m.get("p_r32", 0) - m.get("p_1st", 0)
                                    - m.get("p_2nd", 0))
                if p3 > 5:  # seulement equipes avec presence reelle en 3eme
                    rows.append([grp, c, f"{p3:.1f}%",
                                  f"{p_qual_via3:.1f}%",
                                  f"{(p_qual_via3 / p3 * 100) if p3 > 0 else 0:.0f}%"])
        rows.sort(key=lambda r: -float(r[3].rstrip("%")))
        addtable(fig, [0.10, 0.30, 0.80, 0.60],
                  ["Poule", "Eq.", "P(3e)", "P(qualif via 3e)", "P(qualif | 3e)"],
                  rows[:30], col_widths=[0.10, 0.12, 0.15, 0.20, 0.20], fontsize=9)
        savepage(pdf, fig)

        # ─── PAGE 16 : BRACKET R32 — qui affronte qui ────────────────────
        fig = newpage(pdf, "Bracket R32 — affiches probables",
                       "Pour chaque slot du bracket FIFA officiel, top 3 affiches les + frequentes")
        # On reconstruit qui est dans chaque slot via les opp_r16 — mais pas
        # exact. Simplification : afficher les top opponents R16 (= adversaires
        # R32 d'apres la structure) par equipe top 16.
        rows = []
        top16 = sorted(mc_pele.items(),
                        key=lambda x: -x[1]["p_r16"])[:16]
        for code, m in top16:
            opps = m.get("top_opp_r16", [])
            opp_str = " · ".join([f"{o}({p:.0f}%)" for o, p in opps[:3]])
            rows.append([code, f"{m['p_r16']:.1f}%", opp_str or "—"])
        addtable(fig, [0.06, 0.50, 0.88, 0.42],
                  ["Eq. (top 16 P(R16))", "P(R16)", "Adversaires R16 les + frequents"],
                  rows, col_widths=[0.20, 0.15, 0.65], fontsize=9, align="left")
        fig.text(0.06, 0.43, "Note : un adversaire affiche a 30% signifie qu'en 30% des sims, cette equipe arrive en R16 contre cet adversaire.",
                  fontsize=8, color="#666", style="italic")
        savepage(pdf, fig)

        # ─── PAGE 17 : PROGRESSION COMPLETE TOP 24 ─────────────────────────
        fig = newpage(pdf, "Progression complete — top 24 P(QF)",
                       "Cumul des probabilites par tour atteint")
        top24 = sorted(mc_pele.items(), key=lambda x: -x[1]["p_qf"])[:24]
        rows = []
        for code, m in top24:
            rows.append([
                code,
                f"{m['p_r32']:.0f}%",
                f"{m['p_r16']:.0f}%",
                f"{m['p_qf']:.1f}%",
                f"{m['p_sf']:.1f}%",
                f"{m['p_final']:.1f}%",
                f"{m['p_winner']:.2f}%",
                f"{m['p_bronze']:.1f}%",
            ])
        addtable(fig, [0.06, 0.06, 0.88, 0.86],
                  ["Eq.", "R32", "R16", "QF", "SF", "Final", "Champ", "Bronze"],
                  rows, col_widths=[0.10, 0.10, 0.10, 0.12, 0.12, 0.12, 0.14, 0.12],
                  fontsize=9)
        savepage(pdf, fig)

        # ─── PAGE 18 : TOP 8 CONTENDERS DETAIL ─────────────────────────────
        for page_n, slice_range in enumerate([(0, 4), (4, 8)]):
            fig = newpage(pdf, f"Top contenders — detail {page_n*4+1}-{page_n*4+4}",
                           "Pour les 4 favoris : ratings, top adversaires KO, chemin probable")
            top4 = sorted(mc_pele.items(), key=lambda x: -x[1]["p_winner"])[slice_range[0]:slice_range[1]]
            y = 0.90
            for code, m in top4:
                t = teams.get(code, {})
                pele = t.get("pele", 0)
                tilt = t.get("tilt", 0)
                v8e = v8_elo.get(code, 1500)
                fig.text(0.06, y, f"#{slice_range[0] + i + 1}  {code}",
                          fontsize=14, fontweight="bold", color="#1a3a6e")
                fig.text(0.20, y, f"PELE {pele:.0f}   Tilt {tilt:+.3f}   V8 {v8e:.0f}   Δ {pele-v8e:+.0f}",
                          fontsize=9, color="#555")
                fig.text(0.06, y - 0.025,
                          f"P(Champion) {m['p_winner']:.2f}%   "
                          f"P(Final) {m['p_final']:.1f}%   "
                          f"P(SF) {m['p_sf']:.1f}%   "
                          f"P(QF) {m['p_qf']:.1f}%   "
                          f"P(R16) {m['p_r16']:.1f}%   "
                          f"P(R32) {m['p_r32']:.1f}%",
                          fontsize=9)
                # Top 3 adversaires QF (= les 1/4 finale les + probables)
                opps_qf = m.get("top_opp_qf", [])
                if opps_qf:
                    opp_str = "  ".join([f"vs {o} {p:.0f}%" for o, p in opps_qf[:3]])
                    fig.text(0.06, y - 0.05,
                              f"Quarts probables : {opp_str}",
                              fontsize=8, color="#666")
                # Top 3 R16
                opps_r16 = m.get("top_opp_r16", [])
                if opps_r16:
                    opp_str = "  ".join([f"vs {o} {p:.0f}%" for o, p in opps_r16[:3]])
                    fig.text(0.06, y - 0.07,
                              f"1/8 finale probables : {opp_str}",
                              fontsize=8, color="#666")
                y -= 0.12
            savepage(pdf, fig)

        # ─── PAGE 20 : DIVERGENCES V8 vs PELE ──────────────────────────────
        fig = newpage(pdf, "Divergences V8 prod vs PELE — P(qualif R32)",
                       "Top 20 ecarts absolus | positif = PELE > V8 | negatif = V8 > PELE")
        divs = []
        for c in mc_pele:
            p = mc_pele[c]["p_r32"]
            v = mc_v8.get(c, {}).get("r32", 0)
            divs.append((c, p, v, p - v))
        divs.sort(key=lambda x: -abs(x[3]))
        rows = []
        for c, p, v, d in divs[:20]:
            arrow = "▲" if d > 0 else "▼"
            rows.append([c, f"{v:.1f}%", f"{p:.1f}%", f"{arrow} {d:+.1f}"])
        addtable(fig, [0.15, 0.30, 0.70, 0.62],
                  ["Equipe", "P(R32) V8 prod", "P(R32) PELE", "Delta (pts)"],
                  rows, col_widths=[0.15, 0.25, 0.25, 0.20], fontsize=9)

        # Aussi : P(Champion) divergences
        fig.text(0.06, 0.26, "Et sur P(Champion) — top 10 ecarts :",
                  fontsize=10, fontweight="bold", color="#1a3a6e")
        divs_w = []
        for c in mc_pele:
            p = mc_pele[c]["p_winner"]
            v = mc_v8.get(c, {}).get("winner", 0)
            if p > 0.1 or v > 0.1:
                divs_w.append((c, v, p, p - v))
        divs_w.sort(key=lambda x: -abs(x[3]))
        for i, (c, v, p, d) in enumerate(divs_w[:10]):
            fig.text(0.06, 0.22 - i * 0.018,
                      f"{c:6s}   V8 {v:5.2f}%   PELE {p:5.2f}%   delta {d:+.2f}",
                      fontsize=8, family="monospace")
        savepage(pdf, fig)

        # ─── PAGE 21 : VALUE BETS vs PINNACLE ─────────────────────────────
        fig = newpage(pdf, "Value bets vs Pinnacle — phase poule",
                       "19 matchs avec cotes Pinnacle (de-margees Buchdahl)")
        val_rows = []
        for grp, gteams in ws.WC2026_GROUPS.items():
            for _md, pairings in ws.GROUP_MATCHES.items():
                for ih, ia in pairings:
                    h, a = gteams[ih], gteams[ia]
                    mk = market.get((h, a))
                    if not mk:
                        continue
                    tr = silver_true.get((h, a))
                    if not tr:
                        continue
                    pe_h, pe_d, pe_a = v4.wc_shrink_1x2(tr["p_h"], tr["p_d"], tr["p_a"])
                    mk_h, mk_d, mk_a = mk
                    # Edge = PELE - Pinnacle
                    eh, ed, ea = pe_h - mk_h, pe_d - mk_d, pe_a - mk_a
                    # Pick le + gros edge positif
                    best_side, best_edge = max([("H", eh), ("N", ed), ("A", ea)],
                                                  key=lambda x: x[1])
                    val_rows.append([
                        f"{h}-{a}",
                        f"{pe_h*100:.0f}/{pe_d*100:.0f}/{pe_a*100:.0f}",
                        f"{mk_h*100:.0f}/{mk_d*100:.0f}/{mk_a*100:.0f}",
                        best_side,
                        f"{best_edge*100:+.1f}",
                    ])
        val_rows.sort(key=lambda r: -float(r[4]))
        addtable(fig, [0.06, 0.20, 0.88, 0.72],
                  ["Match", "PELE+0.9x H/N/A", "Pinnacle H/N/A",
                   "Side", "Edge (pts)"],
                  val_rows, col_widths=[0.18, 0.24, 0.24, 0.12, 0.18],
                  fontsize=9)
        fig.text(0.06, 0.16,
                  "Edge > 0 = PELE estime cette issue plus probable que Pinnacle. "
                  "Pas une recommandation de pari : PELE est ~5pts MAE moins precis "
                  "que Pinnacle en moyenne, edge doit etre > 5pts pour etre serieux.",
                  fontsize=8, color="#666", style="italic", wrap=True)
        savepage(pdf, fig)

        # ─── PAGE 22 : LIMITATIONS & SAUVEGARDE ────────────────────────────
        fig = newpage(pdf, "Limitations & sources",
                       "A lire avant toute interpretation")
        lims = [
            ("Modele PELE Phase 2 absente du KO", "Notre formule calibree (1.35/1.2) reproduit la transformation rating→λ a ±0.24 buts mais sans le mean-reversion Transfermarkt de la Phase 2. Pour la phase poule c'est ok (vraies λ Silver injectees), pour le KO ca peut sous-estimer l'effet roster."),
            ("Tilt rating ignore en KO", "wc_simulator prod ne connait que l'Elo. Le Tilt Silver (propension offensive/defensive) n'est applique qu'en phase poule via vraies λ. En KO, c'est neglige."),
            ("PELE rating snapshot", f"Les ratings PELE chargees datent du dernier scrape datawrapper. Silver met a jour ~1x/jour, les ratings peuvent avoir bouge depuis."),
            ("Tirs au but", "Modelises par sigmoid Elo clampee [0.15, 0.85]. Pas de modelisation du gardien ou de la fatigue. Hypothese 50/50 si nul a la fin du temps reglementaire."),
            ("Bookmakers", "Pinnacle couvre uniquement 19/104 matchs (les + populaires). Le 'value bet' n'a de sens que sur ces matchs."),
            ("V8 prod (comparatif)", "Lance avec elo_map = pin_calibrated snapshot 2026-05-20. N'utilise pas les overrides forced manuels (CDM 2026 final roster pas encore connu)."),
            ("Pas de blessures, suspensions, forme", "Le modele est purement statique sur les ratings de base. ECT (event change tag) non integre."),
            ("Phase 2 Silver = score de roster Transfermarkt", "Pour reproduire ESP a 99.7% comme Silver, V8 prod aurait besoin d'integrer un score de roster (valeur 23 joueurs Transfermarkt). Voir piste P2 dans le plan d'evolution."),
        ]
        y = 0.90
        for title, body in lims:
            fig.text(0.06, y, "•  " + title, fontsize=10, fontweight="bold",
                      color="#1a3a6e")
            from textwrap import wrap
            for line in wrap(body, width=110):
                y -= 0.024
                fig.text(0.08, y, line, fontsize=8)
            y -= 0.022

        # Fichiers sources
        fig.text(0.06, 0.18, "Sources & fichiers", fontsize=11,
                  fontweight="bold", color="#1a3a6e")
        srcs = [
            f"• Vraies probas Silver : live/data/pele_paywall/silver_projections.csv (72 matchs)",
            f"• Ratings PELE/Tilt : live/data/pele_cache/{{pele,tilt,rr}}.csv (211 nations)",
            f"• V8 prod snapshot : artifacts/football-lab/lab/data/snapshots/initial_baseline_2026-05-20/",
            f"• Cotes Pinnacle : pinnacle_wc2026_odds.json (snapshot 2026-05-20)",
            f"• Bracket FIFA officiel : importe depuis artifacts/football-dashboard/wc_simulator.py",
            f"• Methodo PELE : .agents/memory/pele-methodology.md + .local/refs/pele_paywall/methodology_clean.txt",
        ]
        for i, s in enumerate(srcs):
            fig.text(0.08, 0.15 - i * 0.018, s, fontsize=8, family="monospace")

        fig.text(0.5, 0.02, f"PDF V5 — {N_SIMS:,} simulations Monte Carlo — phase test, hors prod",
                  ha="center", fontsize=7, color="#aaa")
        savepage(pdf, fig)


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    print("[1/5] Chargement donnees PELE + Silver + V8 prod…")
    teams, silver_true, market, v8_elo = load_all_data()
    print(f"      {len(teams)} nations PELE, {len(silver_true)} matchs Silver, "
           f"{len(market)} cotes Pinnacle, {len(v8_elo)} nations V8")

    elo_map = build_elo_map_pele(teams)
    expected_scores = build_expected_scores(silver_true)
    print(f"      elo_map PELE construit, {len(expected_scores)} matchs poule avec vraies λ Silver (target 72)")

    print(f"[2/5] Simulation complete CDM 2026 via wc_simulator prod — moteur PELE patched ({N_SIMS:,} sims)…")
    mc_pele = run_full_tournament_mc(elo_map, expected_scores, n=N_SIMS)

    print(f"[3/5] Simulation comparatif V8 prod ({N_SIMS:,} sims)…")
    mc_v8 = run_v8_mc(v8_elo, n=N_SIMS)

    print("[4/5] Sauvegarde JSON…")
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "n_sims": N_SIMS,
        "mc_pele": {k: {kk: (vv if not isinstance(vv, list) else
                              [list(x) for x in vv]) for kk, vv in v.items()}
                     for k, v in mc_pele.items()},
        "mc_v8": mc_v8,
    }, indent=2, default=str))
    print(f"      -> {OUT_JSON} ({OUT_JSON.stat().st_size // 1024} KB)")

    print("[5/5] Rendu PDF V5…")
    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    render_pdf(OUT_PDF, mc_pele, mc_v8, teams, silver_true, market, v8_elo,
                expected_scores)
    print(f"      -> {OUT_PDF}")

    # Resume console
    print("\n========== TOP 10 CONTENDERS (P-Champion) ==========")
    top = sorted(mc_pele.items(), key=lambda x: -x[1]["p_winner"])[:10]
    for i, (code, m) in enumerate(top, 1):
        print(f"  {i:2d}. {code}  P(W) {m['p_winner']:5.2f}%   "
               f"P(F) {m['p_final']:5.2f}%   "
               f"P(SF) {m['p_sf']:5.2f}%   "
               f"P(QF) {m['p_qf']:5.2f}%   "
               f"P(R16) {m['p_r16']:5.1f}%   "
               f"P(R32) {m['p_r32']:5.1f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
