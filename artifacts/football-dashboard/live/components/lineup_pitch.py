"""Helper Streamlit pour le composant React `lineup-pitch`.

Le composant React vit dans `artifacts/football-dashboard/components/lineup_pitch/`
et est buildé via `pnpm --filter @workspace/lineup-pitch build` → output
dans `dist/`. On le charge ici avec `streamlit.components.v1.declare_component`
en pointant directement sur ce dossier.

Chantier 1 (FAIT) : helper `render_lineup_pitch(event_data, key)` ping
aller-retour bidirectionnel React ↔ Python pour valider le pipe.
Chantier 2 (FAIT) : composant terrain interactif rendu sur fixture
Atlético-Arsenal hardcodée côté React.
Chantier 3 (FAIT) : `build_match_data_from_log(event_id, log_df, head)`
transforme le `forward_log.jsonl` filtré sur l'event courant en payload
`MatchData` riche (rosters home + away avec toutes les cotes/stats moteur)
consommable par le composant React. Si le payload est passé via
`match_data=...`, le composant l'utilise au lieu du fixture.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit.components.v1 as components

_COMPONENT_NAME = "lineup_pitch"

# Chemin absolu vers le dist/ du composant React (output `vite build`).
_BUILD_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "components"
    / "lineup_pitch"
    / "dist"
)


def _resolve_component():
    """Déclare le composant Streamlit pointant sur le bundle React buildé.

    Lazy-instantiation pour éviter de planter l'import si le bundle n'a pas
    encore été généré (premier setup, CI sans build, etc.).
    """
    if not _BUILD_DIR.exists():
        return None
    return components.declare_component(_COMPONENT_NAME, path=str(_BUILD_DIR))


_component_func = _resolve_component()


def _coerce_float(v: Any) -> float | None:
    """Convertit une valeur pandas/numpy en float ou None (pour JSON safe).

    Gère :
      - NaN / pd.NA → None
      - inf → None (les cotes infinies n'ont pas de sens à afficher)
      - strings non-numériques → None
      - tout reste → float()
    """
    if v is None:
        return None
    try:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return None
            v = float(v)
        if pd.isna(v):
            return None
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _coerce_int(v: Any) -> int | None:
    f = _coerce_float(v)
    if f is None:
        return None
    return int(f)


def _coerce_bool(v: Any, default: bool = False) -> bool:
    """Convertit une valeur en bool ; pd.NA / NaN / None → default."""
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    return bool(v)


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s or None


def _player_payload(row: dict) -> dict:
    """Transforme un record forward_log (1 joueur) en schema React Player."""
    is_starter_raw = row.get("is_starter")
    # is_starter peut être null si BSD n'a pas confirmé la compo : on bascule
    # sur is_presumed_starter (top-22 par start_rate) comme proxy pré-match.
    if is_starter_raw is None or (
        isinstance(is_starter_raw, float) and math.isnan(is_starter_raw)
    ):
        is_starter_bool = _coerce_bool(row.get("is_presumed_starter"))
    else:
        is_starter_bool = _coerce_bool(is_starter_raw)

    pos = _coerce_str(row.get("position")) or "MID"
    avail = _coerce_str(row.get("availability")) or "available"
    team_side = _coerce_str(row.get("team_side")) or "home"

    return {
        "pid": _coerce_int(row.get("player_id")),
        "name": _coerce_str(row.get("player_name")) or "",
        "pos": pos,
        "team_side": team_side,
        "is_starter": is_starter_bool,
        "availability": avail,
        "injury_type": _coerce_str(row.get("injury_type")),
        "fair_scorer": _coerce_float(row.get("fair_odd_scorer")),
        "betclic_scorer": _coerce_float(row.get("betclic_odd_scorer")),
        "edge_scorer": _coerce_float(row.get("edge_scorer")),
        "fair_assist": _coerce_float(row.get("fair_odd_assist")),
        "betclic_assist": _coerce_float(row.get("betclic_odd_assist")),
        "edge_assist": _coerce_float(row.get("edge_assist")),
        "xg_player": _coerce_float(row.get("xg_player")),
        "xa_player": _coerce_float(row.get("xa_player")),
        "xg_p90": _coerce_float(row.get("xg_per_90_used")),
        "xa_p90": _coerce_float(row.get("xa_per_90_used")),
        "expected_shots": _coerce_float(row.get("expected_shots")),
        "expected_shots_on_target": _coerce_float(
            row.get("expected_shots_on_target")
        ),
        "shots_p90": _coerce_float(row.get("shots_per_90_used")),
        "shots_on_p90": _coerce_float(row.get("shots_on_target_per_90_used")),
        "minutes_expected": _coerce_float(row.get("minutes_expected")),
        "start_rate": _coerce_float(row.get("start_rate")),
        # Le forward_log ne contient pas le numéro de maillot (BSD ne l'expose
        # pas systématiquement). Le React applique un fallback `pid % 100`
        # quand jersey_number est null.
        "jersey_number": None,
    }


def build_match_data_from_log(
    event_id: int,
    log_df: pd.DataFrame,
    *,
    home_team: str | None = None,
    away_team: str | None = None,
    kickoff: str | None = None,
    league: str | None = None,
    saved_overrides: dict | None = None,
    bsd_formations: dict | None = None,
) -> dict | None:
    """Transforme le forward_log filtré sur un event en payload MatchData.

    Args:
        event_id: l'event BSD à reconstruire.
        log_df: le DataFrame forward_log entier.
        home_team / away_team / kickoff / league: overrides explicites
            (sinon dérivés du log : `match`, `kickoff`, `league_name`).

    Returns:
        Le dict consommable par le composant React (même shape que le
        fixture `atletico_arsenal.json`), ou None si l'event n'a aucune
        prédiction logguée (pool jamais buildé).
    """
    if log_df is None or log_df.empty:
        return None
    try:
        sub = log_df[log_df["event_id"] == event_id]
    except KeyError:
        return None
    if sub.empty:
        return None

    # Convertir en records (dict) pour éviter les pièges pandas (NaN type, etc.)
    records = sub.to_dict(orient="records")
    if not records:
        return None
    first = records[0]

    # Header derived ↓
    match_str = _coerce_str(first.get("match")) or ""
    if home_team is None or away_team is None:
        # Format du log : "HomeTeam - AwayTeam"
        if " - " in match_str:
            ht, at = match_str.split(" - ", 1)
            home_team = home_team or ht.strip()
            away_team = away_team or at.strip()
        else:
            home_team = home_team or "Home"
            away_team = away_team or "Away"

    if kickoff is None:
        kickoff = _coerce_str(first.get("kickoff"))
    if league is None:
        league = (
            _coerce_str(first.get("league_name"))
            or _coerce_str(first.get("league_slug"))
            or ""
        )

    # Group by team_side ↓
    home_players: list[dict] = []
    away_players: list[dict] = []
    for r in records:
        side = _coerce_str(r.get("team_side")) or "home"
        p = _player_payload(r)
        if side == "away":
            away_players.append(p)
        else:
            home_players.append(p)

    bsd_f = bsd_formations or {}
    return {
        "event_id": int(event_id),
        "home_team": home_team or "Home",
        "away_team": away_team or "Away",
        "kickoff": kickoff,
        "league": league or "",
        "xg_team_home": _coerce_float(first.get("xg_team_home")),
        "xg_team_away": _coerce_float(first.get("xg_team_away")),
        "home": home_players,
        "away": away_players,
        # Compositions manuelles déjà sauvegardées par l'utilisateur. Le
        # composant React rehydrate l'état depuis cette clé au mount + au
        # changement de side. None ou {home: null, away: null} = pas
        # d'override → comportement auto-detect.
        "saved_overrides": saved_overrides or {"home": None, "away": None},
        # Formation officielle remontée par BSD (`getMatchLineups[side].
        # formation`) quand la compo est confirmée. Le composant React la
        # priorise sur l'heuristique detectFormation. None pendant la
        # phase pré-match (BSD ne publie qu'à ~30-60 min du coup d'envoi).
        "home_formation_bsd": _coerce_str(bsd_f.get("home")),
        "away_formation_bsd": _coerce_str(bsd_f.get("away")),
    }


def render_lineup_pitch(
    *,
    event_data: dict[str, Any],
    key: str,
    match_data: dict | None = None,
    default: Any = None,
) -> Any:
    """Rend le composant terrain et retourne la valeur émise par React.

    Args:
        event_data: dict header (home_team, away_team, kickoff, league)
            utilisé en fallback si `match_data` est None.
        key: clé Streamlit unique par event (sinon collision si plusieurs
            matchs affichés simultanément).
        match_data: payload riche (rosters + cotes) construit via
            `build_match_data_from_log()`. Si fourni, le composant l'utilise
            au lieu du fixture hardcodé Atlético-Arsenal. None = mode dev.
        default: valeur retournée tant que React n'a rien émis.

    Returns:
        Le dernier dict émis par React via `setComponentValue`, sinon
        `default`. Format save : `{action: "save", ts, payload: {side,
        formation, starters_pids, minutes_overrides}}`.
    """
    if _component_func is None:
        import streamlit as st

        st.warning(
            "Composant `lineup_pitch` non buildé. Lance "
            "`pnpm --filter @workspace/lineup-pitch build` "
            f"(dist/ attendu dans {_BUILD_DIR})."
        )
        return default

    return _component_func(
        home_team=event_data.get("home_team"),
        away_team=event_data.get("away_team"),
        kickoff=event_data.get("kickoff"),
        league=event_data.get("league"),
        match_data=match_data,
        key=key,
        default=default,
    )
