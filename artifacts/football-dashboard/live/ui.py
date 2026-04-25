"""Pages Streamlit pour le pipeline forward-test live.

- `render_edges_page()`               : test edges buteurs/passeurs J/J+1
- `render_tracking_page()`            : historique enrichi du forward log + métriques perf
- `render_predictions_buteurs_page()` : liste matchs prévus + drill-down détail riche (BSD)
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
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
    st.header("🎯 Test Edge Buteurs (Top 5)")
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
    st.header("📈 Tracking Test Edge Buteurs — Performance live")
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


# ---------------------------------------------------------------------------
# Page : Prédiction Buteurs (drill-down match → détail riche BSD)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _bsd_event_detail_cached(event_id: int) -> dict:
    """Cache 5 min sur le détail BSD pour éviter de re-fetch à chaque rerun.
    Retour conventionné :
      - dict normal : succès
      - dict {"_error": str} : erreur réseau / API / payload vide
    """
    sys.path.insert(0, str(DASH_ROOT))
    from live.bsd_helpers import get_event_detail
    from live.transfer_overrides import inject_into_event_detail
    try:
        d = get_event_detail(event_id)
        if not d:
            return {"_error": "BSD a renvoyé une réponse vide pour cet event."}
        # Enrichit `unavailable_players` avec nos overrides manuels (transferts/prêts)
        try:
            home_id = (d.get("home_team_obj") or d.get("home_team") or {})
            home_id = home_id.get("id") if isinstance(home_id, dict) else None
            away_id = (d.get("away_team_obj") or d.get("away_team") or {})
            away_id = away_id.get("id") if isinstance(away_id, dict) else None
            inject_into_event_detail(d, home_id, away_id)
        except Exception:
            pass
        return d
    except Exception as e:
        return {"_error": str(e)}


def _safe_float(v, default: float | None = None) -> float | None:
    """Cast tolérant : renvoie default si v est None/NaN/non castable."""
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return f


def _fmt_num(v, fmt: str = "{:.2f}", na: str = "—") -> str:
    """Formate un nombre safe (renvoie na si None/NaN/non-numérique)."""
    f = _safe_float(v)
    if f is None:
        return na
    return fmt.format(f)


def _format_form_string(form: str) -> str:
    """LLWWW → coloré"""
    if not form:
        return ""
    out = []
    for c in form.upper():
        if c == "W":
            out.append("🟢")
        elif c == "D":
            out.append("⚪")
        elif c == "L":
            out.append("🔴")
        else:
            out.append(c)
    return "".join(out)


def _render_radar_compare(home_form: dict, away_form: dict, home_name: str, away_name: str):
    """Radar comparatif des 2 équipes sur les KPIs disponibles dans home/away_form."""
    if not home_form or not away_form:
        return
    metrics = [
        ("avg_xg", "xG/match", 0, 3.0),
        ("avg_xg_conceded", "xG concédé", 3.0, 0),  # inversé : moins = mieux
        ("avg_shots", "Tirs/match", 0, 20.0),
        ("avg_shots_on_target", "Tirs cadrés", 0, 8.0),
        ("avg_pass_accuracy", "% passes", 50.0, 95.0),
        ("duel_win_rate", "% duels gagnés", 0.30, 0.70),
        ("aerial_win_rate", "% duels aériens", 0.30, 0.70),
    ]
    rows = []
    for key, label, lo, hi in metrics:
        h = home_form.get(key)
        a = away_form.get(key)
        if h is None or a is None:
            continue
        # normalisation 0-100 (gérée pour le sens inverse via lo > hi)
        def norm(v):
            if hi == lo:
                return 50.0
            x = (v - lo) / (hi - lo) * 100.0
            return max(0.0, min(100.0, x))
        rows.append({"métrique": label, home_name: round(norm(h), 1),
                     away_name: round(norm(a), 1)})
    if not rows:
        return
    df_radar = pd.DataFrame(rows).set_index("métrique")
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        cats = list(df_radar.index) + [df_radar.index[0]]
        for col, color in [(home_name, "rgba(220,38,38,0.6)"),
                           (away_name, "rgba(37,99,235,0.6)")]:
            vals = df_radar[col].tolist() + [df_radar[col].iloc[0]]
            fig.add_trace(go.Scatterpolar(r=vals, theta=cats, fill="toself",
                                          name=col, line=dict(color=color)))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=True, height=420, margin=dict(l=20, r=20, t=20, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)
    except ImportError:
        st.bar_chart(df_radar)


def _coach_name(coach) -> str:
    """Extrait le nom + nationalité depuis dict ou string."""
    if not coach:
        return ""
    if isinstance(coach, str):
        return coach
    if isinstance(coach, dict):
        nm = coach.get("name") or coach.get("short_name") or "?"
        country = coach.get("country")
        if country:
            return f"{nm} ({country})"
        return nm
    return str(coach)


def _coach_extras(coach) -> str | None:
    """Tags supplémentaires (formation préférée, style)."""
    if not isinstance(coach, dict):
        return None
    bits = []
    pf = coach.get("preferred_formation")
    if pf:
        bits.append(f"⚙️ Formation préférée : `{pf}`")
    styles = coach.get("top_styles") or []
    if isinstance(styles, list) and styles:
        bits.append(f"🎨 Styles : {', '.join(str(s) for s in styles[:3])}")
    profile = coach.get("profile")
    if profile:
        bits.append(f"🧭 Profil : {profile}")
    return " · ".join(bits) if bits else None


def _render_lineup_column(side_block: dict, side_label: str, coach):
    """Affiche une compo (1 colonne) : formation, coach, starters, subs."""
    formation = (side_block.get("formation") or side_block.get("system")
                 or side_block.get("tactical_formation"))
    starters = side_block.get("starters") or side_block.get("starting") or []
    subs = side_block.get("substitutes") or side_block.get("subs") or []

    st.markdown(f"### {side_label}")
    coach_str = _coach_name(coach)
    if coach_str:
        st.markdown(f"👤 **Coach :** {coach_str}")
        extras = _coach_extras(coach)
        if extras:
            st.caption(extras)
    if formation:
        st.markdown(f"⚙️ **Système :** `{formation}`")
    elif not starters:
        st.caption("⏳ Compo non encore confirmée par BSD (publiée ~1h avant kick-off).")

    if starters:
        st.markdown("**Onze de départ**")
        for p in starters:
            if not isinstance(p, dict):
                continue
            name = (p.get("player") or {}).get("name") if isinstance(p.get("player"), dict) \
                else p.get("name") or p.get("player_name") or "?"
            pos = p.get("position") or p.get("role") or ""
            num = p.get("jersey_number") or p.get("shirt_number") or ""
            num_s = f"#{num} " if num else ""
            pos_s = f" · {pos}" if pos else ""
            st.markdown(f"- {num_s}{name}{pos_s}")
    if subs:
        with st.expander(f"🪑 Remplaçants ({len(subs)})"):
            for p in subs:
                if not isinstance(p, dict):
                    continue
                name = (p.get("player") or {}).get("name") if isinstance(p.get("player"), dict) \
                    else p.get("name") or p.get("player_name") or "?"
                pos = p.get("position") or ""
                num = p.get("jersey_number") or ""
                num_s = f"#{num} " if num else ""
                pos_s = f" · {pos}" if pos else ""
                st.markdown(f"- {num_s}{name}{pos_s}")


def _render_match_detail(event_id: int, df_log: pd.DataFrame):
    """Vue détail d'un match : header, odds, lineups, stats, buteurs prédits."""
    sub = df_log[df_log["event_id"] == event_id]
    if sub.empty:
        st.warning("Aucune ligne dans le log pour cet event.")
        return

    head = sub.iloc[0]
    detail = _bsd_event_detail_cached(int(event_id))
    if detail.get("_error"):
        st.warning(
            f"⚠️ Détail BSD indisponible — affichage limité aux données du forward log. "
            f"_Cause : {detail['_error']}_"
        )
        detail = {}

    # === En-tête ===
    home_name = head.get("home_team") or head["match"].split(" - ")[0]
    away_name = head.get("away_team") or head["match"].split(" - ")[-1]
    kickoff_str = head["kickoff"].tz_convert("Europe/Paris").strftime("%a %d %b — %H:%M") \
        if pd.notna(head["kickoff"]) else "?"
    st.subheader(f"⚽ {home_name} — {away_name}")
    venue = detail.get("venue") or {}
    venue_str = ""
    if isinstance(venue, dict) and venue.get("name"):
        venue_str = f"🏟️ {venue['name']}"
        if venue.get("city"):
            venue_str += f", {venue['city']}"
    referee = detail.get("referee")
    ref_str = ""
    if isinstance(referee, dict):
        ref_str = f"🟥 Arbitre : {referee.get('name', '?')}"
    elif isinstance(referee, str) and referee:
        ref_str = f"🟥 Arbitre : {referee}"
    league_label = LEAGUE_LABELS.get(head["league_slug"], head["league_slug"])
    season_obj = detail.get("season") or {}
    season_str = season_obj.get("name", "") if isinstance(season_obj, dict) else ""
    rd = detail.get("round_number")
    rd_str = f" · J{rd}" if rd else ""
    st.markdown(
        f"**{league_label}** — {season_str}{rd_str}  \n"
        f"🕒 {kickoff_str} (heure Paris)  \n"
        f"{venue_str}  \n{ref_str}"
    )

    # === xG modèle vs Marché ===
    st.markdown("---")
    st.markdown("### 📊 xG attendus & marchés")
    c1, c2, c3 = st.columns(3)
    xh = _safe_float(head.get("xg_team_home"), 0.0) or 0.0
    xa = _safe_float(head.get("xg_team_away"), 0.0) or 0.0
    with c1:
        st.metric(f"λ {home_name}", f"{xh:.2f}")
    with c2:
        st.metric(f"λ {away_name}", f"{xa:.2f}")
    with c3:
        st.metric("Total xG", f"{xh + xa:.2f}")
    st.caption(f"Méthode dérivation λ : `{head.get('lambdas_method', '?')}`")

    o_h, o_d, o_a = detail.get("odds_home"), detail.get("odds_draw"), detail.get("odds_away")
    o_o25, o_u25 = detail.get("odds_over_25"), detail.get("odds_under_25")
    o_btts_y, o_btts_n = detail.get("odds_btts_yes"), detail.get("odds_btts_no")
    odds_rows = []
    if o_h: odds_rows.append({"Marché": "1 (Home)", "Cote": o_h})
    if o_d: odds_rows.append({"Marché": "X (Nul)", "Cote": o_d})
    if o_a: odds_rows.append({"Marché": "2 (Away)", "Cote": o_a})
    if o_o25: odds_rows.append({"Marché": "Over 2.5", "Cote": o_o25})
    if o_u25: odds_rows.append({"Marché": "Under 2.5", "Cote": o_u25})
    if o_btts_y: odds_rows.append({"Marché": "BTTS Oui", "Cote": o_btts_y})
    if o_btts_n: odds_rows.append({"Marché": "BTTS Non", "Cote": o_btts_n})
    if odds_rows:
        st.dataframe(pd.DataFrame(odds_rows), use_container_width=True,
                     hide_index=True, height=min(40 + 35 * len(odds_rows), 320))

    # === Compositions ===
    st.markdown("---")
    st.markdown("### 👥 Compositions & système de jeu")
    lineups = detail.get("lineups") or {}
    if isinstance(lineups, dict) and (lineups.get("home") or lineups.get("away")):
        cl, cr = st.columns(2)
        with cl:
            _render_lineup_column(lineups.get("home") or {}, f"🏠 {home_name}",
                                  detail.get("home_coach"))
        with cr:
            _render_lineup_column(lineups.get("away") or {}, f"🛫 {away_name}",
                                  detail.get("away_coach"))
    else:
        st.info("⏳ Compositions non encore confirmées par BSD (publiées ~1h avant le coup d'envoi).")
        # Au moins afficher les coachs
        cc1, cc2 = st.columns(2)
        for col, coach_obj, label in [(cc1, detail.get("home_coach"), home_name),
                                       (cc2, detail.get("away_coach"), away_name)]:
            with col:
                nm = _coach_name(coach_obj)
                if nm:
                    st.markdown(f"👤 **Coach {label} :** {nm}")
                    extras = _coach_extras(coach_obj)
                    if extras:
                        st.caption(extras)

    # === Forme + radar comparatif ===
    home_form = detail.get("home_form") or {}
    away_form = detail.get("away_form") or {}
    if home_form or away_form:
        st.markdown("---")
        st.markdown("### 📈 Forme récente & comparatif des forces")
        fc1, fc2 = st.columns(2)
        for col, form, name, emoji in [(fc1, home_form, home_name, "🏠"),
                                       (fc2, away_form, away_name, "🛫")]:
            with col:
                if not form:
                    continue
                fs = _format_form_string(form.get("form_string", ""))
                st.markdown(f"**{emoji} {name}** — {fs}")
                st.caption(
                    f"{form.get('matches_played', 0)} matchs · "
                    f"{form.get('wins', 0)}V {form.get('draws', 0)}N "
                    f"{form.get('losses', 0)}D · "
                    f"{form.get('goals_scored_last_n', 0)}-"
                    f"{form.get('goals_conceded_last_n', 0)} buts · "
                    f"xG {_fmt_num(form.get('avg_xg'))} | "
                    f"xGA {_fmt_num(form.get('avg_xg_conceded'))}"
                )
        _render_radar_compare(home_form, away_form, home_name, away_name)

    # === Head-to-head ===
    h2h = detail.get("head_to_head") or {}
    if isinstance(h2h, dict) and h2h.get("total_matches"):
        st.markdown("---")
        st.markdown(f"### 🤝 Confrontations directes ({h2h.get('total_matches', 0)} matchs)")
        c1, c2, c3 = st.columns(3)
        c1.metric(f"V {home_name}", h2h.get("home_wins", 0))
        c2.metric("Nuls", h2h.get("draws", 0))
        c3.metric(f"V {away_name}", h2h.get("away_wins", 0))
        avg_g = _safe_float(h2h.get("avg_total_goals"))
        if avg_g is not None:
            st.caption(f"⚽ Moyenne buts/match : **{avg_g:.2f}**")
        recent = h2h.get("recent_matches") or []
        if recent:
            with st.expander(f"📋 {len(recent)} derniers face-à-face"):
                rec_df = pd.DataFrame([
                    {
                        "Date": (m.get("date") or "")[:10],
                        "Domicile": m.get("home"),
                        "Score": f"{m.get('home_score', '?')} - {m.get('away_score', '?')}",
                        "Extérieur": m.get("away"),
                    } for m in recent
                ])
                st.dataframe(rec_df, use_container_width=True, hide_index=True)

    # === Blessés / suspendus ===
    unav = detail.get("unavailable_players") or {}
    if isinstance(unav, dict) and (unav.get("home") or unav.get("away")):
        st.markdown("---")
        st.markdown("### 🚑 Joueurs indisponibles")
        uc1, uc2 = st.columns(2)
        for col, side, name in [(uc1, "home", home_name), (uc2, "away", away_name)]:
            with col:
                lst = unav.get(side) or []
                st.markdown(f"**{name}** ({len(lst)})")
                if not lst:
                    st.caption("—")
                for p in lst[:15]:
                    nm = p.get("name", "?")
                    rn = p.get("reason") or p.get("status") or ""
                    ret = p.get("expected_return")
                    ret_s = f" — retour ~{ret}" if ret else ""
                    st.markdown(f"- {nm} _({rn}{ret_s})_")

    # === Tableau buteurs prédits (interactif) ===
    st.markdown("---")
    st.markdown("### ⚽ Buteurs prédits (modèle propriétaire)")
    _render_predictions_editor(event_id, sub, home_name, away_name)


# ---------------------------------------------------------------------------
# Helpers : éditeur interactif des prédictions buteurs (R004)
# ---------------------------------------------------------------------------
_AVAIL_EMOJI = {
    "available": "",
    "doubtful": "❓",
    "injured": "🤕",
    "suspended": "🟥",
    "missing": "🤕",
}


def _safe_avail(value) -> str:
    """Retourne availability normalisée en lower-case ; NaN/None → 'available'."""
    if value is None:
        return "available"
    if isinstance(value, float) and pd.isna(value):
        return "available"
    s = str(value).strip().lower()
    return s or "available"


def _initial_inclusion_state(sub: pd.DataFrame) -> dict[int, bool]:
    """Par défaut : on inclut tous les joueurs disponibles, on exclut les
    blessés/suspendus. Les joueurs explicitement marqués `excluded` (BSD lineup
    publiée + joueur indisponible) sont également exclus."""
    state: dict[int, bool] = {}
    for _, r in sub.iterrows():
        pid = int(r["player_id"])
        avail = _safe_avail(r.get("availability"))
        excluded_val = r.get("excluded", False)
        is_excluded_log = bool(excluded_val) and not (
            isinstance(excluded_val, float) and pd.isna(excluded_val)
        )
        state[pid] = (avail == "available") and not is_excluded_log
    return state


def _recalculate_shares(sub: pd.DataFrame, included_pids: set[int]) -> pd.DataFrame:
    """Recalcule xg_calibré, p_scorer, odd_scorer, edge pour chaque équipe en
    se basant uniquement sur les joueurs cochés (`included_pids`).

    Nécessite que le forward_log contienne `xg_per_90_used`, `xa_per_90_used`,
    `minutes_expected`, `xg_team_home`, `xg_team_away`.
    """
    df = sub.copy()
    df["_pid"] = df["player_id"].astype(int)
    df["_in"] = df["_pid"].isin(included_pids)

    # Première ligne pour récupérer xg_team
    xg_h = float(df["xg_team_home"].dropna().iloc[0]) if df["xg_team_home"].notna().any() else 0.0
    xg_a = float(df["xg_team_away"].dropna().iloc[0]) if df["xg_team_away"].notna().any() else 0.0
    team_xg_target = {"home": xg_h, "away": xg_a}
    team_xa_target = {"home": xg_h * 0.75, "away": xg_a * 0.75}

    # Recalcul par équipe
    for side in ("home", "away"):
        mask = (df["team_side"] == side) & df["_in"]
        if not mask.any():
            continue
        sub_team = df.loc[mask].copy()
        # raw = xg_per_90_used * mins/90  (déjà historisé par le modèle)
        raw_xg = (sub_team["xg_per_90_used"].fillna(0).astype(float)
                  * sub_team["minutes_expected"].fillna(0).astype(float) / 90.0)
        raw_xa = (sub_team["xa_per_90_used"].fillna(0).astype(float)
                  * sub_team["minutes_expected"].fillna(0).astype(float) / 90.0)
        total_xg = float(raw_xg.sum()) or 1e-9
        total_xa = float(raw_xa.sum()) or 1e-9

        xg_cal = team_xg_target[side] * (raw_xg / total_xg)
        xa_cal = team_xa_target[side] * (raw_xa / total_xa)

        p_scorer = 1.0 - np.exp(-xg_cal)
        p_assist = 1.0 - np.exp(-xa_cal)

        df.loc[mask, "xg_player"] = xg_cal.values
        df.loc[mask, "xa_player"] = xa_cal.values
        df.loc[mask, "p_model_scorer"] = p_scorer.values
        df.loc[mask, "p_model_assist"] = p_assist.values
        df.loc[mask, "fair_odd_scorer"] = np.where(p_scorer > 0, 1.0 / p_scorer, np.nan)
        df.loc[mask, "fair_odd_assist"] = np.where(p_assist > 0, 1.0 / p_assist, np.nan)

        # Edges
        for col_p, col_bc, col_edge in [("p_model_scorer", "betclic_odd_scorer", "edge_scorer"),
                                         ("p_model_assist", "betclic_odd_assist", "edge_assist")]:
            bc = sub_team[col_bc].astype(float)
            p = df.loc[mask, col_p].astype(float)
            edge = p.values * bc.values - 1.0
            edge = np.where(bc.isna().values | p.isna().values, np.nan, edge)
            df.loc[mask, col_edge] = edge

    # Joueurs décochés → on neutralise leurs prédictions (NaN)
    excluded_mask = ~df["_in"]
    for col in ("xg_player", "xa_player", "p_model_scorer", "p_model_assist",
                "fair_odd_scorer", "fair_odd_assist", "edge_scorer", "edge_assist"):
        df.loc[excluded_mask, col] = np.nan

    return df.drop(columns=["_pid", "_in"])


def _render_predictions_editor(event_id: int, sub: pd.DataFrame,
                                home_name: str, away_name: str) -> None:
    """Tableau interactif `st.data_editor` :
       checkbox Inclure → recalcul live des shares xG/équipe."""
    if sub.empty:
        st.warning("Aucune prédiction joueur pour ce match.")
        return

    state_key = f"includes_{event_id}"
    default_state = _initial_inclusion_state(sub)
    if state_key not in st.session_state:
        st.session_state[state_key] = dict(default_state)

    # Bouton réinitialisation
    cols = st.columns([1, 1, 4])
    with cols[0]:
        if st.button("↩ Réinitialiser à BSD", key=f"reset_{event_id}",
                     help="Remet les inclusions par défaut (blessés/suspendus exclus)."):
            st.session_state[state_key] = dict(default_state)
            st.rerun()
    with cols[1]:
        market = st.radio("Marché", ["Buteur", "Passeur", "Les deux"],
                          horizontal=True, key=f"market_{event_id}")

    # State courant (peut différer du défaut si l'user a touché)
    state = st.session_state[state_key]
    # S'assurer que tous les pids du sub sont représentés
    for pid_int, default_val in default_state.items():
        state.setdefault(pid_int, default_val)

    included_pids = {int(pid) for pid, inc in state.items() if inc}
    recalc = _recalculate_shares(sub, included_pids)
    lineup_confirmed = bool(sub["lineup_confirmed"].dropna().iloc[0]) \
        if sub["lineup_confirmed"].notna().any() else False

    # Construction des lignes éditables
    rows = []
    for _, r in recalc.iterrows():
        pid = int(r["player_id"])
        avail = _safe_avail(r.get("availability"))
        emoji = _AVAIL_EMOJI.get(avail, "")
        # Nom (préfixé d'un ★ si titulaire et lineup confirmée — meilleur visuel
        # qu'un gras Markdown que st.data_editor n'interprète pas)
        nm_raw = r.get("player_name", "?")
        nm = "?" if (isinstance(nm_raw, float) and pd.isna(nm_raw)) else str(nm_raw)
        is_starter_val = r.get("is_starter")
        is_starter = (lineup_confirmed and bool(is_starter_val)
                      and not (isinstance(is_starter_val, float) and pd.isna(is_starter_val)))
        if is_starter:
            nm = f"★ {nm}"
        joueur = (f"{emoji} {nm}" if emoji else nm).strip()

        pos_raw = r.get("position")
        pos_str = "" if (pos_raw is None or (isinstance(pos_raw, float) and pd.isna(pos_raw))) \
                  else str(pos_raw)
        mins_val = r.get("minutes_expected")
        mins_int = int(float(mins_val)) if (mins_val is not None and not (
            isinstance(mins_val, float) and pd.isna(mins_val))) else 0

        common_pre = {
            "Inclure": bool(state.get(pid, True)),
            "Joueur": joueur,
            "Équipe": home_name if r.get("team_side") == "home" else away_name,
            "Pos": pos_str,
            "Min": mins_int,
            "Titu": "★" if is_starter else ("Sub" if lineup_confirmed else "—"),
        }
        if market in ("Buteur", "Les deux"):
            rows.append({
                "_pid": pid, **common_pre, "Marché": "⚽ Buteur",
                "p %": (round(float(r["p_model_scorer"]) * 100, 1)
                        if pd.notna(r.get("p_model_scorer")) else None),
                "Cote juste": (round(float(r["fair_odd_scorer"]), 2)
                               if pd.notna(r.get("fair_odd_scorer")) else None),
                "Cote Betclic": (round(float(r["betclic_odd_scorer"]), 2)
                                 if pd.notna(r.get("betclic_odd_scorer")) else None),
                "Edge %": (round(float(r["edge_scorer"]) * 100, 2)
                           if pd.notna(r.get("edge_scorer")) else None),
            })
        if market in ("Passeur", "Les deux"):
            rows.append({
                "_pid": pid, **common_pre, "Marché": "🅰 Passeur",
                "p %": (round(float(r["p_model_assist"]) * 100, 1)
                        if pd.notna(r.get("p_model_assist")) else None),
                "Cote juste": (round(float(r["fair_odd_assist"]), 2)
                               if pd.notna(r.get("fair_odd_assist")) else None),
                "Cote Betclic": (round(float(r["betclic_odd_assist"]), 2)
                                 if pd.notna(r.get("betclic_odd_assist")) else None),
                "Edge %": (round(float(r["edge_assist"]) * 100, 2)
                           if pd.notna(r.get("edge_assist")) else None),
            })

    if not rows:
        st.warning("Aucune prédiction joueur pour ce marché.")
        return

    df_edit = pd.DataFrame(rows).sort_values(by=["p %"], ascending=False, na_position="last")

    edited = st.data_editor(
        df_edit,
        column_config={
            "_pid": None,  # caché
            "Inclure": st.column_config.CheckboxColumn(
                "✓", help="Inclure ce joueur dans la distribution xG/xA",
                width="small"),
            "Joueur": st.column_config.TextColumn(width="medium"),
            "Pos": st.column_config.TextColumn(width="small"),
            "Min": st.column_config.NumberColumn(width="small"),
            "Titu": st.column_config.TextColumn(width="small"),
            "p %": st.column_config.NumberColumn("p %", format="%.1f"),
            "Cote juste": st.column_config.NumberColumn(format="%.2f"),
            "Cote Betclic": st.column_config.NumberColumn(format="%.2f"),
            "Edge %": st.column_config.NumberColumn(format="%+.2f"),
        },
        column_order=["Inclure", "Joueur", "Équipe", "Pos", "Min", "Titu",
                      "Marché", "p %", "Cote juste", "Cote Betclic", "Edge %"],
        hide_index=True,
        use_container_width=True,
        height=600,
        key=f"editor_{event_id}",
        disabled=["Joueur", "Équipe", "Pos", "Min", "Titu", "Marché",
                  "p %", "Cote juste", "Cote Betclic", "Edge %"],
    )

    # Détection des changements de checkbox → MAJ session_state + rerun.
    # En mode "Les deux", chaque player_id apparaît sur 2 lignes (buteur + passeur).
    # On groupe par pid : si AU MOINS UNE des lignes diffère de l'état actuel, on
    # adopte cette nouvelle valeur. La 2ᵉ ligne sera resynchronisée au rerun, ce
    # qui évite l'effet "toggle écrasé par l'autre ligne du même joueur".
    new_state = dict(state)
    changed = False
    for pid_e, group in edited.groupby("_pid"):
        pid_e = int(pid_e)
        old = bool(state.get(pid_e, True))
        new_vals = [bool(v) for v in group["Inclure"].tolist()]
        if all(v == old for v in new_vals):
            continue  # rien à faire pour ce pid
        # Au moins une ligne diffère : on prend la 1ʳᵉ qui diffère
        for v in new_vals:
            if v != old:
                new_state[pid_e] = v
                changed = True
                break
    if changed:
        st.session_state[state_key] = new_state
        st.rerun()

    # Stats résumées
    n_in = sum(1 for v in state.values() if v)
    n_total = len(state)
    n_blessed = sum(1 for _, r in sub.iterrows()
                    if _safe_avail(r.get("availability")) != "available")
    msg = f"📊 {n_in}/{n_total} joueurs inclus"
    if n_blessed:
        msg += f"  •  🤕 {n_blessed} indisponibles BSD"
    if not lineup_confirmed:
        msg += "  •  ⏳ Compos non confirmées (mins=90 partout)"
    else:
        msg += "  •  ✅ Compos confirmées"
    st.caption(msg)


def render_predictions_buteurs_page():
    st.header("🔮 Prédiction Buteurs — Détail par match")
    st.caption(
        "Liste des matchs du week-end avec prédictions disponibles. "
        "Sélectionne un match pour voir compositions, coachs, système de jeu, "
        "stats des équipes, head-to-head, blessés et tous les buteurs prédits."
    )

    df = load_forward_log_df()
    if df.empty:
        st.info(
            "Aucune prédiction encore loggée. Va sur **🎯 Test Edge Buteurs** "
            "et clique sur **Lancer prédictions maintenant**."
        )
        return

    # --- Toolbar : refresh prédictions + indicateur fraîcheur ---
    last_logged = df["logged_at"].max() if "logged_at" in df.columns else None
    tb1, tb2, tb3 = st.columns([1.2, 1.4, 2.4])
    with tb1:
        if st.button("🔄 Rafraîchir prédictions", key="predbut_refresh", type="primary"):
            with st.spinner("Pipeline en cours (1-3 min selon le nombre de matchs)..."):
                ok, log_txt = _run_predict_today(["--days", "2", "--refresh-squads"])
            if ok:
                st.success("Prédictions régénérées (squads BSD + overrides actualisés).")
            else:
                st.error("Échec du pipeline — vois les logs.")
            with st.expander("Logs"):
                st.code(log_txt[-4000:])
            load_forward_log_df.clear()
            _bsd_event_detail_cached.clear()
            st.rerun()
    with tb2:
        if last_logged is not None and pd.notna(last_logged):
            age_h = (pd.Timestamp.now(tz="UTC") - last_logged).total_seconds() / 3600
            stamp = last_logged.tz_convert("Europe/Paris").strftime("%a %d/%m %H:%M")
            color = "🟢" if age_h < 6 else ("🟡" if age_h < 24 else "🔴")
            st.caption(f"{color} Dernière mise à jour : **{stamp}** (Paris) — il y a {age_h:.1f}h")
        else:
            st.caption("⚪ Pas de timestamp disponible")

    # Liste matchs (groupby event_id) avec stats résumées
    grouped = (df.groupby(["event_id", "league_slug", "match"], dropna=False)
               .agg(kickoff=("kickoff", "first"),
                    n_players=("player_id", "nunique"),
                    n_with_book=("betclic_odd_scorer",
                                 lambda s: int(s.notna().sum())))
               .reset_index()
               .sort_values("kickoff"))

    grouped["Ligue"] = grouped["league_slug"].map(lambda s: LEAGUE_LABELS.get(s, s))
    grouped["Kickoff (Paris)"] = grouped["kickoff"].dt.tz_convert("Europe/Paris").dt.strftime(
        "%a %d/%m %H:%M")

    # Sélection via query param OR session_state pour permettre URL partageable
    qp = st.query_params
    qp_eid = qp.get("event_id")
    if qp_eid:
        try:
            current_eid = int(qp_eid)
        except (TypeError, ValueError):
            current_eid = None
    else:
        current_eid = st.session_state.get("predbut_selected_event_id")

    # Sélecteur match
    match_labels = {
        int(r.event_id): f"{r['Ligue']} · {r['Kickoff (Paris)']} — {r['match']} "
                         f"({int(r['n_players'])} joueurs, {int(r['n_with_book'])} cotes)"
        for _, r in grouped.iterrows()
    }
    eid_list = list(match_labels.keys())

    if current_eid not in eid_list:
        current_eid = eid_list[0] if eid_list else None

    selected = st.selectbox(
        "📅 Choisir un match",
        eid_list,
        format_func=lambda eid: match_labels.get(eid, str(eid)),
        index=eid_list.index(current_eid) if current_eid in eid_list else 0,
        key="predbut_selectbox",
    )

    # Synchronise l'URL avec la sélection (dès le 1er affichage → URL partageable)
    qp_current = st.query_params.get("event_id")
    if selected is not None and str(selected) != qp_current:
        st.session_state["predbut_selected_event_id"] = selected
        st.query_params["page"] = "predictions_buteurs"
        st.query_params["event_id"] = str(selected)

    # Vue d'ensemble compacte sous le sélecteur
    with st.expander(f"📋 Vue d'ensemble : {len(grouped)} matchs prédits"):
        show = grouped[["Ligue", "Kickoff (Paris)", "match", "n_players", "n_with_book"]].rename(
            columns={"match": "Match", "n_players": "Joueurs prédits",
                     "n_with_book": "Cotes Betclic"})
        st.dataframe(show, use_container_width=True, hide_index=True)

    st.markdown("---")
    if selected is not None:
        _render_match_detail(int(selected), df)
