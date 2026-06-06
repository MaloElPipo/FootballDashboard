"""Backtest des formules lambda V8 prod vs V5 calibree sur CDM 2018 + 2022.

Donnees: eloratings.net (Elo pre-tournoi + resultats des matchs).
Compare 2 formules de derivation lambda et calcule:
  - log-loss 1X2
  - Brier multi-classe
  - MAE Poisson sur scores
  - Calibration (bins)

V8 prod   : baseline=1.25, scale=0.5  (sans WC shrink)
V5 calib  : baseline=1.35, scale=1.2, WC shrink 0.9x en phase poule
"""
from __future__ import annotations
import json
import math
import re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "live" / "data" / "backtest_wc"
OUT = RAW

# ─── Parsing eloratings.net "start" pages ──────────────────────────────────

# Bloc par equipe sur la start page:
#   [Brazil](url)
#   2141           <- Elo
#   4              <- rank
#   1992           <- moyenne all-time
#   0              <- delta rank
#   +26            <- delta Elo
#   ...
# Les 6 premieres lignes suffisent (nom + Elo).

TEAM_LINK_RE = re.compile(r"^\[([^\]]+)\]\(https://www\.eloratings\.net/([^)]+)\)$")

def parse_start_page(text: str) -> dict[str, int]:
    """Retourne {team_name: elo_pretournoi}."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    out: dict[str, int] = {}
    i = 0
    in_table = False
    while i < len(lines):
        if lines[i] == "### Start":
            in_table = True
            i += 1
            continue
        if not in_table:
            i += 1
            continue
        m = TEAM_LINK_RE.match(lines[i])
        if m and i + 1 < len(lines):
            try:
                elo = int(lines[i + 1])
                if 1000 <= elo <= 2300:
                    out[m.group(1)] = elo
            except ValueError:
                pass
        i += 1
    return out


# ─── Parsing eloratings.net "results" pages ────────────────────────────────

# Bloc par match:
#   June 14
#   2018
#   [Russia](url)
#   [Saudi Arabia](url)
#   5
#   0
#   [World Cup](url)
#   [in Russia](url)
#   ...
# On veut: home, away, gh, ga, tournament == World Cup.

MONTH_RE = re.compile(r"^(January|February|March|April|May|June|July|August|"
                      r"September|October|November|December)\s+\d{1,2}$")

def parse_results_page(text: str) -> list[dict]:
    """Retourne les matchs World Cup uniquement."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    matches: list[dict] = []
    i = 0
    while i < len(lines) - 7:
        if MONTH_RE.match(lines[i]):
            date = lines[i]
            year = lines[i + 1] if i + 1 < len(lines) else ""
            t1 = TEAM_LINK_RE.match(lines[i + 2]) if i + 2 < len(lines) else None
            t2 = TEAM_LINK_RE.match(lines[i + 3]) if i + 3 < len(lines) else None
            if t1 and t2:
                try:
                    gh = int(lines[i + 4])
                    ga = int(lines[i + 5])
                    tour_line = lines[i + 6]
                    tm = re.match(r"^\[([^\]]+)\]\(", tour_line)
                    tour = tm.group(1) if tm else tour_line
                    if tour == "World Cup":
                        matches.append({
                            "date": f"{date}, {year}",
                            "home": t1.group(1),
                            "away": t2.group(1),
                            "gh": gh,
                            "ga": ga,
                        })
                    i += 7
                    continue
                except (ValueError, IndexError):
                    pass
        i += 1
    return matches


# ─── Formules lambda ───────────────────────────────────────────────────────

# Source: artifacts/football-dashboard/wc_simulator.py (prod V8)
#   baseline (mu) = 1.25, scale = 0.5, home advantage Elo = 100
# V5 calibre depuis pele_vs_v8_report.py (P4 precalibre):
#   baseline = 1.35, scale = 1.2, alpha_tilt = 0.2 (mais Tilt indispo en backtest)
#   WC shrink poule = 0.9x sur les lambdas

HOME_ADV_ELO = 100  # CDM = terrain neutre sauf hote, mais ici on garde 0 (neutre)

def lambdas_v8(eh: float, ea: float, neutral: bool = True,
                baseline: float = 1.25, scale: float = 0.5) -> tuple[float, float]:
    """Formule prod V8: baseline equilibree + scale lineaire * (Elo_diff/400)."""
    elo_diff = (eh - ea) + (0 if neutral else HOME_ADV_ELO)
    edge = elo_diff / 400.0
    lh = baseline + scale * edge
    la = baseline - scale * edge
    return max(0.15, lh), max(0.15, la)

def lambdas_v5_calib(eh: float, ea: float, neutral: bool = True,
                       baseline: float = 1.35, scale: float = 1.2,
                       wc_shrink: float = 0.9) -> tuple[float, float]:
    """V5 calibre PELE: baseline plus haut, scale 2x plus fort + shrink WC."""
    elo_diff = (eh - ea) + (0 if neutral else HOME_ADV_ELO)
    edge = elo_diff / 400.0
    lh = baseline + scale * edge
    la = baseline - scale * edge
    lh = max(0.15, lh) * wc_shrink
    la = max(0.15, la) * wc_shrink
    return lh, la


# ─── Distribution Poisson independante ─────────────────────────────────────

def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)

def probs_1x2(lh: float, la: float, max_goals: int = 10) -> tuple[float, float, float]:
    """P(home win, draw, away win) sous Poisson independant."""
    ph, pd, pa = 0.0, 0.0, 0.0
    cache_h = [poisson_pmf(i, lh) for i in range(max_goals + 1)]
    cache_a = [poisson_pmf(j, la) for j in range(max_goals + 1)]
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            p = cache_h[i] * cache_a[j]
            if i > j:
                ph += p
            elif i == j:
                pd += p
            else:
                pa += p
    # Renormalise (la queue >max_goals est minime mais propre)
    s = ph + pd + pa
    return ph / s, pd / s, pa / s


# ─── Metriques ──────────────────────────────────────────────────────────────

def outcome(gh: int, ga: int) -> int:
    """0 = home win, 1 = draw, 2 = away win."""
    if gh > ga: return 0
    if gh == ga: return 1
    return 2

def log_loss(probs: tuple[float, float, float], obs: int,
              eps: float = 1e-12) -> float:
    return -math.log(max(eps, probs[obs]))

def brier(probs: tuple[float, float, float], obs: int) -> float:
    one_hot = [0.0, 0.0, 0.0]
    one_hot[obs] = 1.0
    return sum((p - o) ** 2 for p, o in zip(probs, one_hot))


# ─── Mapping noms eloratings -> noms snapshot ──────────────────────────────

# Eloratings utilise les noms anglais entiers. On garde tel quel.
NAME_FIXES = {
    "South Korea": "South Korea",
    "United States": "USA",
    "Korea Republic": "South Korea",
}


def run_backtest() -> dict:
    s18 = parse_start_page((RAW / "raw_2018_start.md").read_text())
    s22 = parse_start_page((RAW / "raw_2022_start.md").read_text())
    m18 = parse_results_page((RAW / "raw_2018_results.md").read_text())
    m22 = parse_results_page((RAW / "raw_2022_results.md").read_text())

    print(f"[parse] 2018: {len(s18)} equipes, {len(m18)} matchs WC")
    print(f"[parse] 2022: {len(s22)} equipes, {len(m22)} matchs WC")

    # On garde uniquement les matchs ou les 2 equipes sont dans le snapshot
    def keep(matches, snap):
        kept, skipped = [], []
        for m in matches:
            h = NAME_FIXES.get(m["home"], m["home"])
            a = NAME_FIXES.get(m["away"], m["away"])
            if h in snap and a in snap:
                kept.append({**m, "eh": snap[h], "ea": snap[a]})
            else:
                skipped.append((m["home"], m["away"]))
        return kept, skipped

    k18, skip18 = keep(m18, s18)
    k22, skip22 = keep(m22, s22)
    print(f"[match] 2018 retenus: {len(k18)}/{len(m18)} (skipped {len(skip18)})")
    print(f"[match] 2022 retenus: {len(k22)}/{len(m22)} (skipped {len(skip22)})")
    if skip18: print(f"        skipped 2018: {skip18[:5]}")
    if skip22: print(f"        skipped 2022: {skip22[:5]}")

    all_matches = k18 + k22

    # Le match d'ouverture du host est techniquement a domicile, mais 32 equipes
    # = la CDM est consideree neutre par convention. On reste neutre.
    # Grid search : on teste plusieurs (baseline, scale, shrink) pour trouver
    # le sweet spot calibration vs log-loss.
    grid = [
        ("V8_prod",      1.25, 0.5, 1.0),  # prod actuelle
        ("V5_calib",     1.35, 1.2, 0.9),  # V5 actuel (surconfiant favoris)
        ("V5b_s10_sh09", 1.35, 1.0, 0.9),  # scale plus doux
        ("V5c_s08_sh09", 1.35, 0.8, 0.9),  # scale encore + doux
        ("V5d_s10_sh10", 1.35, 1.0, 1.0),  # sans shrink WC
        ("V5e_b13_s08",  1.30, 0.8, 1.0),  # baseline + bas, scale doux
        ("V5f_b13_s10",  1.30, 1.0, 0.95),
    ]
    formulas = {
        name: (lambda eh, ea, b=b, s=s, sh=sh:
                lambdas_v5_calib(eh, ea, neutral=True,
                                   baseline=b, scale=s, wc_shrink=sh))
        for name, b, s, sh in grid
    }
    # V8_prod garde la formule prod sans shrink (= V5_calib avec shrink=1.0
    # et baseline=1.25, scale=0.5 — ce qui est equivalent).
    formulas["V8_prod"] = lambda eh, ea: lambdas_v8(eh, ea, neutral=True)

    # ─── Blends lineaires de probabilites (ensembling) ──────────────────────
    # Hypothese : V8 prod sous-confident (compresse milieu), V5 calib
    # surconfident (favoris tranches). Leurs biais sont decorreles → un
    # melange devrait battre les deux individuellement (wisdom of crowds).
    # On teste plusieurs poids alpha sur V8 vs V5_calib (scale=1.2) et
    # V8 vs V5c_s08 (scale=0.8, deploye actuel).
    blends = [
        ("blend50_V8_V5calib", "V8_prod",  "V5_calib",     0.5),
        ("blend30_V8_V5calib", "V8_prod",  "V5_calib",     0.3),  # 30% V8 / 70% PELE
        ("blend70_V8_V5calib", "V8_prod",  "V5_calib",     0.7),  # 70% V8 / 30% PELE
        ("blend50_V8_V5c08",   "V8_prod",  "V5c_s08_sh09", 0.5),
    ]
    all_keys = list(formulas.keys()) + [b[0] for b in blends]

    results = {fname: {
        "n": 0, "log_loss_sum": 0.0, "brier_sum": 0.0,
        "mae_gh": 0.0, "mae_ga": 0.0,
    } for fname in all_keys}
    # Calibration micro-agregee 3 classes : (sum_pred, n_total, n_obs_1) par bin
    calib = {fname: [[0.0, 0, 0] for _ in range(10)] for fname in all_keys}

    for m in all_matches:
        obs = outcome(m["gh"], m["ga"])
        match_probs = {}
        for fname, fn in formulas.items():
            lh, la = fn(m["eh"], m["ea"])
            p = probs_1x2(lh, la)
            match_probs[fname] = p
            r = results[fname]
            r["n"] += 1
            r["log_loss_sum"] += log_loss(p, obs)
            r["brier_sum"] += brier(p, obs)
            r["mae_gh"] += abs(lh - m["gh"])
            r["mae_ga"] += abs(la - m["ga"])
            for idx_class, pc in enumerate(p):
                bin_idx = min(9, int(pc * 10))
                calib[fname][bin_idx][0] += pc
                calib[fname][bin_idx][1] += 1
                calib[fname][bin_idx][2] += (1 if idx_class == obs else 0)
        # Blends : poids alpha sur source A, (1-alpha) sur source B
        for bname, src_a, src_b, alpha in blends:
            pa = match_probs[src_a]
            pb = match_probs[src_b]
            p = tuple(alpha * pa[i] + (1 - alpha) * pb[i] for i in range(3))
            r = results[bname]
            r["n"] += 1
            r["log_loss_sum"] += log_loss(p, obs)
            r["brier_sum"] += brier(p, obs)
            # MAE lambda non defini pour un blend de probas
            r["mae_gh"] = None
            r["mae_ga"] = None
            for idx_class, pc in enumerate(p):
                bin_idx = min(9, int(pc * 10))
                calib[bname][bin_idx][0] += pc
                calib[bname][bin_idx][1] += 1
                calib[bname][bin_idx][2] += (1 if idx_class == obs else 0)

    # ─── Synthese ──────────────────────────────────────────────────────────
    summary = {}
    for fname, r in results.items():
        n = r["n"]
        # Bench: log-loss uniform = ln(3) = 1.0986 (random 1/3 chaque)
        # Bench: log-loss "historical" 1X2 marche neutre ≈ 1.00
        summary[fname] = {
            "n_matches": n,
            "log_loss_mean": round(r["log_loss_sum"] / n, 4) if n else None,
            "brier_mean": round(r["brier_sum"] / n, 4) if n else None,
            "mae_lambda_h": (round(r["mae_gh"] / n, 3)
                            if n and r["mae_gh"] is not None else None),
            "mae_lambda_a": (round(r["mae_ga"] / n, 3)
                            if n and r["mae_ga"] is not None else None),
            "calibration_bins": [
                {
                    "bin": f"{i*10}-{(i+1)*10}%",
                    "n": b[1],
                    "p_moy_predit": round(b[0] / b[1], 3) if b[1] else None,
                    "freq_observee": round(b[2] / b[1], 3) if b[1] else None,
                }
                for i, b in enumerate(calib[fname]) if b[1] > 0
            ],
        }

    # Benchmarks
    n_total = results["V8_prod"]["n"]
    summary["benchmarks"] = {
        "uniform_log_loss": round(math.log(3), 4),  # 1.0986
        "note": "log-loss < 1.0 = mieux qu'un modele uniform; "
                "<0.95 = comparable a un bookmaker grand public; "
                "<0.90 = niveau modele pro.",
        "n_total_matches": n_total,
    }

    # ─── Output ────────────────────────────────────────────────────────────
    out_path = OUT / "backtest_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "summary": summary, "matches": all_matches,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n[ecrit] {out_path}")

    n_total = results["V8_prod"]["n"]

    # Console report : tableau classement (formules + blends)
    ordered = sorted([k for k in all_keys],
                      key=lambda k: summary[k]["log_loss_mean"])
    print("\n" + "=" * 78)
    print(f"  BACKTEST CDM 2018+2022 — Grid search formules lambda (n={n_total})")
    print("=" * 78)
    print(f"  benchmark uniform log-loss = {math.log(3):.4f}")
    print(f"  {'Formule':<16} {'Log-loss':>10}  {'Brier':>8}  "
            f"{'MAE λh':>8}  {'MAE λa':>8}  {'ECE':>7}")
    print("  " + "-" * 64)
    # ECE = expected calibration error (weighted abs diff p_pred vs freq_obs)
    ece = {}
    for fname in all_keys:
        bins = summary[fname]["calibration_bins"]
        tot = sum(b["n"] for b in bins)
        ece[fname] = sum(b["n"] / tot * abs(b["p_moy_predit"] - b["freq_observee"])
                          for b in bins if tot)
    for fname in ordered:
        s = summary[fname]
        mark = "  <-- BEST" if fname == ordered[0] else ""
        mae_h = f"{s['mae_lambda_h']:>8.3f}" if s['mae_lambda_h'] is not None else f"{'-':>8}"
        mae_a = f"{s['mae_lambda_a']:>8.3f}" if s['mae_lambda_a'] is not None else f"{'-':>8}"
        print(f"  {fname:<22} {s['log_loss_mean']:>10.4f}  "
                f"{s['brier_mean']:>8.4f}  {mae_h}  "
                f"{mae_a}  {ece[fname]:>7.4f}{mark}")

    print(f"\n  CALIBRATION {ordered[0]} (best log-loss):")
    for b in summary[ordered[0]]["calibration_bins"]:
        bar = "█" * int((b["freq_observee"] or 0) * 40)
        print(f"    {b['bin']:>8}  n={b['n']:>4}  "
                f"p_pred={b['p_moy_predit']:.2f}  "
                f"freq_obs={b['freq_observee']:.2f}  {bar}")

    # ─── Markdown report ──────────────────────────────────────────────────
    md_path = OUT / "backtest_report.md"
    md = []
    md.append("# Backtest CDM 2018 + 2022 — calibration formule lambda\n")
    md.append(f"Date : {Path(__file__).stat().st_mtime:.0f} | Source : eloratings.net (Elo pre-tournoi + 128 matchs World Cup)\n")
    md.append("## Resultats grid search\n")
    md.append("| Formule | baseline | scale | shrink | Log-loss | Brier | MAE λh | MAE λa | ECE |\n|---|---|---|---|---|---|---|---|---|")
    params_lookup = {n: (b, s, sh) for n, b, s, sh in grid}
    params_lookup["V8_prod"] = (1.25, 0.5, 1.0)
    blend_lookup = {b[0]: (b[1], b[2], b[3]) for b in blends}
    for fname in ordered:
        ss = summary[fname]
        mark = " **BEST**" if fname == ordered[0] else ""
        if fname in blend_lookup:
            src_a, src_b, alpha = blend_lookup[fname]
            params = f"{alpha:.1f}×{src_a} + {1-alpha:.1f}×{src_b}"
            mae_h = "—"
            mae_a = "—"
            md.append(f"| {fname}{mark} | {params} | — | — | "
                        f"{ss['log_loss_mean']:.4f} | {ss['brier_mean']:.4f} | "
                        f"{mae_h} | {mae_a} | {ece[fname]:.4f} |")
        else:
            b, s, sh = params_lookup[fname]
            md.append(f"| {fname}{mark} | {b} | {s} | {sh} | "
                        f"{ss['log_loss_mean']:.4f} | {ss['brier_mean']:.4f} | "
                        f"{ss['mae_lambda_h']:.3f} | {ss['mae_lambda_a']:.3f} | "
                        f"{ece[fname]:.4f} |")
    md.append(f"\nBenchmark : log-loss uniform (1/3 chaque) = {math.log(3):.4f}\n")
    md.append("- **Log-loss** : penalise plus les predictions confiantes mais fausses. Plus bas = mieux.")
    md.append("- **Brier** : erreur quadratique moyenne. Plus bas = mieux.")
    md.append("- **MAE λ** : ecart moyen lambda predit vs buts reels. Mesure la qualite du baseline.")
    md.append("- **ECE** (Expected Calibration Error) : moyenne ponderee |p_pred - freq_obs| par bin. Plus bas = mieux calibre.\n")

    md.append("## Calibration par bin — top 3 formules\n")
    for fname in ordered[:3]:
        md.append(f"### {fname}")
        md.append("| Bin | n | p_pred | freq_obs | gap |\n|---|---|---|---|---|")
        for bn in summary[fname]["calibration_bins"]:
            gap = (bn["freq_observee"] or 0) - (bn["p_moy_predit"] or 0)
            md.append(f"| {bn['bin']} | {bn['n']} | {bn['p_moy_predit']:.2f} | "
                        f"{bn['freq_observee']:.2f} | {gap:+.2f} |")
        md.append("")

    # ─── Verdict ───────────────────────────────────────────────────────────
    best = ordered[0]
    worst = ordered[-1]
    md.append("## Verdict\n")
    delta_v5_vs_v8 = (summary["V5_calib"]["log_loss_mean"]
                        - summary["V8_prod"]["log_loss_mean"])
    delta_best_vs_v8 = (summary[best]["log_loss_mean"]
                          - summary["V8_prod"]["log_loss_mean"])
    md.append(f"- Meilleure formule : **{best}** "
                f"(log-loss {summary[best]['log_loss_mean']:.4f}, "
                f"ECE {ece[best]:.4f})")
    md.append(f"- V8 prod actuel : log-loss {summary['V8_prod']['log_loss_mean']:.4f}, "
                f"ECE {ece['V8_prod']:.4f}")
    md.append(f"- V5 calib (deploye dans PDF) : log-loss "
                f"{summary['V5_calib']['log_loss_mean']:.4f} "
                f"({delta_v5_vs_v8:+.4f} vs V8) — ECE {ece['V5_calib']:.4f}")
    md.append(f"- Gain log-loss best vs V8 : **{delta_best_vs_v8:+.4f}**")
    if delta_best_vs_v8 < -0.005:
        md.append(f"\n**Recommandation : GO** — migrer prod vers `{best}` "
                    f"(amelioration significative).")
    elif delta_best_vs_v8 < 0:
        md.append(f"\n**Recommandation : SHADOW** — `{best}` legerement meilleur, "
                    "tester en shadow-mode avant bascule.")
    else:
        md.append("\n**Recommandation : NO-GO** — aucune formule alternative ne bat "
                    "V8 prod sur 128 matchs. Garder l'existant.")
    md.append("\n## Limitations methodologiques\n")
    md.append("- 128 matchs : n petit. Intervalle de confiance log-loss ~±0.03.")
    md.append("- Pas de Tilt offensif : V5 perd un de ses leviers prevus.")
    md.append("- Elo pre-tournoi ≠ Elo PELE Silver : on teste la structure de la formule, pas le rating system.")
    md.append("- Tournoi neutre force : pas de bonus hote (Russie 2018, Qatar 2022 — biais marginal).")
    md.append("- Poisson independant : pas de correlation Dixon-Coles (sous-estime les nuls 0-0/1-1).")
    Path(md_path).write_text("\n".join(md))
    print(f"\n[ecrit] {md_path}")

    return summary


if __name__ == "__main__":
    run_backtest()
