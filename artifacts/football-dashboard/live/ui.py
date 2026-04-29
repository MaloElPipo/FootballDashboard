"""Pages Streamlit pour le pipeline forward-test live.

- `render_tracking_page()`            : historique enrichi du forward log + métriques perf
- `render_predictions_buteurs_page()` : liste matchs prévus + drill-down détail riche (BSD)
  + bouton 1-clic "Ajouter au tracking" depuis chaque match (vers bets_tracker.json)
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
sys.path.insert(0, str(DASH_ROOT))

from preview_player_odds._3_model_proxy import apply_anti_poisson_calibration  # noqa: E402
from live.statshub_helpers import get_predicted_lineup_for_bsd_event  # noqa: E402
from live.forward_bets import (  # noqa: E402
    add_forward_bet,
    clear_all_forward_bets,
    delete_forward_bet,
    load_forward_bets,
    update_forward_bet_result,
)
from live.leagues_config import (  # noqa: E402
    LEAGUES,
    REGION_LABELS,
    REGION_ORDER,
    group_by_region,
    league_labels_dict,
)


def _anti_poisson_calibrate_array(odds: np.ndarray) -> np.ndarray:
    """Version vectorisée pour Streamlit (mêmes formule que le moteur)."""
    arr = np.asarray(odds, dtype=float)
    out = np.full_like(arr, np.nan)
    mask = np.isfinite(arr) & (arr > 1.0)
    if mask.any():
        b = arr[mask]
        shrink = np.minimum((b - 1.0) / 100.0, 0.75)
        shrink = np.where(shrink < 0, 0.0, shrink)
        out[mask] = b * (1.0 - shrink)
    # Recopie tel quel les cotes <= 1.0 (rien à compresser)
    keep = np.isfinite(arr) & (arr <= 1.0)
    out[keep] = arr[keep]
    return out

# LEAGUE_LABELS est désormais auto-généré depuis le registre central
# `live.leagues_config` (T017) ; on conserve un override pour Premier League
# afin de garder le drapeau d'Angleterre (régional) plutôt que celui de l'UK.
LEAGUE_LABELS: dict[str, str] = {
    **league_labels_dict(),
    "premier_league": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League",
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
    """Lance le pipeline daily V2 (Top 5 + UCL/UEL + ~25 ligues secondaires)
    en sous-processus, capture stdout/stderr.

    On pointe sur `predict_today_v2.py` (pas v1) pour que le bouton
    "Rafraîchir prédictions" couvre TOUTES les compétitions actives du
    registre central — sinon les matchs hors Top 5 (ex: PSG-Bayern UCL)
    ne sont jamais re-pricés et leurs xG restent figés sur la dernière
    valeur loggée. v2 réutilise STRICTEMENT le moteur Buteurs Maison 4.1
    via `import live.predict_today as pt` (zéro modification du moteur).
    """
    cmd = [sys.executable, str(ROOT / "predict_today_v2.py")] + args_extra
    try:
        res = subprocess.run(
            cmd, cwd=DASH_ROOT, capture_output=True, text=True, timeout=600
        )
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        return res.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT après 10 minutes"


def _invalidate_odds_router_cache() -> int:
    """Supprime le cache disque du router odds (TTL 30 min) pour forcer
    un re-fetch frais de toutes les sources (BSD compareOdds / TheOddsAPI
    Pinnacle+Bet365 / Betclic). Retourne le nombre d'entrées purgées
    (0 si pas de cache existant). Appelé avant chaque clic explicite sur
    le bouton "Rafraîchir prédictions" — sans cette purge, l'utilisateur
    voit les anciennes cotes pendant ≤ 30 min même après avoir rechargé."""
    cache_file = ROOT / "data" / "odds_router_cache.json"
    if not cache_file.exists():
        return 0
    try:
        with cache_file.open() as f:
            n = len(json.load(f) or {})
    except (json.JSONDecodeError, OSError):
        n = 0
    try:
        cache_file.unlink()
    except OSError:
        pass
    return n


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

# Page : Tracking Test Edge Buteurs (bets validés via le bouton 1-clic)
# ---------------------------------------------------------------------------
def _safe_int(v):
    """Cast tolérant : retourne None si NaN, str invalide, etc."""
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _auto_resolve_status_from_log(bets: list[dict], log_df: pd.DataFrame) -> list[dict]:
    """Si un bet est encore 'pending' mais que le forward_log a un outcome
    pour ce (event_id, player_id), on le résout automatiquement en lisant
    la colonne outcome correspondant au market du bet (outcome_scored pour
    Buteur, outcome_assisted pour Passeur). Le forward_log a UNE row par
    (event_id, player_id) avec scorer/assist côte à côte, donc cette clé
    suffit ; le market discrimine la colonne d'outcome.
    Ne touche pas aux bets déjà résolus manuellement (won/lost/void)."""
    if log_df.empty:
        return bets
    # Indexation défensive : skip silencieusement les rows mal formées
    log_keyed: dict = {}
    for _, r in log_df.iterrows():
        ev_id = _safe_int(r.get("event_id"))
        pid = _safe_int(r.get("player_id"))
        if ev_id is None or pid is None:
            continue
        log_keyed[(ev_id, pid)] = r
    changed = False
    for b in bets:
        if b.get("result") != "pending":
            continue
        ev_id = _safe_int(b.get("event_id"))
        pid = _safe_int(b.get("player_id"))
        if ev_id is None or pid is None:
            continue
        ref = log_keyed.get((ev_id, pid))
        if ref is None:
            continue
        outcome_col = "outcome_scored" if b.get("market") == "Buteur" else "outcome_assisted"
        outcome = ref.get(outcome_col)
        if pd.isna(outcome):
            continue  # match pas encore enrichi
        new_result = "won" if bool(outcome) else "lost"
        b["result"] = new_result
        stake = float(b.get("stake") or 0)
        odd = float(b.get("betclic_odd") or 0)
        b["profit_units"] = round(
            stake * (odd - 1) if new_result == "won" else -stake, 2
        )
        changed = True
    if changed:
        from live.forward_bets import save_forward_bets
        save_forward_bets(bets)
    return bets


def render_tracking_page():
    st.header("📈 Tracking Test Edge Buteurs")
    st.caption(
        "Tous les bets validés depuis **🔮 Prédiction Buteurs** (bouton "
        "« Ajouter au tracking ») arrivent ici. Les résultats sont résolus "
        "automatiquement quand le match est terminé et enrichi."
    )

    bets = load_forward_bets()

    # Auto-résolution depuis le forward log enrichi
    log_df = load_forward_log_df()
    if bets:
        bets = _auto_resolve_status_from_log(bets, log_df)

    # Toolbar : reset
    tb1, _ = st.columns([1.4, 4])
    with tb1:
        if st.button("🗑 Tout effacer", help="Vide complètement le tracking",
                     key="forward_clear_btn"):
            st.session_state["_forward_clear_confirm"] = True
        if st.session_state.get("_forward_clear_confirm"):
            st.warning(
                f"Tu es sûr ? Cela supprimera **{len(bets)}** bet(s) trackés "
                "(action irréversible).",
                icon="⚠️",
            )
            cc1, cc2 = st.columns(2)
            with cc1:
                if st.button("Oui, tout effacer", key="forward_clear_yes",
                             type="primary"):
                    clear_all_forward_bets()
                    st.session_state["_forward_clear_confirm"] = False
                    st.success("Tracking vidé.")
                    st.rerun()
            with cc2:
                if st.button("Annuler", key="forward_clear_no"):
                    st.session_state["_forward_clear_confirm"] = False
                    st.rerun()

    if not bets:
        st.info(
            "Aucun bet tracké pour l'instant. Va sur **🔮 Prédiction Buteurs**, "
            "sélectionne un match, et utilise le bouton **« ➕ Ajouter au tracking »** "
            "sous le tableau des prédictions pour commencer le forward test."
        )
        return

    # KPIs globaux
    df_b = pd.DataFrame(bets)
    n_total = len(df_b)
    n_pending = int((df_b["result"] == "pending").sum())
    n_won = int((df_b["result"] == "won").sum())
    n_lost = int((df_b["result"] == "lost").sum())
    n_void = int((df_b["result"] == "void").sum())
    n_settled = n_won + n_lost  # void exclu du ROI
    stake_total = float(df_b["stake"].sum())
    profit_total = float(df_b["profit_units"].fillna(0).sum())
    stake_settled = float(df_b[df_b["result"].isin(["won", "lost"])]["stake"].sum())
    roi_pct = (profit_total / stake_settled * 100) if stake_settled > 0 else 0.0
    hit_rate = (n_won / n_settled * 100) if n_settled > 0 else 0.0
    edge_avg = float(df_b["edge_pct"].mean()) if n_total > 0 else 0.0

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Bets trackés", n_total, delta=f"{n_pending} en attente")
    k2.metric("Mise totale", f"{stake_total:.1f} u")
    k3.metric("P/L réalisé", f"{profit_total:+.2f} u",
              delta=f"{roi_pct:+.1f}% ROI" if n_settled else None)
    k4.metric("Hit rate", f"{hit_rate:.1f}%" if n_settled else "—",
              delta=f"{n_won}W / {n_lost}L" if n_settled else None)
    k5.metric("Edge moyen", f"{edge_avg:+.1f}%")

    if n_void:
        st.caption(f"({n_void} bet(s) void exclus du calcul ROI/hit rate)")

    st.markdown("---")
    st.markdown("### 📋 Détail des bets trackés")

    # Construction du tableau d'affichage
    def _kickoff_str(s):
        if not s or pd.isna(s):
            return "—"
        try:
            ts = pd.to_datetime(s, utc=True).tz_convert("Europe/Paris")
            return ts.strftime("%a %d/%m %H:%M")
        except Exception:
            return str(s)[:16]

    def _result_label(r):
        return {
            "pending": "⏳ En attente",
            "won": "✅ Gagné",
            "lost": "❌ Perdu",
            "void": "↩ Annulé",
        }.get(r, r)

    show_rows = []
    for b in sorted(bets, key=lambda x: x.get("added_at", ""), reverse=True):
        show_rows.append({
            "id": b["id"],
            "Ajouté": (b.get("added_at") or "")[:16].replace("T", " "),
            "Kickoff": _kickoff_str(b.get("kickoff")),
            "Ligue": b.get("league_name") or b.get("league_slug") or "—",
            "Match": b.get("match", "—"),
            "Pick": f"{b['player_name']} ({b['market']})",
            "p %": (round(b["p_model"] * 100, 1)
                    if b.get("p_model") is not None else None),
            "Cote juste": b.get("fair_odd"),
            "Cote prise": b.get("betclic_odd"),
            "Edge %": b.get("edge_pct"),
            "Mise": b.get("stake"),
            "Statut": _result_label(b.get("result", "pending")),
            "P/L u": b.get("profit_units"),
        })
    df_show = pd.DataFrame(show_rows)

    st.dataframe(
        df_show.drop(columns=["id"]),
        use_container_width=True,
        hide_index=True,
        height=min(620, 80 + 36 * len(df_show)),
        column_config={
            "p %": st.column_config.NumberColumn("p %", format="%.1f"),
            "Cote juste": st.column_config.NumberColumn("Cote juste", format="%.2f"),
            "Cote prise": st.column_config.NumberColumn("Cote prise", format="%.2f"),
            "Edge %": st.column_config.NumberColumn("Edge %", format="%+.2f"),
            "Mise": st.column_config.NumberColumn("Mise", format="%.2f"),
            "P/L u": st.column_config.NumberColumn("P/L u", format="%+.2f"),
        },
    )

    # Actions par bet : MAJ statut manuel + suppression
    st.markdown("---")
    st.markdown("### ⚙️ Actions sur un bet")
    st.caption(
        "Forcer un statut manuellement (utile si le résultat du match n'a pas "
        "encore été enrichi automatiquement) ou supprimer un bet."
    )

    bet_options = {
        f"#{b['id']} · {b['player_name']} ({b['market']}) · {b['match']}": b["id"]
        for b in sorted(bets, key=lambda x: x.get("added_at", ""), reverse=True)
    }
    ac1, ac2, ac3, ac4 = st.columns([3, 1.3, 1.3, 1.3])
    with ac1:
        sel_label = st.selectbox(
            "Bet à modifier",
            options=list(bet_options.keys()),
            key="forward_action_pick",
        )
        sel_bet_id = bet_options[sel_label]
    with ac2:
        new_status = st.selectbox(
            "Forcer statut",
            options=["pending", "won", "lost", "void"],
            format_func=_result_label,
            key=f"forward_status_{sel_bet_id}",
        )
    with ac3:
        st.write("")
        if st.button("Mettre à jour", key=f"forward_update_{sel_bet_id}",
                     use_container_width=True):
            update_forward_bet_result(sel_bet_id, new_status)
            st.success(f"Bet #{sel_bet_id} → {_result_label(new_status)}")
            st.rerun()
    with ac4:
        st.write("")
        if st.button("🗑 Supprimer", key=f"forward_delete_{sel_bet_id}",
                     use_container_width=True):
            delete_forward_bet(sel_bet_id)
            st.success(f"Bet #{sel_bet_id} supprimé")
            st.rerun()


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


def _render_statshub_lineup_column(players: list[dict], label: str) -> None:
    """Affiche une colonne de joueurs StatsHub (titulaires + remplaçants)."""
    starters = [p for p in players if isinstance(p, dict) and p.get("predictionType") in (None, "predicted") and not p.get("isSubstitute")]
    subs = [p for p in players if isinstance(p, dict) and p.get("isSubstitute")]
    # Fallback : la plupart des payloads StatsHub mettent tout dans `data`,
    # le titulaire vs sub est implicite (les 11 premiers = titulaires)
    if not subs and len(players) > 11:
        starters = players[:11]
        subs = players[11:]
    elif not starters:
        starters = players[:11]

    st.markdown(f"### {label}")
    if starters:
        st.markdown("**Onze probable**")
        for p in starters:
            if not isinstance(p, dict):
                continue
            name = p.get("name") or "?"
            pos = p.get("position") or ""
            num = p.get("jerseyNo") or ""
            num_s = f"#{num} " if num else ""
            pos_s = f" · {pos}" if pos else ""
            st.markdown(f"- {num_s}{name}{pos_s}")
    if subs:
        with st.expander(f"🪑 Remplaçants probables ({len(subs)})"):
            for p in subs:
                if not isinstance(p, dict):
                    continue
                name = p.get("name") or "?"
                pos = p.get("position") or ""
                num = p.get("jerseyNo") or ""
                num_s = f"#{num} " if num else ""
                pos_s = f" · {pos}" if pos else ""
                st.markdown(f"- {num_s}{name}{pos_s}")


def _render_statshub_predicted_lineup(head, home_name: str, away_name: str) -> None:
    """Affiche la compo prédite StatsHub si dispo (complément à BSD).

    Silencieux et non-bloquant: si StatsHub indisponible ou match non trouvé,
    on n'affiche rien (zéro impact sur l'UI existante).
    """
    try:
        bsd_event_id = int(head.get("event_id"))
    except (TypeError, ValueError, KeyError):
        return

    # Convertit kickoff (Timestamp pandas) en unix ts si dispo
    kickoff_ts = None
    try:
        ko = head.get("kickoff")
        if ko is not None and pd.notna(ko):
            kickoff_ts = int(ko.timestamp())
    except Exception:
        kickoff_ts = None

    league_slug = head.get("league_slug")

    try:
        result = get_predicted_lineup_for_bsd_event(
            bsd_event_id=bsd_event_id,
            home_team=home_name,
            away_team=away_name,
            kickoff_ts=kickoff_ts,
            league_slug=league_slug,
        )
    except Exception:
        return  # silent fail

    if not result or (not result.get("home") and not result.get("away")):
        return

    st.markdown("---")
    score = result.get("match_score", 0.0)
    score_pct = int(round(score * 100))
    with st.expander(
        f"🔮 Compo prédite (StatsHub) — confiance match {score_pct}%",
        expanded=False,
    ):
        st.caption(
            "Source complémentaire : StatsHub.com · "
            "Affichée à côté de BSD pour comparaison. "
            "Le moteur Buteurs Maison 4.1 ne s'appuie PAS sur cette source."
        )
        cl, cr = st.columns(2)
        with cl:
            _render_statshub_lineup_column(result.get("home", []), f"🏠 {home_name}")
        with cr:
            _render_statshub_lineup_column(result.get("away", []), f"🛫 {away_name}")


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

    # === [T023 chantier 2] Board de composition manuelle ===
    # Composant terrain interactif (6 schémas, pastilles cotes Buteur, panneau
    # droit cliquable, slider minutes, Save/Reset). Au chantier 2 le composant
    # affiche un fixture hardcodé Atlético-Arsenal UCL pour valider l'UI ; au
    # chantier 3 on branche les vraies données du forward log de l'event courant.
    with st.expander("🥅 [T023 c2] Composition manuelle (fixture Atlético-Arsenal)", expanded=True):
        from live.components.lineup_pitch import render_lineup_pitch

        result = render_lineup_pitch(
            event_data={
                "home_team": home_name,
                "away_team": away_name,
                "kickoff": kickoff_str,
                "league": league_label,
            },
            key=f"lineup_pitch_test_{event_id}",
        )
        if result is not None and isinstance(result, dict) and result.get("action") == "save":
            st.success(
                f"✓ Composition sauvegardée côté React (chantier 4 = persistance JSON). "
                f"Schéma : {result.get('payload', {}).get('formation')} · "
                f"Side : {result.get('payload', {}).get('side')}"
            )
        with st.expander("Debug : dernier message React → Python", expanded=False):
            st.json(result if result is not None else {"_": "(aucun message)"})

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

    # === Compo prédite StatsHub (complément, source externe) ===
    _render_statshub_predicted_lineup(head, home_name, away_name)

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
    """Par défaut, on coche le **onze probable** :
      - Si la compo BSD est confirmée pour le side → titulaires officiels cochés,
        subs décochés (`is_starter` du log).
      - Sinon, fallback heuristique sur `is_presumed_starter` (top-11 par
        start_rate, T008). Pour rétro-compatibilité avec les anciennes lignes
        de log (pas de champ `is_presumed_starter`), on coche tous les
        disponibles → comportement T007 d'avant.
    Joueurs blessés/suspendus → toujours décochés."""
    state: dict[int, bool] = {}
    has_presumed = "is_presumed_starter" in sub.columns
    for _, r in sub.iterrows():
        pid = int(r["player_id"])
        avail = _safe_avail(r.get("availability"))
        excluded_val = r.get("excluded", False)
        is_excluded_log = bool(excluded_val) and not (
            isinstance(excluded_val, float) and pd.isna(excluded_val)
        )
        if avail != "available" or is_excluded_log:
            state[pid] = False
            continue
        # Compo confirmée pour ce side ? → on suit `is_starter` officiel
        side = r.get("team_side")
        side_conf = r.get(f"{side}_lineup_confirmed") if side in ("home", "away") else None
        if bool(side_conf):
            v = r.get("is_starter")
            state[pid] = bool(v) and not (isinstance(v, float) and pd.isna(v))
            continue
        # Compo non confirmée : on prend la compo probable (top-11 start_rate)
        if has_presumed:
            v = r.get("is_presumed_starter")
            if v is None or (isinstance(v, float) and pd.isna(v)):
                state[pid] = True  # joueur sans info → garder coché par défaut
            else:
                state[pid] = bool(v)
        else:
            state[pid] = True  # rétro-compat : pre-T008
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

        # T009 — Conversion 90' théorique pour le calcul des cotes (garantie
        # buteur FR : la cote bookmaker valide aussi pour un joueur entré en
        # cours de match → on price à 90' théorique pour rester comparable).
        # `xg_cal` reste l'xG attendu sur les minutes prévues (utilisé pour
        # la normalisation team), MAIS la cote vient de xg_for_90 = xg_cal × 90/mins.
        mins_safe = sub_team["minutes_expected"].fillna(0).astype(float).clip(lower=1.0)
        xg_for_90 = xg_cal * 90.0 / mins_safe.values
        xa_for_90 = xa_cal * 90.0 / mins_safe.values

        # Cotes brutes Poisson, puis calibration anti-Poisson "Buteurs Maison 4.1"
        p_scorer_brut = 1.0 - np.exp(-xg_for_90)
        p_assist_brut = 1.0 - np.exp(-xa_for_90)
        odd_scorer_brut = np.where(p_scorer_brut > 0, 1.0 / p_scorer_brut, np.nan)
        odd_assist_brut = np.where(p_assist_brut > 0, 1.0 / p_assist_brut, np.nan)
        odd_scorer = _anti_poisson_calibrate_array(odd_scorer_brut)
        odd_assist = _anti_poisson_calibrate_array(odd_assist_brut)
        # p_model recohérencé avec cote calibrée (edge = p × cote_book − 1)
        p_scorer = np.where(np.isfinite(odd_scorer) & (odd_scorer > 0),
                            1.0 / odd_scorer, 0.0)
        p_assist = np.where(np.isfinite(odd_assist) & (odd_assist > 0),
                            1.0 / odd_assist, 0.0)

        df.loc[mask, "xg_player"] = xg_cal.values
        df.loc[mask, "xa_player"] = xa_cal.values
        df.loc[mask, "p_model_scorer"] = p_scorer
        df.loc[mask, "p_model_assist"] = p_assist
        df.loc[mask, "fair_odd_scorer"] = odd_scorer
        df.loc[mask, "fair_odd_assist"] = odd_assist

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
    # Compte les inclusions différentes du défaut. Si aucune modif → on affiche
    # les cotes telles que loggées par le moteur Buteurs Maison 4.1 (pool complet
    # des joueurs avec minutes_expected > 0). Si l'user a touché aux checkboxes
    # → on bascule en mode "what-if" et on redistribue λ équipe sur les cochés.
    # Sans ce garde, l'UI redistribuait par défaut λ sur seulement les 11
    # présumés titulaires, gonflant artificiellement la part des starters
    # (ex: Kane affiché 1.90 au lieu du 2.10 calculé par le moteur).
    n_user_changes = sum(
        1 for pid_d, default_val in default_state.items()
        if bool(state.get(pid_d, default_val)) != bool(default_val)
    )
    if n_user_changes > 0:
        recalc = _recalculate_shares(sub, included_pids)
    else:
        recalc = sub.copy()
    lineup_confirmed = bool(sub["lineup_confirmed"].dropna().iloc[0]) \
        if sub["lineup_confirmed"].notna().any() else False
    home_conf = bool(sub["home_lineup_confirmed"].dropna().iloc[0]) \
        if "home_lineup_confirmed" in sub.columns and sub["home_lineup_confirmed"].notna().any() else False
    away_conf = bool(sub["away_lineup_confirmed"].dropna().iloc[0]) \
        if "away_lineup_confirmed" in sub.columns and sub["away_lineup_confirmed"].notna().any() else False

    # T008 — badge confiance compo probable. Affiché dès qu'un côté n'est pas
    # confirmé par BSD (sinon l'info est inutile : on a la vraie compo).
    def _conf_pct(col: str) -> str | None:
        if col not in sub.columns or sub[col].dropna().empty:
            return None
        return f"{float(sub[col].dropna().iloc[0]) * 100:.0f}%"
    home_cp = _conf_pct("lineup_confidence_home") if not home_conf else None
    away_cp = _conf_pct("lineup_confidence_away") if not away_conf else None
    badges = []
    if home_cp is not None:
        badges.append(f"**{home_name}** : compo probable (confiance {home_cp})")
    if away_cp is not None:
        badges.append(f"**{away_name}** : compo probable (confiance {away_cp})")
    if badges:
        st.caption(" · ".join(badges) +
                   "  \n*100% = onze type qui ne change jamais. Les 11 cochés par "
                   "défaut sont les plus titularisés sur la saison.*")

    # Construction des lignes éditables
    rows = []
    for _, r in recalc.iterrows():
        pid = int(r["player_id"])
        avail = _safe_avail(r.get("availability"))
        emoji = _AVAIL_EMOJI.get(avail, "")
        # Nom : ★ si titulaire confirmé OU titulaire présumé (compo probable)
        nm_raw = r.get("player_name", "?")
        nm = "?" if (isinstance(nm_raw, float) and pd.isna(nm_raw)) else str(nm_raw)
        side = r.get("team_side")
        side_conf = (home_conf if side == "home" else away_conf) if side in ("home", "away") else False
        if side_conf:
            v = r.get("is_starter")
            is_starter = bool(v) and not (isinstance(v, float) and pd.isna(v))
            titu_label = "★" if is_starter else "Sub"
        else:
            v = r.get("is_presumed_starter") if "is_presumed_starter" in recalc.columns else None
            is_starter = bool(v) and not (isinstance(v, float) and pd.isna(v))
            titu_label = "★?" if is_starter else "Sub?"
        if is_starter:
            nm = f"★ {nm}"
        joueur = (f"{emoji} {nm}" if emoji else nm).strip()

        pos_raw = r.get("position")
        pos_str = "" if (pos_raw is None or (isinstance(pos_raw, float) and pd.isna(pos_raw))) \
                  else str(pos_raw)
        mins_val = r.get("minutes_expected")
        mins_int = int(float(mins_val)) if (mins_val is not None and not (
            isinstance(mins_val, float) and pd.isna(mins_val))) else 0

        # T010 — expected shots & SoT (descriptifs, communs aux 2 marchés)
        xshots = r.get("expected_shots")
        xsot = r.get("expected_shots_on_target")
        common_pre = {
            "Inclure": bool(state.get(pid, True)),
            "Joueur": joueur,
            "Équipe": home_name if r.get("team_side") == "home" else away_name,
            "Pos": pos_str,
            "Min": mins_int,
            "Titu": titu_label,
            "xT": (round(float(xshots), 2) if pd.notna(xshots) else None),
            "xT cad.": (round(float(xsot), 2) if pd.notna(xsot) else None),
        }
        if market in ("Buteur", "Les deux"):
            rows.append({
                "_pid": pid, **common_pre, "_marche": "Buteur",
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
                "_pid": pid, **common_pre, "_marche": "Passeur",
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
            "_marche": None,  # caché — utilisé en interne pour tracking
            "Inclure": st.column_config.CheckboxColumn(
                "✓", help="Inclure ce joueur dans la distribution xG/xA",
                width="small"),
            "Joueur": st.column_config.TextColumn(width="medium"),
            "Pos": st.column_config.TextColumn(width="small"),
            "Min": st.column_config.NumberColumn(width="small"),
            "Titu": st.column_config.TextColumn(width="small"),
            "p %": st.column_config.NumberColumn("p %", format="%.1f"),
            "Cote juste": st.column_config.NumberColumn(
                "Cote juste", format="%.2f",
                help="Cote théorique du modèle, calculée à 90' théorique de "
                     "temps de jeu — best case correspondant à la garantie "
                     "buteur FR (Betclic & co valident le bet même si le "
                     "joueur entre en cours de match). Directement comparable "
                     "à la cote bookmaker."),
            "xT": st.column_config.NumberColumn(
                "xT", format="%.2f", width="small",
                help="Tirs attendus dans CE match = shots/90 carrière "
                     "× minutes attendues / 90. Stat descriptive (pas une "
                     "cote) — un sub à 25 min aura un xT proportionnellement "
                     "plus faible qu'un titulaire à 85 min même rate."),
            "xT cad.": st.column_config.NumberColumn(
                "xT cad.", format="%.2f", width="small",
                help="Tirs cadrés attendus = shots_on_target/90 × minutes "
                     "attendues / 90. Idéalement xT cad. ≈ 30-40% de xT "
                     "pour un attaquant Top 5."),
            "Cote Betclic": st.column_config.NumberColumn(format="%.2f"),
            "Edge %": st.column_config.NumberColumn(format="%+.2f"),
        },
        column_order=["Inclure", "Joueur", "Équipe", "Pos", "Min", "Titu",
                      "p %", "Cote juste",
                      "Cote Betclic", "Edge %", "xT", "xT cad."],
        hide_index=True,
        use_container_width=True,
        height=600,
        key=f"editor_{event_id}",
        disabled=["Joueur", "Équipe", "Pos", "Min", "Titu",
                  "p %", "Cote juste", "Cote Betclic",
                  "Edge %", "xT", "xT cad."],
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
    # Bandeau "what-if" : déclenché dès que l'user a touché aux checkboxes
    # (`n_user_changes` est calculé plus haut, sert aussi à activer le recalcul
    # `_recalculate_shares`). Sinon on affiche les cotes telles que loggées par
    # le moteur Buteurs Maison 4.1.
    if n_user_changes > 0:
        st.info(
            f"💡 Vous avez modifié {n_user_changes} inclusion(s) par rapport au "
            "onze probable. La colonne **Cote juste** est recalculée live à "
            "partir des joueurs cochés (mode what-if).",
            icon="ℹ️",
        )
    msg = f"📊 {n_in}/{n_total} joueurs inclus"
    if n_blessed:
        msg += f"  •  🤕 {n_blessed} indisponibles BSD"
    if not lineup_confirmed:
        msg += "  •  ⏳ Compos non confirmées (mins=90 partout)"
    else:
        msg += "  •  ✅ Compos confirmées"
    st.caption(msg)

    # ── Bloc "Ajouter au tracking forward test" ──
    # T014 — bouton 1-clic pour pousser un pick à edge positif vers
    # bets_tracker.json (consommé par la page "📊 Suivi des paris").
    st.markdown("---")
    st.markdown("### 💰 Ajouter au tracking forward test")

    candidates = df_edit[
        df_edit["Edge %"].notna()
        & (df_edit["Edge %"] > 0)
        & df_edit["Cote Betclic"].notna()
    ].sort_values("Edge %", ascending=False).reset_index(drop=True)

    if candidates.empty:
        st.caption(
            "Aucun edge positif avec cote Betclic disponible pour ce match — "
            "rien à tracker pour l'instant."
        )
    else:
        def _label_for(row) -> str:
            joueur = str(row["Joueur"]).replace("★ ", "").strip()
            marche = row["_marche"]
            return (
                f"{joueur}  ·  {marche}  ·  cote {row['Cote Betclic']:.2f}  "
                f"·  edge {row['Edge %']:+.1f}%"
            )

        bc1, bc2, bc3 = st.columns([3, 1, 1.2])
        with bc1:
            sel_idx = st.selectbox(
                "Pick à tracker",
                options=list(range(len(candidates))),
                format_func=lambda i: _label_for(candidates.iloc[i]),
                key=f"track_pick_{event_id}",
            )
        with bc2:
            stake = st.number_input(
                "Mise (u)",
                min_value=0.1, max_value=100.0, value=1.0, step=0.5,
                key=f"track_stake_{event_id}",
            )
        with bc3:
            st.write("")  # spacer pour aligner le bouton verticalement
            do_add = st.button(
                "➕ Ajouter au tracking",
                key=f"track_add_{event_id}",
                type="primary",
                use_container_width=True,
            )

        if do_add:
            row = candidates.iloc[sel_idx]
            joueur_clean = str(row["Joueur"]).replace("★ ", "").strip()
            marche_clean = row["_marche"]  # "Buteur" ou "Passeur"
            match_str = f"{home_name} - {away_name}"
            cote_book = float(row["Cote Betclic"])
            cote_juste = (float(row["Cote juste"])
                          if pd.notna(row.get("Cote juste")) else None)
            edge_pct = float(row["Edge %"])
            pid = int(row["_pid"])

            # Lookup contexte enrichi dans le forward log (sub) via pid
            ref_row = sub[sub["player_id"] == pid].iloc[0] if not sub[sub["player_id"] == pid].empty else None
            league_slug = ref_row.get("league_slug") if ref_row is not None else None
            league_name = ref_row.get("league_name") if ref_row is not None else None
            kickoff_iso = (ref_row.get("kickoff").isoformat()
                           if ref_row is not None and pd.notna(ref_row.get("kickoff"))
                           else None)
            p_model = (float(ref_row["p_model_scorer"])
                       if marche_clean == "Buteur" and ref_row is not None and pd.notna(ref_row.get("p_model_scorer"))
                       else (float(ref_row["p_model_assist"])
                             if marche_clean == "Passeur" and ref_row is not None and pd.notna(ref_row.get("p_model_assist"))
                             else None))

            try:
                bet = add_forward_bet(
                    event_id=event_id,
                    match=match_str,
                    league_slug=league_slug,
                    league_name=league_name,
                    kickoff=kickoff_iso,
                    player_id=pid,
                    player_name=joueur_clean,
                    market=marche_clean,
                    p_model=p_model,
                    fair_odd=cote_juste,
                    betclic_odd=cote_book,
                    edge_pct=edge_pct,
                    stake=float(stake),
                )
                st.success(
                    f"Bet #{bet['id']} ajouté : **{joueur_clean}** "
                    f"({marche_clean}) @ {cote_book:.2f} — mise {float(stake):.2f}u. "
                    f"Visible dans **📈 Tracking Test Edge Buteurs**."
                )
            except Exception as e:
                st.error(f"Erreur lors de l'ajout : {e}")


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
            "Aucune prédiction encore loggée. Clique sur **🔄 Rafraîchir prédictions** "
            "ci-dessous pour lancer le pipeline."
        )
        return

    # --- Toolbar : refresh prédictions + indicateur fraîcheur ---
    last_logged = df["logged_at"].max() if "logged_at" in df.columns else None
    tb1, tb2, tb3 = st.columns([1.2, 1.4, 2.4])
    with tb1:
        if st.button("🔄 Rafraîchir prédictions", key="predbut_refresh", type="primary",
                     help="Re-fetch des cotes (Pinnacle/Bet365/Betclic) + re-calcul "
                          "des xG sur Top 5 + UCL/UEL + ~25 ligues secondaires. "
                          "Le cache odds 30 min est purgé pour garantir des cotes fraîches."):
            n_purged = _invalidate_odds_router_cache()
            with st.spinner(
                f"Cache odds purgé ({n_purged} entrées). Pipeline V2 en cours "
                "(2-5 min selon le nombre de matchs)..."
            ):
                ok, log_txt = _run_predict_today(["--days", "2", "--refresh-squads"])
            if ok:
                st.success(
                    "Prédictions régénérées sur toutes les ligues actives "
                    "(squads BSD + cotes fraîches + xG re-calculés)."
                )
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

    # Filtre matchs futurs uniquement : une fois le coup d'envoi passé,
    # les cotes Betclic ne sont plus actualisées et les prédictions perdent
    # tout intérêt opérationnel. On masque donc les matchs déjà commencés.
    now_utc = pd.Timestamp.now(tz="UTC")
    n_total = len(grouped)
    grouped = grouped[grouped["kickoff"].notna() & (grouped["kickoff"] > now_utc)].copy()
    n_hidden = n_total - len(grouped)

    grouped["Ligue"] = grouped["league_slug"].map(lambda s: LEAGUE_LABELS.get(s, s))
    grouped["Kickoff (Paris)"] = grouped["kickoff"].dt.tz_convert("Europe/Paris").dt.strftime(
        "%a %d/%m %H:%M")

    if grouped.empty:
        if n_hidden > 0:
            st.info(
                f"⏱️ Aucun match à venir — {n_hidden} match(s) déjà commencé(s) "
                "ont été masqué(s) (cotes Betclic figées, plus d'intérêt). "
                "Reviens un peu avant le prochain week-end ou clique sur "
                "**Rafraîchir prédictions**."
            )
        else:
            st.info(
                "Aucun match à prédire dans les jours à venir. "
                "Clique sur **Rafraîchir prédictions** pour relancer le pipeline."
            )
        return
    if n_hidden > 0:
        st.caption(
            f"⏱️ {n_hidden} match(s) déjà commencé(s) masqué(s) "
            "(cotes Betclic figées une fois le coup d'envoi passé)."
        )

    # T017e — Nav Flashscore-like : sidebar arborescente par région avec
    # expanders + 2 toggles (Top 5 uniquement / Edge > 5%).
    # On expose dans la sidebar *uniquement les ligues présentes dans le log*
    # pour éviter une navigation creuse vers des ligues sans données.
    counts_by_slug = grouped["league_slug"].value_counts().to_dict()
    comp_slugs_in_log = list(counts_by_slug.keys())

    # Calcul "matchs avec au moins 1 edge ≥ 5%" : max sur (scorer, assist)
    # par event_id puis filtre seuil. Robuste si une seule des 2 colonnes existe.
    edge_cols = [c for c in ("edge_scorer", "edge_assist") if c in df.columns]
    if edge_cols and "event_id" in df.columns:
        edge_per_event = df.groupby("event_id")[edge_cols].max().max(axis=1)
        events_with_edge = set(
            int(eid) for eid, v in edge_per_event.items()
            if pd.notna(v) and float(v) >= 0.05
        )
    else:
        events_with_edge = set()

    qp_comp = st.query_params.get("comp")
    selected_slug: str | None = qp_comp if qp_comp in comp_slugs_in_log else None

    with st.sidebar:
        st.markdown("### 🧭 Navigation compétitions")

        # Toggles globaux
        only_top5 = st.toggle(
            "⭐ Top 5 uniquement", value=False, key="predbut_only_top5",
            help="Masque toutes les compétitions hors Top 5 (Premier League, La Liga, Serie A, Bundesliga, Ligue 1).",
        )
        only_edge = st.toggle(
            "💰 Edge ≥ 5% uniquement", value=False, key="predbut_only_edge",
            help="N'affiche que les matchs avec au moins une cote dont l'edge modèle ≥ 5%.",
        )

        if st.button("🔄 Toutes les compétitions", key="predbut_reset_comp",
                     use_container_width=True):
            selected_slug = None
            if "comp" in st.query_params:
                del st.query_params["comp"]
            st.rerun()

        groups = group_by_region(include_tier2=False)
        for region in REGION_ORDER:
            cfgs = [c for c in groups.get(region, [])
                    if c.slug in counts_by_slug
                    and (not only_top5 or c.region == "top5")]
            if not cfgs:
                continue
            region_total = sum(counts_by_slug[c.slug] for c in cfgs)
            with st.expander(f"{REGION_LABELS.get(region, region)} ({region_total})",
                             expanded=region in ("uefa", "top5")):
                for c in cfgs:
                    n = counts_by_slug.get(c.slug, 0)
                    label = f"{LEAGUE_LABELS.get(c.slug, c.name)} · {n}"
                    is_active = (selected_slug == c.slug)
                    btn_label = ("✓ " + label) if is_active else label
                    if st.button(btn_label, key=f"predbut_nav_{c.slug}",
                                 use_container_width=True):
                        st.query_params["comp"] = c.slug
                        st.query_params["page"] = "predictions_buteurs"
                        st.rerun()

    # Application des filtres au DataFrame grouped
    if only_top5:
        top5_set = {"premier_league", "la_liga", "serie_a", "bundesliga", "ligue_1"}
        grouped = grouped[grouped["league_slug"].isin(top5_set)].copy()
    if only_edge and events_with_edge:
        grouped = grouped[grouped["event_id"].astype(int).isin(events_with_edge)].copy()
    if selected_slug:
        grouped = grouped[grouped["league_slug"] == selected_slug].copy()

    if selected_slug:
        st.caption(
            f"🏆 Compétition sélectionnée : **{LEAGUE_LABELS.get(selected_slug, selected_slug)}** "
            f"— {len(grouped)} match(s)."
        )

    if grouped.empty:
        st.info(
            "Aucun match ne correspond à tes filtres. Élargis la sélection "
            "dans la barre latérale ou clique sur **🔄 Toutes les compétitions**."
        )
        return

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
