"""Page Streamlit Phase 1 : Triple inversion BTTS via Dixon-Coles.

Trois modes d'usage :
  1. **Saisie manuelle**   : on entre 5 probas marche, on visualise l'inversion
  2. **Match BSD**         : on choisit league/saison/match, on fetch les cotes
  3. **Backtest 1X2**      : log-loss agreges sur N matchs PL recents

Toujours afficher cote a cote : methode double (prod) vs methode triple (Dixon-Coles).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from lab.calibration import invert_market as IM
from lab.calibration import match_fetcher as MF


# ─────────────────────────────────────────────────────────────────────────────
# Helpers UI
# ─────────────────────────────────────────────────────────────────────────────


def _result_card(label: str, res: IM.InversionResult, market: dict):
    """Carte recap d'une inversion + comparaison avec le marche."""
    derived = IM.derived_probs(res.lambda_h, res.lambda_a, res.rho)
    st.markdown(f"### {label}")
    if not res.ok:
        st.error(f"Optimiseur non converge : {res.method}")
        return derived

    c1, c2, c3 = st.columns(3)
    c1.metric("lambda_home", f"{res.lambda_h:.3f}")
    c2.metric("lambda_away", f"{res.lambda_a:.3f}")
    c3.metric("rho", f"{res.rho:.3f}")
    st.caption(
        f"Cout optimiseur : {res.cost:.5f} | Total buts implicite : "
        f"{res.lambda_h + res.lambda_a:.2f}"
    )

    df = pd.DataFrame(
        [
            {
                "marche": "1 (Home)",
                "marche_proba": market["p_h"],
                "model_proba": derived["p_h"],
            },
            {
                "marche": "X (Nul)",
                "marche_proba": market["p_d"],
                "model_proba": derived["p_d"],
            },
            {
                "marche": "2 (Away)",
                "marche_proba": market["p_a"],
                "model_proba": derived["p_a"],
            },
            {
                "marche": "Over 2.5",
                "marche_proba": market["p_over25"],
                "model_proba": derived["p_over"],
            },
            {
                "marche": "BTTS Yes",
                "marche_proba": market["p_btts"],
                "model_proba": derived["p_btts"],
            },
        ]
    )
    df["ecart"] = df["model_proba"] - df["marche_proba"]
    df["ecart_pct"] = df["ecart"] * 100
    st.dataframe(
        df.style.format(
            {
                "marche_proba": "{:.3f}",
                "model_proba": "{:.3f}",
                "ecart": "{:+.4f}",
                "ecart_pct": "{:+.2f} pp",
            }
        ),
        hide_index=True,
        width="stretch",
    )
    return derived


def _scoreline_heatmap(label: str, lh: float, la: float, rho: float):
    M = IM.joint_matrix(lh, la, rho, max_goals=6)
    fig = go.Figure(
        data=go.Heatmap(
            z=M * 100,
            x=[str(i) for i in range(7)],
            y=[str(i) for i in range(7)],
            colorscale="Blues",
            text=[[f"{v*100:.1f}" for v in row] for row in M],
            texttemplate="%{text}",
            hovertemplate="Home %{y} - Away %{x} : %{z:.2f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"{label} — distribution des scores (%)",
        xaxis_title="Buts Away",
        yaxis_title="Buts Home",
        yaxis_autorange="reversed",
        height=350,
        margin=dict(l=40, r=20, t=50, b=40),
    )
    st.plotly_chart(fig, width="stretch")


# ─────────────────────────────────────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────────────────────────────────────


def section_manual():
    st.subheader("Saisie manuelle des probas marche")
    st.caption(
        "Entre les 5 probas implicites (apres retrait de marge). Sert a comparer "
        "vite les deux methodes sur un cas pedagogique."
    )

    presets = {
        "Match equilibre, beaucoup de buts": (0.34, 0.27, 0.39, 0.60, 0.58),
        "Favori domicile, peu de buts": (0.62, 0.24, 0.14, 0.42, 0.48),
        "Outsider domicile sur defensif": (0.22, 0.30, 0.48, 0.40, 0.46),
        "Derby ferme nul probable": (0.30, 0.36, 0.34, 0.38, 0.43),
    }
    preset = st.selectbox(
        "Preset (optionnel)", ["— Saisie libre —", *presets.keys()], index=1
    )
    if preset != "— Saisie libre —":
        p_h, p_d, p_a, p_over25, p_btts = presets[preset]
    else:
        p_h, p_d, p_a, p_over25, p_btts = 0.50, 0.27, 0.23, 0.55, 0.52

    c1, c2, c3, c4, c5 = st.columns(5)
    p_h = c1.number_input("P(1)", 0.01, 0.98, value=float(p_h), step=0.01)
    p_d = c2.number_input("P(X)", 0.01, 0.98, value=float(p_d), step=0.01)
    p_a = c3.number_input("P(2)", 0.01, 0.98, value=float(p_a), step=0.01)
    p_over25 = c4.number_input(
        "P(Over 2.5)", 0.01, 0.99, value=float(p_over25), step=0.01
    )
    p_btts = c5.number_input("P(BTTS)", 0.01, 0.99, value=float(p_btts), step=0.01)

    # Normaliser 1X2
    s = p_h + p_d + p_a
    if abs(s - 1.0) > 0.005:
        st.warning(f"Somme 1X2 = {s:.3f}, normalisation appliquee")
        p_h, p_d, p_a = p_h / s, p_d / s, p_a / s

    market = {"p_h": p_h, "p_d": p_d, "p_a": p_a, "p_over25": p_over25, "p_btts": p_btts}

    res_dbl = IM.invert_double(p_h, p_d, p_a, p_over25)
    res_tri = IM.invert_triple(p_h, p_d, p_a, p_over25, p_btts)

    col_l, col_r = st.columns(2)
    with col_l:
        _result_card("Methode actuelle (Poisson 2 params)", res_dbl, market)
        _scoreline_heatmap("Double", res_dbl.lambda_h, res_dbl.lambda_a, res_dbl.rho)
    with col_r:
        _result_card("Methode nouvelle (Dixon-Coles 3 params)", res_tri, market)
        _scoreline_heatmap("Triple", res_tri.lambda_h, res_tri.lambda_a, res_tri.rho)

    st.divider()
    st.subheader("Delta entre les deux methodes")
    d_dbl = IM.derived_probs(res_dbl.lambda_h, res_dbl.lambda_a, res_dbl.rho)
    d_tri = IM.derived_probs(res_tri.lambda_h, res_tri.lambda_a, res_tri.rho)
    delta = pd.DataFrame(
        [
            {
                "marche": k_label,
                "marche": v_market,
                "double_indep": d_dbl[k_model],
                "triple_dc": d_tri[k_model],
                "delta (triple - double)": d_tri[k_model] - d_dbl[k_model],
            }
            for k_label, v_market, k_model in [
                ("1", market["p_h"], "p_h"),
                ("X", market["p_d"], "p_d"),
                ("2", market["p_a"], "p_a"),
                ("O2.5", market["p_over25"], "p_over"),
                ("BTTS", market["p_btts"], "p_btts"),
            ]
        ]
    )
    st.dataframe(delta, hide_index=True, width="stretch")
    st.caption(
        "Si la methode triple respecte mieux le BTTS marche (residuel ~0) alors qu'elle"
        " s'ecarte legerement sur 1X2/O2.5, c'est attendu : on a 5 contraintes pour"
        " 3 inconnues, donc l'optimiseur arbitre."
    )


def section_bsd_match():
    st.subheader("Inversion d'un match reel via BSD")
    st.caption(
        "Selectionne une league + saison BSD, on fetch jusqu'a 30 matchs finis "
        "(cache 24h) puis tu choisis un match. Si le payload BSD ne donne pas les "
        "3 marches (1X2 + O/U 2.5 + BTTS), on l'indique."
    )

    LEAGUES = {
        "Premier League": 1,
        "La Liga": 3,
        "Serie A": 4,
        "Bundesliga": 5,
        "Ligue 1": 6,
    }
    c1, c2, c3 = st.columns([2, 2, 1])
    league_name = c1.selectbox("League", list(LEAGUES.keys()))
    season_id = c2.number_input(
        "Season ID BSD", 1, 99999, value=2024, step=1,
        help="A ajuster selon le mapping BSD reel"
    )
    fetch = c3.button("Charger matchs", type="primary")

    if fetch or st.session_state.get("phase1_matches_loaded"):
        if fetch:
            with st.spinner("Fetch BSD..."):
                matches = MF.list_finished_matches(LEAGUES[league_name], int(season_id), limit=30)
            st.session_state["phase1_matches"] = matches
            st.session_state["phase1_matches_loaded"] = True
        matches = st.session_state.get("phase1_matches", [])

        if not matches:
            st.warning(
                "Aucun match trouve. Les noms d'endpoints BSD peuvent differer ; "
                "voir le module `match_fetcher.py` pour ajuster les routes."
            )
            return

        def _label(m: dict) -> str:
            mid = m.get("id") or m.get("match_id") or "?"
            home = (m.get("home_team") or m.get("home") or {})
            away = (m.get("away_team") or m.get("away") or {})
            hn = home.get("name") if isinstance(home, dict) else str(home)
            an = away.get("name") if isinstance(away, dict) else str(away)
            score = m.get("score") or {}
            sh = score.get("home", "?") if isinstance(score, dict) else "?"
            sa = score.get("away", "?") if isinstance(score, dict) else "?"
            return f"#{mid} — {hn} {sh}-{sa} {an}"

        labels = [_label(m) for m in matches]
        idx = st.selectbox("Match", range(len(matches)), format_func=lambda i: labels[i])
        match = matches[idx]
        match_id = match.get("id") or match.get("match_id")

        with st.spinner("Fetch cotes compareOdds..."):
            odds = MF.fetch_compare_odds(int(match_id))
        if not odds:
            st.error("Aucune cote retournee par BSD pour ce match.")
            with st.expander("Payload match brut"):
                st.json(match)
            return

        market = MF.extract_market_probs(odds)
        if not market:
            st.error(
                "Payload cotes incomplet (manque 1X2 ou O/U 2.5 ou BTTS). "
                "Voir le payload brut ci-dessous pour aligner les aliases."
            )
            with st.expander("Payload cotes brut"):
                st.json(odds)
            return

        st.success(
            f"Cotes recuperees : 1={market['raw_odds']['1']:.2f}  "
            f"X={market['raw_odds']['X']:.2f}  2={market['raw_odds']['2']:.2f}  "
            f"O2.5={market['raw_odds']['O2.5']:.2f}  BTTS_Y={market['raw_odds']['BTTS_Y']:.2f}"
        )

        res_dbl = IM.invert_double(market["p_h"], market["p_d"], market["p_a"], market["p_over25"])
        res_tri = IM.invert_triple(
            market["p_h"], market["p_d"], market["p_a"], market["p_over25"], market["p_btts"]
        )

        col_l, col_r = st.columns(2)
        with col_l:
            _result_card("Methode actuelle (Poisson 2 params)", res_dbl, market)
        with col_r:
            _result_card("Methode nouvelle (Dixon-Coles 3 params)", res_tri, market)

        # Comparaison avec resultat reel si dispo
        result = MF.extract_result(match)
        if result:
            ll_dbl = IM.score_log_loss(
                IM.derived_probs(res_dbl.lambda_h, res_dbl.lambda_a, 0)["p_h"],
                IM.derived_probs(res_dbl.lambda_h, res_dbl.lambda_a, 0)["p_d"],
                IM.derived_probs(res_dbl.lambda_h, res_dbl.lambda_a, 0)["p_a"],
                result,
            )
            d_tri = IM.derived_probs(res_tri.lambda_h, res_tri.lambda_a, res_tri.rho)
            ll_tri = IM.score_log_loss(d_tri["p_h"], d_tri["p_d"], d_tri["p_a"], result)
            st.divider()
            st.metric(
                f"Resultat reel : {result}",
                f"log-loss double = {ll_dbl:.3f}  |  triple = {ll_tri:.3f}",
                delta=f"{ll_dbl - ll_tri:+.3f}",
                delta_color="normal",
                help="Positif = triple meilleur sur ce match (log-loss plus petit)",
            )


def section_backtest():
    st.subheader("Backtest agrege 1X2 (log-loss)")
    st.caption(
        "Selectionne N matchs finis recents, on fait l'inversion double et triple, "
        "puis on agrege le log-loss. Couteux la 1re fois (cache 24h ensuite)."
    )

    LEAGUES = {
        "Premier League": 1,
        "La Liga": 3,
        "Serie A": 4,
        "Bundesliga": 5,
        "Ligue 1": 6,
    }
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    league_name = c1.selectbox("League", list(LEAGUES.keys()), key="bt_league")
    season_id = c2.number_input("Season ID", 1, 99999, value=2024, key="bt_season")
    n_max = c3.slider("N matchs", 5, 100, 30, step=5)
    run = c4.button("Lancer backtest", type="primary")

    if not run:
        st.info("Clique sur 'Lancer backtest' pour declencher la fetch + inversion.")
        return

    with st.spinner(f"Fetch matchs ({n_max} max)..."):
        matches = MF.list_finished_matches(LEAGUES[league_name], int(season_id), limit=n_max)

    if not matches:
        st.error("Aucun match trouve. Verifie le mapping league/season BSD.")
        return

    progress = st.progress(0.0)
    rows = []
    failed = 0
    for i, m in enumerate(matches[:n_max]):
        progress.progress((i + 1) / min(n_max, len(matches)))
        mid = m.get("id") or m.get("match_id")
        if mid is None:
            failed += 1
            continue
        odds = MF.fetch_compare_odds(int(mid))
        market = MF.extract_market_probs(odds) if odds else None
        result = MF.extract_result(m)
        if not (market and result):
            failed += 1
            continue
        res_dbl = IM.invert_double(market["p_h"], market["p_d"], market["p_a"], market["p_over25"])
        res_tri = IM.invert_triple(
            market["p_h"], market["p_d"], market["p_a"], market["p_over25"], market["p_btts"]
        )
        d_dbl = IM.derived_probs(res_dbl.lambda_h, res_dbl.lambda_a, 0)
        d_tri = IM.derived_probs(res_tri.lambda_h, res_tri.lambda_a, res_tri.rho)
        ll_dbl = IM.score_log_loss(d_dbl["p_h"], d_dbl["p_d"], d_dbl["p_a"], result)
        ll_tri = IM.score_log_loss(d_tri["p_h"], d_tri["p_d"], d_tri["p_a"], result)
        rows.append(
            {
                "match_id": mid,
                "outcome": result,
                "ll_double": ll_dbl,
                "ll_triple": ll_tri,
                "delta_btts_double": d_dbl["p_btts"] - market["p_btts"],
                "delta_btts_triple": d_tri["p_btts"] - market["p_btts"],
            }
        )
    progress.empty()

    if not rows:
        st.error(
            f"Aucun match exploitable (couverture cotes BSD insuffisante). "
            f"{failed} matchs rejetes."
        )
        return

    df = pd.DataFrame(rows)
    st.success(f"{len(df)} matchs traites ({failed} rejetes).")

    c1, c2, c3 = st.columns(3)
    c1.metric("Log-loss moyen (double)", f"{df['ll_double'].mean():.4f}")
    c2.metric("Log-loss moyen (triple)", f"{df['ll_triple'].mean():.4f}",
              delta=f"{df['ll_triple'].mean() - df['ll_double'].mean():+.4f}",
              delta_color="inverse")
    win_rate = (df["ll_triple"] < df["ll_double"]).mean()
    c3.metric("Matchs ou triple bat double", f"{win_rate*100:.1f} %")

    c1, c2 = st.columns(2)
    c1.metric(
        "|residuel BTTS| moyen (double)",
        f"{df['delta_btts_double'].abs().mean():.4f}",
        help="Distance entre P(BTTS) implicite par l'inversion double et P(BTTS) marche reel",
    )
    c2.metric(
        "|residuel BTTS| moyen (triple)",
        f"{df['delta_btts_triple'].abs().mean():.4f}",
        delta=f"{df['delta_btts_triple'].abs().mean() - df['delta_btts_double'].abs().mean():+.4f}",
        delta_color="inverse",
    )

    st.dataframe(df, hide_index=True, width="stretch")

    # Persist resultats pour le report
    out_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "reports"
        / f"backtest_{league_name.replace(' ', '_')}_{season_id}.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    st.caption(f"Resultats sauves : `{out_path.relative_to(out_path.parents[2])}`")


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────


def render():
    st.title("Phase 1 — Triple inversion (1X2 + O/U + BTTS)")
    st.markdown(
        """
On compare deux methodes d'inversion du marche :

- **Methode actuelle prod** : Poisson independants 2 parametres `(lambda_h, lambda_a)`
  ajustes sur 4 contraintes (1, X, 2, Over 2.5). BTTS non utilise.
- **Methode nouvelle** : Dixon-Coles 3 parametres `(lambda_h, lambda_a, rho)` ajustes
  sur 5 contraintes (1, X, 2, O2.5, **BTTS**) par moindres carres ponderes.

Le terme `rho` ajuste les bas scores (0-0, 0-1, 1-0, 1-1) qui sont structurellement
sous-evalues par Poisson independants.
"""
    )

    tab1, tab2, tab3 = st.tabs(
        ["Saisie manuelle", "Match BSD reel", "Backtest log-loss"]
    )
    with tab1:
        section_manual()
    with tab2:
        section_bsd_match()
    with tab3:
        section_backtest()
