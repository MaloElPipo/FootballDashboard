"""Phase 4 — UI Player Stats BSD vs Sofascore."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from lab.calibration import player_stats as PS
from lab.calibration import player_id_mapping as PIM


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
    not_mapped = 0
    for i, p in enumerate(players):
        progress.progress((i + 1) / len(players))
        sofa_id = p["player_id"]
        mapping = PIM.resolve_player(int(sofa_id), str(p.get("name") or ""), team_id=p.get("team_id"))
        bsd_pid = mapping.get("bsd_player_id")
        base = {
            "sofa_id": sofa_id,
            "bsd_id": bsd_pid,
            "name": p.get("name"),
            "n_picks": p["n_picks"],
            "map_status": mapping.get("status"),
        }
        if not bsd_pid:
            not_mapped += 1
            rows.append({**base, "bsd_matches": None, "bsd_goals": None, "bsd_xg": None, "flag": "NO_BSD_ID"})
            continue
        bsd = PS.fetch_player_season_stats(int(bsd_pid), int(sid))
        if not bsd:
            missing += 1
            rows.append({**base, "bsd_matches": None, "bsd_goals": None, "bsd_xg": None, "flag": "NO_BSD_STATS"})
            continue
        rows.append({
            **base,
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
    c1, c2 = st.columns(2)
    c1.metric("Mapping Sofa->BSD", f"{len(df)-not_mapped}/{len(df)}")
    c2.metric("Stats BSD recuperees", f"{len(df)-not_mapped-missing}/{len(df)-not_mapped}" if (len(df)-not_mapped) > 0 else "0/0")


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


def section_id_mapping():
    st.subheader("Mapping Sofascore -> BSD player_id")
    st.caption(
        "Le forward log stocke des IDs Sofascore. Avant de pouvoir interroger "
        "`BSD getPlayerStats`, il faut resoudre l'ID BSD via `searchPlayers`. "
        "Le mapping est cache sur disque (`lab/data/player_id_mapping.json`)."
    )
    c1, c2 = st.columns([1, 3])
    n = c1.slider("N joueurs (top forward log)", 5, 50, 30, step=5, key="map_n")
    force = c2.checkbox("Forcer le refresh (ignore le cache)", value=False, key="map_force")
    run = st.button("Resoudre les IDs", type="primary", key="map_run")
    if not run:
        cache = PIM.load_mapping()
        st.caption(f"Cache courant : {len(cache)} entrees")
        return

    players = PS.load_forward_log_players(PROD_DIR, limit=n)
    if not players:
        st.error("Forward log prod introuvable ou vide (live/data/forward_log.jsonl).")
        return

    records: list[dict] = []
    progress = st.progress(0.0)
    for i, p in enumerate(players):
        progress.progress((i + 1) / len(players))
        records.append(
            PIM.resolve_player(
                int(p["player_id"]),
                str(p.get("name") or ""),
                team_id=p.get("team_id"),
                force_refresh=force,
            )
        )
    progress.empty()

    summary = PIM.coverage_summary(records)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Joueurs testes", summary["total"])
    c2.metric("Resolus", summary["resolved"])
    c3.metric("Couverture", f"{summary['coverage_pct']} %")
    c4.metric("Erreurs", summary["errors"])

    df = pd.DataFrame([
        {
            "sofa_id": r.get("sofascore_id"),
            "name": r.get("name"),
            "bsd_id": r.get("bsd_player_id"),
            "matched_name": r.get("matched_name"),
            "status": r.get("status"),
            "source": r.get("source"),
        }
        for r in records
    ])
    st.dataframe(df, hide_index=True, width="stretch")


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
    tab1, tab2, tab3, tab4 = st.tabs(
        ["Lookup joueur", "Mapping IDs", "Compare forward log", "Couverture extension"]
    )
    with tab1:
        section_lookup()
    with tab2:
        section_id_mapping()
    with tab3:
        section_compare_forward_log()
    with tab4:
        section_coverage_extension()
