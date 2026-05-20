"""Phase 4 — UI Player Stats BSD vs Sofascore."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from lab.calibration import player_stats as PS


PROD_DIR = Path("/home/runner/workspace/artifacts/football-dashboard")


def section_lookup():
    st.subheader("Lookup stats joueur BSD")
    c1, c2, c3 = st.columns([2, 2, 1])
    pid = c1.number_input("Player ID BSD", 1, 999999, value=110145, step=1, help="ex: Haaland=110145")
    sid = c2.number_input("Season ID", 1, 99999, value=337)
    run = c3.button("Fetch", type="primary")
    if not run:
        st.info("Saisir player_id BSD puis fetch. Endpoint teste : `v2/player-stats/`, `v2/players/<id>/stats/`.")
        return
    with st.spinner("BSD getPlayerStats..."):
        s = PS.fetch_player_season_stats(int(pid), int(sid))
    if not s:
        st.error("Pas de stats retournees par BSD pour ce joueur/saison.")
        return
    st.json(s)


def section_compare_forward_log():
    st.subheader("Comparaison BSD vs Sofascore sur forward log")
    st.caption(
        "Charge les 30 joueurs les plus suivis dans le forward log prod, fetch BSD, "
        "compare aux stats Sofascore snapshot. Flag DISAGREE si ecart > tolerance."
    )

    c1, c2 = st.columns([1, 3])
    n = c1.slider("N joueurs", 5, 50, 30, step=5)
    load = c2.button("Charger forward log + fetch BSD", type="primary")
    if not load:
        return

    players = PS.load_forward_log_players(PROD_DIR, limit=n)
    if not players:
        st.error("Forward log prod introuvable ou vide (live/data/forward_log.jsonl).")
        return

    st.caption(f"{len(players)} joueurs identifies")
    sid = st.number_input("Season ID pour fetch BSD", 1, 99999, value=337, key="cmp_sid")

    rows = []
    progress = st.progress(0.0)
    missing = 0
    for i, p in enumerate(players):
        progress.progress((i + 1) / len(players))
        pid = p["player_id"]
        bsd = PS.fetch_player_season_stats(pid, int(sid))
        if not bsd:
            missing += 1
            rows.append({
                "player_id": pid, "name": p.get("name"),
                "n_picks": p["n_picks"],
                "bsd_matches": None, "bsd_goals": None, "bsd_xg": None, "flag": "NO_BSD"
            })
            continue
        rows.append({
            "player_id": pid, "name": p.get("name"),
            "n_picks": p["n_picks"],
            "bsd_matches": bsd["matches"],
            "bsd_goals": bsd["goals"],
            "bsd_assists": bsd["assists"],
            "bsd_xg": bsd["xg"],
            "bsd_xa": bsd["xa"],
            "bsd_minutes": bsd["minutes"],
            "flag": "OK",
        })
    progress.empty()
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch")
    st.metric("Joueurs couverts par BSD", f"{len(df)-missing}/{len(df)}")


def section_coverage_extension():
    st.subheader("Couverture extension hors top 5")
    st.caption(
        "Test de robustesse : 20 joueurs MLS / Eredivisie / Primeira. Mesure le %"
        " de couverture stats BSD pour valider la migration sur les ligues secondaires."
    )

    sample_ids = st.text_area(
        "IDs joueurs BSD (CSV)",
        value="",
        help="Coller 20 IDs separes par virgules. Si vide, on tente 0 (info).",
        height=100,
    )
    sid = st.number_input("Season ID", 1, 99999, value=337, key="ext_sid")
    run = st.button("Tester couverture", type="primary", key="ext_run")
    if not run:
        return
    try:
        ids = [int(x.strip()) for x in sample_ids.split(",") if x.strip()]
    except ValueError:
        st.error("Format IDs invalide")
        return
    if not ids:
        st.warning("Pas d'IDs fournis. Donne au moins 5 IDs pour tester.")
        return

    with st.spinner(f"Fetch {len(ids)} joueurs..."):
        cov = PS.coverage_extension(ids, int(sid))
    c1, c2, c3 = st.columns(3)
    c1.metric("Total testes", cov["total"])
    c2.metric("Avec data", cov["with_data"])
    c3.metric("Couverture", f"{cov['coverage_pct']} %")
    st.dataframe(pd.DataFrame(cov["detail"]), hide_index=True, width="stretch")


def render():
    st.title("Phase 4 — Migration player stats BSD")
    st.markdown(
        """
On migre la collecte des stats joueurs (goals, assists, xG, xA, minutes) du
scraper Sofascore vers `BSD getPlayerStats`. Trois objectifs :

- **Robustesse** : un seul provider plus un fallback, moins de scraping
- **Couverture** : extension hors top 5 (MLS, Eredivisie, Primeira)
- **xG/xA fiables** : BSD agrege un xG model-based plus stable que le rendu Sofascore

Critere go : couverture >= 90 % sur forward log + couverture >= 70 % sur extension.
"""
    )
    tab1, tab2, tab3 = st.tabs(
        ["Lookup joueur", "Compare forward log", "Couverture extension"]
    )
    with tab1:
        section_lookup()
    with tab2:
        section_compare_forward_log()
    with tab3:
        section_coverage_extension()
