"""Pages Streamlit pour le pipeline forward-test live.

- `render_edges_page()`     : edges buteurs/passeurs J/J+1
- `render_tracking_page()`  : historique enrichi du forward log + métriques perf
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FORWARD_LOG = DATA_DIR / "forward_log.jsonl"
DASH_ROOT = ROOT.parent

LEAGUE_LABELS = {
    "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
    "la_liga": "🇪🇸 La Liga",
    "serie_a": "🇮🇹 Serie A",
    "bundesliga": "🇩🇪 Bundesliga",
    "ligue_1": "🇫🇷 Ligue 1",
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
@st.cache_data(ttl=120, show_spinner=False)
def load_forward_log_df() -> pd.DataFrame:
    """Charge forward_log.jsonl en DataFrame ; retourne un df vide si absent."""
    if not FORWARD_LOG.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    with FORWARD_LOG.open() as f:
        for ln in f:
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Colonnes datetime
    for c in ("logged_at", "kickoff", "enriched_at"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True)
    return df


def _run_predict_today(args_extra: list[str]) -> tuple[bool, str]:
    """Lance predict_today.py en sous-processus, capture stdout/stderr."""
    cmd = [sys.executable, str(ROOT / "predict_today.py")] + args_extra
    try:
        res = subprocess.run(
            cmd, cwd=DASH_ROOT, capture_output=True, text=True, timeout=300
        )
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        return res.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT après 5 minutes"


def _run_enrich_results() -> tuple[bool, str]:
    cmd = [sys.executable, str(ROOT / "enrich_results.py")]
    try:
        res = subprocess.run(
            cmd, cwd=DASH_ROOT, capture_output=True, text=True, timeout=180
        )
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        return res.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"


# ---------------------------------------------------------------------------
# Page : Edges Buteurs/Passeurs
# ---------------------------------------------------------------------------
def render_edges_page():
    st.header("🎯 Edges Buteurs / Passeurs (Live Top 5)")
    st.caption(
        "Edges = (cote bookmaker × probabilité modèle) − 1. "
        "Modèle propriétaire : g2_engine (1X2+O/U+BTTS) → λ équipes → "
        "distribution Poisson individuelle (xG/xA shrinkés vs prior ligue)."
    )

    # --- Toolbar : actions ---
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        if st.button("🔄 Lancer prédictions maintenant", type="primary"):
            with st.spinner("Pipeline en cours (1-3 min selon le nombre de matchs)..."):
                ok, log_txt = _run_predict_today(["--days", "2"])
            if ok:
                st.success("Prédictions générées et appendées au log.")
            else:
                st.error("Échec du pipeline.")
            with st.expander("Logs"):
                st.code(log_txt[-4000:])
            load_forward_log_df.clear()  # invalide le cache
    with col_b:
        if st.button("🧮 Enrichir résultats matchs finis"):
            with st.spinner("Enrichissement..."):
                ok, log_txt = _run_enrich_results()
            (st.success if ok else st.error)("Enrichissement terminé." if ok else "Échec.")
            with st.expander("Logs"):
                st.code(log_txt[-4000:])
            load_forward_log_df.clear()

    df = load_forward_log_df()
    if df.empty:
        st.info(
            "Aucune prédiction encore loggée. Clique sur **Lancer prédictions maintenant** "
            "pour générer les edges du week-end."
        )
        return

    st.markdown("---")

    # --- Filtres ---
    fcols = st.columns(5)
    with fcols[0]:
        ligues_dispo = sorted(df["league_slug"].dropna().unique())
        sel_ligues = st.multiselect(
            "Ligue", ligues_dispo,
            default=ligues_dispo,
            format_func=lambda s: LEAGUE_LABELS.get(s, s),
        )
    with fcols[1]:
        marche = st.radio("Marché", ["Buteur", "Passeur", "Les deux"], horizontal=False)
    with fcols[2]:
        edge_min = st.number_input("Edge min %", -50.0, 100.0, 0.0, 0.5)
    with fcols[3]:
        only_with_book = st.checkbox("Uniquement avec cote book", value=True)
    with fcols[4]:
        only_starters = st.checkbox("Uniquement titulaires probables", value=False)

    df_f = df[df["league_slug"].isin(sel_ligues)].copy()
    if only_starters:
        df_f = df_f[df_f["is_starter"] == True]  # noqa: E712

    # --- Construction du tableau long (1 ligne = 1 marché plat par joueur) ---
    long_rows = []
    for _, r in df_f.iterrows():
        common = {
            "Ligue": LEAGUE_LABELS.get(r["league_slug"], r["league_slug"]),
            "Match": r["match"],
            "Kickoff": r["kickoff"].tz_convert("Europe/Paris").strftime("%a %d/%m %H:%M")
                       if pd.notna(r["kickoff"]) else "",
            "Joueur": r["player_name"],
            "Side": "🏠" if r["team_side"] == "home" else "🛫",
            "Titu": "✓" if r.get("is_starter") else "Sub",
            "Min att.": round(float(r.get("minutes_expected") or 0)),
        }
        if marche in ("Buteur", "Les deux") and pd.notna(r.get("p_model_scorer")):
            long_rows.append({**common,
                "Marché": "⚽ Buteur",
                "p modèle": r["p_model_scorer"],
                "Cote juste": r["fair_odd_scorer"],
                "Cote Betclic": r.get("betclic_odd_scorer"),
                "Edge %": (r["edge_scorer"] * 100) if pd.notna(r.get("edge_scorer")) else None,
                "_outcome": r.get("outcome_scored"),
            })
        if marche in ("Passeur", "Les deux") and pd.notna(r.get("p_model_assist")):
            long_rows.append({**common,
                "Marché": "🅰 Passeur",
                "p modèle": r["p_model_assist"],
                "Cote juste": r["fair_odd_assist"],
                "Cote Betclic": r.get("betclic_odd_assist"),
                "Edge %": (r["edge_assist"] * 100) if pd.notna(r.get("edge_assist")) else None,
                "_outcome": r.get("outcome_assisted"),
            })

    if not long_rows:
        st.warning("Aucune ligne après filtres.")
        return

    out = pd.DataFrame(long_rows)

    if only_with_book:
        out = out[out["Cote Betclic"].notna()]

    if not out.empty:
        out = out[(out["Edge %"].fillna(-999) >= edge_min)]

    if out.empty:
        st.warning("Aucun edge ne passe le seuil.")
        return

    # Tri par edge descendant
    out = out.sort_values("Edge %", ascending=False, na_position="last")

    # Formatage
    out_show = out.drop(columns=["_outcome"]).copy()
    out_show["p modèle"] = (out_show["p modèle"] * 100).round(1)
    out_show["Cote juste"] = out_show["Cote juste"].round(2)
    out_show["Cote Betclic"] = out_show["Cote Betclic"].round(2)
    out_show["Edge %"] = out_show["Edge %"].round(2)
    out_show.rename(columns={"p modèle": "p mod. %"}, inplace=True)

    def color_edge(v):
        if pd.isna(v):
            return ""
        if v >= 5:
            return "background-color: #c6f6d5; color: #1a4d2e; font-weight: 600"
        if v >= 0:
            return "background-color: #fef9c3; color: #5b3a00"
        return "color: #6b7280"

    styled = (out_show.style
              .map(color_edge, subset=["Edge %"])
              .format({"p mod. %": "{:.1f}", "Cote juste": "{:.2f}",
                       "Cote Betclic": "{:.2f}", "Edge %": "{:+.2f}"}, na_rep="—"))

    st.markdown(f"**{len(out_show)} edges** triés par valeur décroissante")
    st.dataframe(styled, use_container_width=True, hide_index=True, height=600)

    # Export
    st.download_button(
        "💾 Exporter CSV",
        out_show.to_csv(index=False).encode("utf-8"),
        file_name=f"edges_{datetime.now():%Y%m%d_%H%M}.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# Page : Tracking forward log (perf historique)
# ---------------------------------------------------------------------------
def render_tracking_page():
    st.header("📈 Tracking Forward Test — Performance live")
    st.caption(
        "Historique de tous les picks loggés. ROI calculé en simulant 1u flat "
        "sur chaque pick avec edge > seuil (sélection theoretical, à mise sur cote bookmaker)."
    )

    df = load_forward_log_df()
    if df.empty:
        st.info("Pas encore de log forward. Va dans la page Edges et lance le pipeline.")
        return

    # Construction long (idem)
    rows = []
    for _, r in df.iterrows():
        for kind, p_col, fair_col, book_col, outcome_col, edge_col in [
            ("scorer", "p_model_scorer", "fair_odd_scorer", "betclic_odd_scorer",
             "outcome_scored", "edge_scorer"),
            ("assist", "p_model_assist", "fair_odd_assist", "betclic_odd_assist",
             "outcome_assisted", "edge_assist"),
        ]:
            if pd.isna(r.get(p_col)):
                continue
            rows.append({
                "league": r["league_slug"],
                "match": r["match"],
                "kickoff": r["kickoff"],
                "player": r["player_name"],
                "marche": kind,
                "p_model": r[p_col],
                "fair_odd": r[fair_col],
                "book_odd": r.get(book_col),
                "edge": r.get(edge_col),
                "outcome": r.get(outcome_col),
                "enriched": pd.notna(r.get("enriched_at")),
            })

    pdf = pd.DataFrame(rows)

    # KPIs globaux
    enriched = pdf[pdf["enriched"]]
    pending = pdf[~pdf["enriched"]]
    valued = enriched[(enriched["edge"].notna()) & (enriched["edge"] > 0) & (enriched["book_odd"].notna())]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Picks loggés", len(pdf))
    c2.metric("Matches finis (enrichis)", len(enriched))
    c3.metric("En attente résultat", len(pending))
    c4.metric("Picks à edge > 0% (joués)", len(valued))

    if valued.empty:
        st.info("Pas encore de picks à edge > 0% sur des matchs finis. Patience !")
        return

    # ROI par tranche d'edge
    valued = valued.copy()
    valued["pnl"] = valued.apply(
        lambda r: (r["book_odd"] - 1.0) if r["outcome"] else -1.0, axis=1
    )
    valued["edge_bin"] = pd.cut(
        valued["edge"] * 100,
        bins=[0, 2, 5, 10, 20, 100],
        labels=["0-2%", "2-5%", "5-10%", "10-20%", ">20%"],
        include_lowest=True,
    )

    st.markdown("### Performance par tranche d'edge")
    perf = (valued.groupby(["marche", "edge_bin"], observed=True)
            .agg(picks=("pnl", "size"),
                 wins=("outcome", "sum"),
                 pnl=("pnl", "sum"),
                 stake=("pnl", "size"))
            .reset_index())
    perf["roi_%"] = (perf["pnl"] / perf["stake"] * 100).round(2)
    perf["hit_rate_%"] = (perf["wins"] / perf["picks"] * 100).round(1)
    st.dataframe(perf[["marche", "edge_bin", "picks", "wins", "hit_rate_%", "pnl", "roi_%"]],
                 use_container_width=True, hide_index=True)

    # ROI cumulé
    st.markdown("### ROI cumulé")
    cumul = valued.sort_values("kickoff").reset_index(drop=True)
    cumul["pnl_cum"] = cumul["pnl"].cumsum()
    cumul["pick_id"] = range(1, len(cumul) + 1)
    st.line_chart(cumul.set_index("pick_id")["pnl_cum"], height=300)

    with st.expander("📋 Détail des picks joués"):
        show = cumul[["kickoff", "league", "match", "player", "marche", "p_model",
                      "fair_odd", "book_odd", "edge", "outcome", "pnl"]].copy()
        show["p_model"] = (show["p_model"] * 100).round(1)
        show["edge"] = (show["edge"] * 100).round(2)
        st.dataframe(show, use_container_width=True, hide_index=True)
