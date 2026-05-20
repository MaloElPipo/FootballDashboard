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
        "Charge les top N joueurs du forward log prod, fetch BSD, et compare au "
        "snapshot Sofascore (statshub_performance prod). Diff par champ "
        "(goals/assists/xG/xA/minutes) avec flag OK / DISAGREE / MISSING."
    )

    c1, c2 = st.columns([1, 3])
    n = c1.slider("N joueurs", 5, 50, 30, step=5)
    load = c2.button("Charger forward log + fetch BSD + Sofa snapshot", type="primary")
    if not load:
        return

    players = PS.load_forward_log_players(PROD_DIR, limit=n)
    if not players:
        st.error("Forward log prod introuvable ou vide (live/data/forward_log.jsonl).")
        return

    st.caption(f"{len(players)} joueurs identifies")
    sid = st.number_input("Season ID pour fetch BSD", 1, 99999, value=337, key="cmp_sid")
    tol_goals = st.number_input("Tol goals", 0, 10, 1, key="cmp_tg")
    tol_assists = st.number_input("Tol assists", 0, 10, 1, key="cmp_ta")
    tol_xg = st.number_input("Tol xG", 0.0, 5.0, 0.5, step=0.1, key="cmp_txg")
    tol_xa = st.number_input("Tol xA", 0.0, 5.0, 0.3, step=0.1, key="cmp_txa")
    tol_min = st.number_input("Tol minutes", 0, 900, 90, step=10, key="cmp_tm")
    tolerance = {
        "goals": tol_goals, "assists": tol_assists,
        "xg": tol_xg, "xa": tol_xa, "minutes": tol_min,
    }

    rows = []
    progress = st.progress(0.0)
    missing_bsd = 0
    not_mapped = 0
    no_sofa = 0
    n_compared = 0
    n_concordant = 0
    for i, p in enumerate(players):
        progress.progress((i + 1) / len(players))
        sofa_id = p["player_id"]
        # Task #10 : si la prod a deja resolu bsd_player_id au logging, on le
        # lit directement depuis le forward log. Sinon fallback sur le cache
        # labo `player_id_mapping` (resolution via `searchPlayers`).
        bsd_from_log = p.get("bsd_player_id")
        if bsd_from_log is not None:
            bsd_pid = int(bsd_from_log)
            map_status = "from_log"
        else:
            mapping = PIM.resolve_player(int(sofa_id), str(p.get("name") or ""), team_id=p.get("team_id"))
            bsd_pid = mapping.get("bsd_player_id")
            map_status = mapping.get("status")
        base = {
            "sofa_id": sofa_id,
            "bsd_id": bsd_pid,
            "name": p.get("name"),
            "n_picks": p["n_picks"],
            "map_status": map_status,
        }
        if not bsd_pid:
            not_mapped += 1
            rows.append({**base, "flag": "NO_BSD_ID"})
            continue
        bsd = PS.fetch_player_season_stats(int(bsd_pid), int(sid))
        if not bsd:
            missing_bsd += 1
            rows.append({**base, "flag": "NO_BSD_STATS"})
            continue
        sofa = PS.load_sofascore_snapshot(PROD_DIR, int(bsd_pid))
        if not sofa:
            no_sofa += 1
            rows.append({
                **base,
                "bsd_matches": bsd["matches"], "bsd_goals": bsd["goals"],
                "bsd_assists": bsd["assists"], "bsd_xg": bsd["xg"],
                "bsd_xa": bsd["xa"], "bsd_minutes": bsd["minutes"],
                "flag": "NO_SOFA_SNAP",
            })
            continue

        diff = PS.compare_with_sofascore(bsd, sofa, tolerance=tolerance)
        n_compared += 1
        flags = [d["flag"] for d in diff.values()]
        ok = all(f == "OK" for f in flags)
        if ok:
            n_concordant += 1
        rows.append({
            **base,
            "bsd_matches": bsd["matches"], "sofa_matches": sofa["matches"],
            "bsd_goals": bsd["goals"], "sofa_goals": sofa["goals"],
            "d_goals": diff["goals"]["delta"], "f_goals": diff["goals"]["flag"],
            "bsd_assists": bsd["assists"], "sofa_assists": sofa["assists"],
            "d_assists": diff["assists"]["delta"], "f_assists": diff["assists"]["flag"],
            "bsd_xg": bsd["xg"], "sofa_xg": sofa["xg"],
            "d_xg": diff["xg"]["delta"], "f_xg": diff["xg"]["flag"],
            "bsd_xa": bsd["xa"], "sofa_xa": sofa["xa"],
            "d_xa": diff["xa"]["delta"], "f_xa": diff["xa"]["flag"],
            "bsd_minutes": bsd["minutes"], "sofa_minutes": sofa["minutes"],
            "d_minutes": diff["minutes"]["delta"], "f_minutes": diff["minutes"]["flag"],
            "flag": "OK" if ok else "DISAGREE",
        })
    progress.empty()
    df = pd.DataFrame(rows)
    st.dataframe(df, hide_index=True, width="stretch")

    total = len(df)
    mapped = total - not_mapped
    with_bsd = mapped - missing_bsd
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Mapping Sofa->BSD", f"{mapped}/{total}")
    c2.metric("Stats BSD recup.", f"{with_bsd}/{mapped}" if mapped > 0 else "0/0")
    c3.metric("Snapshot Sofa dispo", f"{n_compared}/{with_bsd}" if with_bsd > 0 else "0/0")
    pct = round(100 * n_concordant / n_compared, 1) if n_compared > 0 else 0.0
    c4.metric("% concordants", f"{pct} %", help="Tous les champs (g/a/xG/xA/min) dans la tolerance.")

    threshold = 80.0
    if n_compared == 0:
        st.warning(
            "Aucune comparaison possible : pas de snapshot Sofascore "
            "(statshub_performance) pour les joueurs mappes. NO-GO migration."
        )
    elif pct >= threshold:
        st.success(f"GO migration : {pct}% des joueurs comparables sont concordants (>= {threshold}%).")
    else:
        st.error(f"NO-GO migration : {pct}% concordants (< {threshold}%). Investiguer les DISAGREE.")

    if n_compared > 0:
        st.caption(
            "Comparaison agregee sur l'ensemble des matchs presents dans le snapshot "
            "Sofascore (pas filtre par season_id). Les ecarts xG/xA peuvent refleter "
            "un modele xG different entre BSD et Sofascore."
        )


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
