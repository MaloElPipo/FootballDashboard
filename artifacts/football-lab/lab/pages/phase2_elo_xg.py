"""Phase 2 — UI Elo via xG getStandings.

Tabs :
  1. Fetch standings + regression att/def
  2. Tableau Elo_xg vs Elo_prod vs Elo_marche
  3. Backtest 1X2 sur une saison
  4. Agregation CDM (info, non bloquant)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from lab import snapshots
from lab.calibration import elo_from_xg as EX
from lab.calibration import match_fetcher as MF
from lab.calibration import invert_market as IM


REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


def _load_prod_elo() -> dict[str, float]:
    """Charge le dernier snapshot prod si dispo (mapping team_name -> elo)."""
    snaps = snapshots.list_snapshots()
    if not snaps:
        return {}
    last = snaps[0]
    try:
        data = snapshots.load_snapshot(last["tag"], "pin_calibrated_elo.json")
        if isinstance(data, dict):
            return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except Exception:
        return {}
    return {}


def section_standings():
    st.subheader("Fetch standings + regression att/def")
    st.caption(
        "Pour chaque league/saison, on fetch les standings BSD (xGF/xGA par equipe), "
        "puis on regresse att/def par equipe avec decay exponentiel inter-saisons (0.7^k)."
    )

    col1, col2, col3 = st.columns([2, 2, 1])
    league_ids = col1.multiselect(
        "Leagues BSD",
        options=list(EX.TOP7_LEAGUES.keys()),
        default=[1, 3, 4, 5, 6],
        format_func=lambda i: f"{i} — {EX.TOP7_LEAGUES.get(i, '?')}",
    )
    seasons_raw = col2.text_input(
        "Saisons BSD (CSV)", value="337,294,358,228,317",
        help="Mettre les IDs current+passees. Ex pour PL 25/26 : 337"
    )
    fetch = col3.button("Lancer fetch", type="primary")

    if not fetch:
        st.info("Configure leagues + saisons puis clique fetch.")
        return

    try:
        season_ids = [int(s.strip()) for s in seasons_raw.split(",") if s.strip()]
    except ValueError:
        st.error("Saisons IDs doivent etre des entiers")
        return

    progress = st.progress(0.0)
    all_rows = []
    n_total = len(league_ids) * len(season_ids)
    k = 0
    failures = []
    for lid in league_ids:
        for sid in season_ids:
            k += 1
            progress.progress(k / max(n_total, 1))
            try:
                rows = EX.fetch_standings_xg(lid, sid)
                if not rows:
                    failures.append(f"L{lid}/S{sid}: 0 rows")
                else:
                    all_rows.extend(rows)
            except Exception as e:
                failures.append(f"L{lid}/S{sid}: {e}")
    progress.empty()

    if failures:
        with st.expander(f"{len(failures)} fetch echoues"):
            for f in failures:
                st.text(f)

    if not all_rows:
        st.error("Aucune donnee standings recuperee.")
        return

    st.success(f"{len(all_rows)} (team, season) rows collectees")
    df_raw = pd.DataFrame(
        [
            {
                "league_id": r.league_id,
                "season_id": r.season_id,
                "team_id": r.team_id,
                "team": r.team_name,
                "mp": r.matches_played,
                "xgf_per_match": r.xgf_per_match,
                "xga_per_match": r.xga_per_match,
                "gf": r.gf,
                "ga": r.ga,
            }
            for r in all_rows
        ]
    )
    st.dataframe(df_raw, hide_index=True, width="stretch")

    strengths = EX.regress_att_def(all_rows)
    st.session_state["phase2_strengths"] = strengths
    st.session_state["phase2_raw"] = df_raw

    df_str = pd.DataFrame(
        [
            {
                "team_id": tid,
                "team": d["team_name"],
                "league_id": d["league_id"],
                "att": d["att"],
                "def": d["def"],
                "strength": d["strength"],
                "n_seasons": len(d["seasons_used"]),
            }
            for tid, d in strengths.items()
        ]
    ).sort_values("strength", ascending=False)
    st.subheader(f"Strengths agreges ({len(strengths)} equipes)")
    st.dataframe(
        df_str.style.format(
            {"att": "{:.3f}", "def": "{:.3f}", "strength": "{:+.3f}"}
        ),
        hide_index=True,
        width="stretch",
    )


def section_compare_elo():
    st.subheader("Elo_xg vs Elo_prod vs Elo_marche")
    strengths = st.session_state.get("phase2_strengths")
    if not strengths:
        st.warning("Lance d'abord l'onglet 'Standings' pour calculer les strengths.")
        return

    prod_elo_by_name = _load_prod_elo()
    if prod_elo_by_name:
        st.caption(f"Snapshot prod charge : {len(prod_elo_by_name)} equipes")
    else:
        st.caption("Pas de snapshot prod dispo — calibration en mu/sigma nominaux.")

    # mapping name->id depuis strengths pour ancrer
    elo_anchor = {}
    for tid, d in strengths.items():
        match = prod_elo_by_name.get(d["team_name"])
        if match:
            elo_anchor[tid] = float(match)

    elo_xg = EX.calibrate_to_elo(strengths, elo_anchor=elo_anchor or None)

    rows = []
    for tid, d in strengths.items():
        rows.append(
            {
                "team_id": tid,
                "team": d["team_name"],
                "league_id": d["league_id"],
                "att": d["att"],
                "def": d["def"],
                "strength": d["strength"],
                "elo_xg": elo_xg[tid],
                "elo_prod": prod_elo_by_name.get(d["team_name"]),
            }
        )
    df = pd.DataFrame(rows)
    df["delta_xg_prod"] = df["elo_xg"] - df["elo_prod"]

    st.dataframe(
        df.style.format(
            {
                "att": "{:.3f}", "def": "{:.3f}", "strength": "{:+.3f}",
                "elo_xg": "{:.0f}", "elo_prod": "{:.0f}", "delta_xg_prod": "{:+.0f}",
            }
        ),
        hide_index=True,
        width="stretch",
    )

    matched = df.dropna(subset=["elo_prod"])
    if len(matched) >= 3:
        st.metric("|delta| Elo_xg vs Elo_prod (median)", f"{matched['delta_xg_prod'].abs().median():.0f}")
        c1, c2 = st.columns(2)
        c1.metric("Pearson corr", f"{matched[['elo_xg','elo_prod']].corr().iloc[0,1]:.3f}")
        c2.metric("RMSE", f"{np.sqrt(((matched['elo_xg']-matched['elo_prod'])**2).mean()):.1f}")

    # Slider blend
    st.divider()
    st.subheader("Blend slider (preview prod)")
    pct = st.slider("% Elo_xg (vs % Elo_prod)", 0, 100, 30, step=10)
    if not matched.empty:
        blended = matched["elo_prod"] * (1 - pct / 100) + matched["elo_xg"] * (pct / 100)
        df_blend = matched.copy()
        df_blend[f"elo_blend_{pct}"] = blended
        df_blend["delta_vs_prod"] = blended - df_blend["elo_prod"]
        st.dataframe(
            df_blend[["team", "elo_prod", "elo_xg", f"elo_blend_{pct}", "delta_vs_prod"]]
            .style.format(
                {"elo_prod": "{:.0f}", "elo_xg": "{:.0f}", f"elo_blend_{pct}": "{:.0f}", "delta_vs_prod": "{:+.0f}"}
            ),
            hide_index=True, width="stretch",
        )


def section_backtest_1x2():
    st.subheader("Backtest 1X2 — log-loss / Brier / ROI Pinnacle close")
    strengths = st.session_state.get("phase2_strengths")
    if not strengths:
        st.warning("Lance d'abord 'Standings'.")
        return

    c1, c2, c3 = st.columns([2, 2, 1])
    league = c1.selectbox("League BSD", list(EX.TOP7_LEAGUES.keys()), format_func=lambda i: EX.TOP7_LEAGUES[i])
    season = c2.number_input("Saison ID (pour matchs finis)", 1, 99999, value=337)
    n_max = c3.slider("N matchs", 5, 100, 20, step=5)
    run = st.button("Lancer backtest", key="bt2_run", type="primary")
    if not run:
        return

    elo_xg = EX.calibrate_to_elo(strengths, elo_anchor=None)
    prod_elo_by_name = _load_prod_elo()

    with st.spinner("Fetch matchs..."):
        matches = MF.list_finished_matches(league, int(season), limit=n_max)
    if not matches:
        st.error("Aucun match recupere.")
        return

    rows = []
    progress = st.progress(0.0)
    for i, m in enumerate(matches[:n_max]):
        progress.progress((i + 1) / min(n_max, len(matches)))
        ht = m.get("home_team") or {}
        at = m.get("away_team") or {}
        h_id = ht.get("id") if isinstance(ht, dict) else None
        a_id = at.get("id") if isinstance(at, dict) else None
        h_name = ht.get("name") if isinstance(ht, dict) else None
        a_name = at.get("name") if isinstance(at, dict) else None
        result = MF.extract_result(m)
        if not (h_id and a_id and result):
            continue
        # Elo_xg
        eh_x = elo_xg.get(h_id)
        ea_x = elo_xg.get(a_id)
        if eh_x is None or ea_x is None:
            continue
        # Elo_prod via nom
        eh_p = prod_elo_by_name.get(h_name)
        ea_p = prod_elo_by_name.get(a_name)
        p_x = EX.elo_to_probs_1x2(eh_x, ea_x)
        ll_x = EX.log_loss_1x2(*p_x, result)
        br_x = EX.brier_1x2(*p_x, result)
        row = {
            "match_id": m.get("id"),
            "home": h_name, "away": a_name, "result": result,
            "elo_xg_h": eh_x, "elo_xg_a": ea_x,
            "p_h_xg": p_x[0], "ll_xg": ll_x, "brier_xg": br_x,
        }
        if eh_p and ea_p:
            p_p = EX.elo_to_probs_1x2(eh_p, ea_p)
            row.update({
                "elo_prod_h": eh_p, "elo_prod_a": ea_p,
                "p_h_prod": p_p[0],
                "ll_prod": EX.log_loss_1x2(*p_p, result),
                "brier_prod": EX.brier_1x2(*p_p, result),
            })

        # ROI Pinnacle close si dispo
        odds = MF.fetch_compare_odds(int(m.get("id")))
        if odds:
            mk = MF.extract_market_probs(odds)
            if mk and "raw_odds" in mk:
                ro = mk["raw_odds"]
                row["roi_xg"] = EX.roi_pinnacle_close(p_x, (ro["1"], ro["X"], ro["2"]), result)
                if "p_h_prod" in row:
                    p_p = EX.elo_to_probs_1x2(eh_p, ea_p)
                    row["roi_prod"] = EX.roi_pinnacle_close(p_p, (ro["1"], ro["X"], ro["2"]), result)
        rows.append(row)
    progress.empty()

    if not rows:
        st.error("Aucun match exploitable (no team_id match avec strengths).")
        return
    df = pd.DataFrame(rows)
    st.success(f"{len(df)} matchs traites")

    c1, c2, c3 = st.columns(3)
    c1.metric("Log-loss moy (xg)", f"{df['ll_xg'].mean():.4f}")
    if "ll_prod" in df:
        d = df.dropna(subset=["ll_prod"])
        c2.metric("Log-loss moy (prod)", f"{d['ll_prod'].mean():.4f}",
                  delta=f"{d['ll_xg'].mean()-d['ll_prod'].mean():+.4f}", delta_color="inverse")
    if "roi_xg" in df:
        c3.metric("ROI cumule (xg)", f"{df['roi_xg'].fillna(0).sum():+.2f}u")

    st.dataframe(df, hide_index=True, width="stretch")
    out = REPORTS_DIR / f"backtest_elo_xg_L{league}_S{season}.csv"
    df.to_csv(out, index=False)
    st.caption(f"Resultats sauves : `{out.relative_to(out.parents[2])}`")


def section_nation_cdm():
    st.subheader("Agregation joueurs -> nations CDM (info)")
    st.info(
        "Outliers Elo nation = info seulement (overrides manuels CDM geres par user). "
        "Cette section recoit le mapping squad CDM + minutes club, et affiche le "
        "Elo nation agrege. Saisie minimale ici pour eviter de dependre des squads BSD."
    )
    st.caption(
        "Pour la prod : appeler `aggregate_nation_elo(squad, club_strengths, minutes)` "
        "en passant le squad CDM 26 joueurs (mapping prod) et les minutes club extraites de "
        "BSD getPlayerStats sur la saison ecoulee."
    )


def render():
    st.title("Phase 2 — Recalibrage Elo via xG getStandings")
    st.markdown(
        """
On reconstruit un Elo equipe a partir de l'historique xGF/xGA des standings BSD
plutot que des resultats 1X2. Ca capte mieux le **niveau structurel** (xG est
moins bruite que les buts) et evite la deformation par les sequences de
chance / malchance.
"""
    )
    tab1, tab2, tab3, tab4 = st.tabs(
        ["1. Standings + regression", "2. Compare Elo", "3. Backtest 1X2", "4. CDM nations"]
    )
    with tab1:
        section_standings()
    with tab2:
        section_compare_elo()
    with tab3:
        section_backtest_1x2()
    with tab4:
        section_nation_cdm()
