"""Phase 3 — UI xG totaux poules CDM + meilleurs 3emes."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lab.cdm import pool_xg as PX
from lab.calibration import invert_market as IM


def section_pool_breakdown():
    st.subheader("Par poule — xG totaux equipe (model vs market)")
    st.caption(
        "Saisir/charger les 12 poules CDM avec lambdas modele + lambdas market "
        "(sortie triple inversion phase 1). Boucle B : ajuster Elo si gap > 0.5/match."
    )
    st.info(
        "L'integration complete avec les squads CDM 26 sera faite par un module "
        "downstream (lab/cdm/wc26_data.py a connecter depuis le snapshot prod "
        "pinnacle_wc2026_odds.json). Ici on travaille en mode synthetique pour "
        "valider l'algorithme."
    )

    st.markdown("### Demo synthetique — 1 poule (A) avec 4 equipes")
    # Demo synthetique
    teams = ["A1", "A2", "A3", "A4"]
    rng = np.random.default_rng(1)
    pools = {}
    for ti, t in enumerate(teams):
        # 3 matchs : vs les 3 autres
        matches = []
        for tj, opp in enumerate(teams):
            if opp == t:
                continue
            home = (ti + tj) % 2 == 0
            lh_mod = 1.0 + 0.4 * (1 if ti < tj else -1)
            la_mod = 1.0 - 0.2 * (1 if ti < tj else -1)
            lh_mkt = lh_mod + rng.normal(0, 0.15)
            la_mkt = la_mod + rng.normal(0, 0.15)
            matches.append({
                "opp": opp, "home": home,
                "lambda_model_h": max(0.2, lh_mod),
                "lambda_model_a": max(0.2, la_mod),
                "lambda_market_h": max(0.2, lh_mkt),
                "lambda_market_a": max(0.2, la_mkt),
            })
        pools[t] = PX.compute_pool_xg(t, matches)

    df = pd.DataFrame([{
        "team": p.team_id,
        "xgf_model": p.xgf_model, "xgf_market": p.xgf_market,
        "delta_xgf": p.delta_xgf,
        "xga_model": p.xga_model, "xga_market": p.xga_market,
        "delta_xga": p.delta_xga,
        "delta_per_match": p.delta_per_match,
    } for p in pools.values()])
    st.dataframe(
        df.style.format({
            "xgf_model": "{:.2f}", "xgf_market": "{:.2f}", "delta_xgf": "{:+.2f}",
            "xga_model": "{:.2f}", "xga_market": "{:.2f}", "delta_xga": "{:+.2f}",
            "delta_per_match": "{:.3f}",
        }),
        hide_index=True, width="stretch",
    )

    st.subheader("Boucle B : ajustement Elo")
    elo_init = {"A1": 1850, "A2": 1700, "A3": 1620, "A4": 1500}
    forced = st.multiselect("Nations forced (skip)", teams)
    adjusts = []
    for tid, p in pools.items():
        e0 = elo_init[tid]
        e1, reason = PX.adjust_elo_from_gap(e0, p.delta_per_match, forced=tid in forced)
        adjusts.append({"team": tid, "elo_before": e0, "elo_after": e1, "delta": e1 - e0, "reason": reason})
    st.dataframe(pd.DataFrame(adjusts), hide_index=True, width="stretch")


def section_top_scorers():
    st.subheader("Top buteurs estimes par poule")
    st.caption(
        "Repartition xGF poule sur les joueurs offensifs via squad + minutes club "
        "(integration en aval). Ici demo : tableau attendu lambda*proba conversion."
    )
    st.info("Implementation downstream : connecte au snapshot squads_static.json + minutes club BSD.")


def section_best_thirds():
    st.subheader("Meilleurs 3emes — Poisson correle vs independent")
    st.caption(
        "On compare la distribution des points par equipe avec et sans facteur de forme "
        "partage sur les 3 matchs (form_sigma). La correlation augmente la variance des points "
        "et donc la queue droite des 3emes qualifies."
    )

    c1, c2 = st.columns(2)
    form_sigma = c1.slider("Form sigma (correlation factor)", 0.0, 0.5, 0.18, step=0.02)
    n_sims = c2.slider("N sims par equipe", 500, 10000, 3000, step=500)

    # Demo : 4 equipes "candidates 3eme" avec lambdas connus
    candidates = {
        "Senegal":   {"lambdas_for": [1.4, 1.1, 1.0], "lambdas_against": [1.0, 1.3, 1.5]},
        "Pologne":   {"lambdas_for": [1.2, 1.0, 0.9], "lambdas_against": [1.1, 1.2, 1.4]},
        "Australie": {"lambdas_for": [1.0, 0.9, 0.8], "lambdas_against": [1.2, 1.3, 1.5]},
        "Mexique":   {"lambdas_for": [1.5, 1.3, 1.2], "lambdas_against": [1.0, 1.1, 1.3]},
    }

    indep_dist = PX.best_thirds_distribution(candidates, n_sims=n_sims, form_sigma=0.0)
    corr_dist = PX.best_thirds_distribution(candidates, n_sims=n_sims, form_sigma=form_sigma)

    rows = []
    for tid in candidates:
        i = indep_dist[tid]
        c = corr_dist[tid]
        rows.append({
            "team": tid,
            "pts_mean_indep": i["pts_mean"], "pts_mean_corr": c["pts_mean"],
            "pts_p25_indep": i["pts_p25"], "pts_p25_corr": c["pts_p25"],
            "pts_p75_indep": i["pts_p75"], "pts_p75_corr": c["pts_p75"],
            "p4pts_indep": i["p_4pts_plus"], "p4pts_corr": c["p_4pts_plus"],
            "p_qualif_r32_indep": PX.prob_qualif_r32_as_third(i),
            "p_qualif_r32_corr": PX.prob_qualif_r32_as_third(c),
        })
    df = pd.DataFrame(rows)
    df["delta_p_qualif"] = df["p_qualif_r32_corr"] - df["p_qualif_r32_indep"]
    st.dataframe(
        df.style.format({
            "pts_mean_indep": "{:.2f}", "pts_mean_corr": "{:.2f}",
            "pts_p25_indep": "{:.1f}", "pts_p25_corr": "{:.1f}",
            "pts_p75_indep": "{:.1f}", "pts_p75_corr": "{:.1f}",
            "p4pts_indep": "{:.3f}", "p4pts_corr": "{:.3f}",
            "p_qualif_r32_indep": "{:.3f}", "p_qualif_r32_corr": "{:.3f}",
            "delta_p_qualif": "{:+.3f}",
        }),
        hide_index=True, width="stretch",
    )

    fig = go.Figure()
    for tid in candidates:
        fig.add_trace(go.Bar(
            name=tid,
            x=["indep", "corr"],
            y=[indep_dist[tid]["p_4pts_plus"], corr_dist[tid]["p_4pts_plus"]],
        ))
    fig.update_layout(title="P(>=4 pts) — indep vs corr", barmode="group", height=350)
    st.plotly_chart(fig, width="stretch")


def section_convergence():
    st.subheader("Convergence du recalibrage Elo")
    st.caption(
        "Iterations boucle B : a chaque pas, l'Elo nation s'ajuste, ce qui change "
        "les lambdas modele, qui change le gap... Affichage diagnostic uniquement "
        "(la prod gardera 3 iterations max)."
    )
    st.info("Demo non couplee — sera connectee une fois le pipeline phase 1 + phase 3 alignes.")


def render():
    st.title("Phase 3 — xG totaux poules CDM + meilleurs 3emes")
    st.markdown(
        """
Quatre objectifs :

1. **xGF par equipe sur la phase de poule** (model + market via phase 1 inversion)
2. **Recalibrage Elo nation** (boucle B) si ecart structurel > 0.5 buts/match
3. **Meilleurs 3emes ameliores** via Poisson correle inter-matchs
4. **Value bets O/U buts marques** par equipe sur phase poule

La page tourne en demo synthetique pour valider l'algorithme. L'integration
prod (avec snapshot `pinnacle_wc2026_odds.json` + squads CDM) sera faite en
phase de bascule.
"""
    )
    tabs = st.tabs([
        "1. Par poule", "2. Top buteurs poule", "3. Meilleurs 3emes", "4. Convergence"
    ])
    with tabs[0]:
        section_pool_breakdown()
    with tabs[1]:
        section_top_scorers()
    with tabs[2]:
        section_best_thirds()
    with tabs[3]:
        section_convergence()
