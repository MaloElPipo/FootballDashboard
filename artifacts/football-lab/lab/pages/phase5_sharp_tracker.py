"""Phase 5 — UI Sharp Money Tracker.

3 tabs :
  1. Snapshot manuel : on snapshot a la demande N events
  2. Vue historique : courbe d'evolution cotes par event/outcome
  3. Top mouvements : SHORTENING/DRIFTING sur 24h
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lab.calibration import track_movement as TM


PROD_DIR = Path("/home/runner/workspace/artifacts/football-dashboard")


def section_snapshot():
    st.subheader("Snapshot des cotes — forward log ouvert")
    st.caption(
        "Cron bi-quotidien (2x/j) sur l'ensemble du forward log ouvert. Manuel "
        "ici pour tests/etalonnage. Append-only dans `lab/data/movement_history.jsonl`."
    )

    events = TM.load_open_forward_log_events(PROD_DIR)
    if not events:
        st.warning("Pas d'event ouvert dans le forward log prod.")
        manual_id = st.number_input("Sinon, snapshot d'un event_id BSD manuel", 1, 99999999, value=0)
        if manual_id and st.button("Snapshot cet event"):
            recs = TM.snapshot_event_odds(int(manual_id))
            n = TM.append_snapshot(recs)
            st.success(f"{n} lignes ecrites")
        return

    st.caption(f"{len(events)} events ouverts detectes")
    c1, c2 = st.columns([1, 3])
    n_max = c1.slider("Snapshot max", 5, 50, 20, step=5)
    market = c2.selectbox("Marche", ["1x2", "over_under_25", "btts"])
    if st.button("Snapshot maintenant", type="primary"):
        progress = st.progress(0.0)
        total = 0
        for i, eid in enumerate(events[:n_max]):
            progress.progress((i + 1) / min(n_max, len(events)))
            recs = TM.snapshot_event_odds(eid, market=market)
            total += TM.append_snapshot(recs)
        progress.empty()
        st.success(f"{total} lignes ecrites pour {min(n_max, len(events))} events")


def section_evolution():
    st.subheader("Evolution cotes par event")
    eid = st.number_input("Event ID BSD", 1, 99999999, value=0)
    if not eid:
        st.info("Saisir un event_id pour visualiser l'historique.")
        return

    bookmaker = st.selectbox("Bookmaker", ["pinnacle", "bet365", "betclic", "unibet"])
    movs = TM.detect_movements(int(eid), bookmaker=bookmaker)
    if not movs["outcomes"]:
        st.warning("Pas d'historique pour ce event/bookmaker.")
        return

    df_summary = pd.DataFrame(
        [
            {"outcome": k, "first_odd": v["first_odd"], "last_odd": v["last_odd"],
             "delta_pct": v["delta_pct"], "signal": v["signal"], "n_snapshots": v["n_snapshots"]}
            for k, v in movs["outcomes"].items()
        ]
    )
    st.dataframe(
        df_summary.style.format({"first_odd": "{:.2f}", "last_odd": "{:.2f}", "delta_pct": "{:+.2f} %"}),
        hide_index=True, width="stretch",
    )

    fig = go.Figure()
    for outcome, v in movs["outcomes"].items():
        ts = [s for s, o in v["series"]]
        odds = [o for s, o in v["series"]]
        fig.add_trace(go.Scatter(x=ts, y=odds, mode="lines+markers", name=outcome))
    fig.update_layout(
        title=f"Evolution cotes — event {eid} ({bookmaker})",
        xaxis_title="Snapshot UTC",
        yaxis_title="Decimal odds",
        height=400,
    )
    st.plotly_chart(fig, width="stretch")


def section_top_movements():
    st.subheader("Top mouvements 24h")
    st.caption(
        "Scan toute l'historique, filtre les events avec >= 2 snapshots, classe par "
        "amplitude de mouvement signal SHORTENING/DRIFTING."
    )
    hist = TM.load_history()
    if not hist:
        st.warning("Pas encore d'historique. Lance des snapshots dans l'onglet 1.")
        return

    event_ids = sorted({r["event_id"] for r in hist})
    rows = []
    for eid in event_ids:
        movs = TM.detect_movements(eid, bookmaker="pinnacle")
        for outcome, v in movs["outcomes"].items():
            if v["signal"]:
                rows.append({
                    "event_id": eid,
                    "outcome": outcome,
                    "delta_pct": v["delta_pct"],
                    "signal": v["signal"],
                    "n_snapshots": v["n_snapshots"],
                })
    if not rows:
        st.info("Aucun signal SHORTENING/DRIFTING detecte (delta < 3 %).")
        return
    df = pd.DataFrame(rows).sort_values("delta_pct", key=lambda s: s.abs(), ascending=False)
    st.dataframe(
        df.style.format({"delta_pct": "{:+.2f} %"}),
        hide_index=True, width="stretch",
    )


def render():
    st.title("Phase 5 — Sharp money tracker")
    st.markdown(
        """
Snapshot bi-quotidien des cotes `compareOdds` BSD sur les events ouverts du
forward log. Detection SHORTENING (cote qui baisse = money in) / DRIFTING
(cote qui monte = money out) sur la fenetre observee.

**Setup uniquement ici.** L'analyse statistique de la valeur predictive du
signal sharp sera faite apres ~3 semaines d'historique (cron prevu en
operation).
"""
    )
    tab1, tab2, tab3 = st.tabs(["1. Snapshot", "2. Evolution event", "3. Top mouvements"])
    with tab1:
        section_snapshot()
    with tab2:
        section_evolution()
    with tab3:
        section_top_movements()
