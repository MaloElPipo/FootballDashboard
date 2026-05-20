"""Phase 3 — UI xG totaux poules CDM + meilleurs 3emes (donnees reelles)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lab.cdm import pool_xg as PX
from lab.cdm import wc26_data as WC


@st.cache_data(show_spinner=False)
def _load_pool_data():
    matches_by_group, elo = WC.build_pool_matches()
    coverage = WC.coverage_summary(matches_by_group)
    return matches_by_group, elo, coverage


@st.cache_data(show_spinner=False)
def _run_boucle_b(max_iter: int, threshold: float, sensitivity: float):
    steps, elo_final, matches_final = WC.run_boucle_b(
        max_iter=max_iter, threshold=threshold, sensitivity=sensitivity,
    )
    return steps, elo_final, matches_final


def _team_xg_rows(matches_by_group, groups_filter: list[str] | None = None) -> list[dict]:
    rows = []
    for g, ms in matches_by_group.items():
        if groups_filter and g not in groups_filter:
            continue
        for team in WC.WC26_GROUPS[g]:
            views = WC.team_match_views(team, ms)
            tpx = PX.compute_pool_xg(team, views)
            rows.append({
                "group": g, "team": team,
                "xgf_model": tpx.xgf_model, "xgf_market": tpx.xgf_market,
                "delta_xgf": tpx.delta_xgf,
                "xga_model": tpx.xga_model, "xga_market": tpx.xga_market,
                "delta_xga": tpx.delta_xga,
                "delta_per_match": tpx.delta_per_match,
                "forced": team in WC.FORCED_NATIONS,
            })
    return rows


def section_pool_breakdown():
    st.subheader("Par poule — xG totaux equipe (model vs market)")
    matches_by_group, elo, coverage = _load_pool_data()

    c1, c2, c3 = st.columns(3)
    c1.metric("Poules", len(WC.WC26_GROUPS))
    c2.metric(
        "Matchs avec cotes Pinnacle",
        f"{coverage['matches_with_odds']} / {coverage['total_pool_matches']}",
        delta=f"{coverage['coverage_pct']}%",
    )
    c3.metric("Nations Elo chargees", len(elo))

    st.caption(
        "Lambdas market : inversion 1X2 (snapshot Pinnacle limite a 1X2, seed "
        "p_over25 derive de l'Elo). Lambdas model : Elo prod (pin_calibrated + "
        "overrides). Pour les matchs sans cote dans le snapshot, market = model "
        "(gap = 0)."
    )

    with st.expander("Couverture par poule"):
        cov_df = pd.DataFrame([
            {"group": g, "matches_with_odds": n, "matches_total": 6}
            for g, n in coverage["per_group"].items()
        ])
        st.dataframe(cov_df, hide_index=True, width="stretch")

    groups = list(WC.WC26_GROUPS.keys())
    sel = st.multiselect("Filtrer les poules", groups, default=groups)
    rows = _team_xg_rows(matches_by_group, groups_filter=sel)
    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.format({
            "xgf_model": "{:.2f}", "xgf_market": "{:.2f}", "delta_xgf": "{:+.2f}",
            "xga_model": "{:.2f}", "xga_market": "{:.2f}", "delta_xga": "{:+.2f}",
            "delta_per_match": "{:.3f}",
        }),
        hide_index=True, width="stretch",
    )

    above = df[df["delta_per_match"] >= 0.5]
    if len(above):
        st.warning(
            f"{len(above)} equipe(s) au-dessus du seuil 0.5 buts/match -> "
            "candidates a l'ajustement Elo (boucle B)."
        )


def section_convergence():
    st.subheader("Boucle B — convergence du recalibrage Elo")
    st.caption(
        "A chaque iteration on ajuste l'Elo nation a partir du gap xGF/match. "
        "Les nations forced (hotes USA/MEX/CAN + politique QAT) ne sont jamais "
        "ajustees. Cible : convergence en ≤ 3 iterations sur le set CDM reel."
    )
    c1, c2, c3 = st.columns(3)
    max_iter = c1.slider("Max iterations", 1, 5, 3)
    threshold = c2.slider("Seuil gap (buts/match)", 0.2, 1.0, 0.5, step=0.05)
    sensitivity = c3.slider("Sensitivity Elo / 0.5 buts", 50.0, 200.0, 100.0, step=10.0)

    steps, elo_final, matches_final = _run_boucle_b(max_iter, threshold, sensitivity)

    df_steps = pd.DataFrame([
        {"iteration": s.iteration, "max_gap": s.max_gap,
         "n_adjusted": len(s.adjustments)}
        for s in steps
    ])
    st.dataframe(df_steps, hide_index=True, width="stretch")

    converged = len(steps) < max_iter or (steps and not steps[-1].adjustments)
    if converged:
        st.success(f"Convergence atteinte en {len(steps)} iteration(s).")
    else:
        st.warning(
            f"Pas de convergence apres {len(steps)} iterations "
            f"(max_gap final = {steps[-1].max_gap:.3f})."
        )

    if steps:
        last = steps[-1]
        if last.adjustments:
            adj_df = pd.DataFrame([
                {"team": t, "delta_elo": d, "elo_final": elo_final.get(t)}
                for t, d in sorted(
                    last.adjustments.items(), key=lambda kv: -abs(kv[1])
                )
            ])
            st.dataframe(
                adj_df.style.format({"delta_elo": "{:+.0f}", "elo_final": "{:.0f}"}),
                hide_index=True, width="stretch",
            )

    with st.expander("xG poules apres convergence"):
        rows = _team_xg_rows(matches_final)
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.format({
                "xgf_model": "{:.2f}", "xgf_market": "{:.2f}", "delta_xgf": "{:+.2f}",
                "delta_per_match": "{:.3f}",
            }),
            hide_index=True, width="stretch",
        )


def section_best_thirds():
    st.subheader("Meilleurs 3emes — Poisson correle vs independent (12 candidats reels)")
    st.caption(
        "On prend pour chaque poule le 3eme par Elo, soit 12 candidats. On compare "
        "leur distribution de points/buts avec et sans facteur de forme partage "
        "sur les 3 matchs. La correlation augmente la queue droite des qualifies R32."
    )
    matches_by_group, elo, _ = _load_pool_data()

    c1, c2 = st.columns(2)
    form_sigma = c1.slider("Form sigma (correlation)", 0.0, 0.5, 0.18, step=0.02)
    n_sims = c2.slider("N sims par equipe", 500, 10000, 3000, step=500)

    cand = WC.third_place_candidates(elo)
    pools = WC.team_pools_for_simulation(cand, matches_by_group)
    indep = PX.best_thirds_distribution(pools, n_sims=n_sims, form_sigma=0.0)
    corr = PX.best_thirds_distribution(pools, n_sims=n_sims, form_sigma=form_sigma)

    rows = []
    for tid in cand:
        i = indep[tid]; c = corr[tid]
        p_i = PX.prob_qualif_r32_as_third(i)
        p_c = PX.prob_qualif_r32_as_third(c)
        group = next(g for g, ts in WC.WC26_GROUPS.items() if tid in ts)
        rows.append({
            "group": group, "team": tid,
            "pts_mean_indep": i["pts_mean"], "pts_mean_corr": c["pts_mean"],
            "p4pts_indep": i["p_4pts_plus"], "p4pts_corr": c["p_4pts_plus"],
            "p_qualif_r32_indep": p_i, "p_qualif_r32_corr": p_c,
            "delta_p_qualif": p_c - p_i,
        })
    df = pd.DataFrame(rows).sort_values("p_qualif_r32_corr", ascending=False)
    st.dataframe(
        df.style.format({
            "pts_mean_indep": "{:.2f}", "pts_mean_corr": "{:.2f}",
            "p4pts_indep": "{:.3f}", "p4pts_corr": "{:.3f}",
            "p_qualif_r32_indep": "{:.3f}", "p_qualif_r32_corr": "{:.3f}",
            "delta_p_qualif": "{:+.3f}",
        }),
        hide_index=True, width="stretch",
    )

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="indep", x=df["team"], y=df["p_qualif_r32_indep"],
    ))
    fig.add_trace(go.Bar(
        name="correle", x=df["team"], y=df["p_qualif_r32_corr"],
    ))
    fig.update_layout(
        title="P(qualif R32 via 3eme) — independent vs correle (12 candidats CDM)",
        barmode="group", height=380, xaxis_title="3eme candidat par poule",
    )
    st.plotly_chart(fig, width="stretch")


def section_top_scorers():
    st.subheader("Top buteurs estimes par poule")
    st.info(
        "Repartition xGF poule sur les joueurs offensifs : necessite "
        "`squads_static.json` (BSD squad CDM + minutes club). Le snapshot "
        "baseline 2026-05-20 n'inclut pas encore ce fichier — section en "
        "attente du loader squads."
    )


def render():
    st.title("Phase 3 — xG totaux poules CDM + meilleurs 3emes")
    st.markdown(
        """
Quatre objectifs (branche sur snapshot `initial_baseline_2026-05-20`) :

1. **xGF par equipe sur la phase de poule** — model (Elo) vs market (cotes Pinnacle inversees)
2. **Recalibrage Elo nation** (boucle B) si ecart structurel > 0.5 buts/match
3. **Meilleurs 3emes ameliores** via Poisson correle inter-matchs (12 candidats reels)
4. **Top buteurs poule** (en attente du loader squads)
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
