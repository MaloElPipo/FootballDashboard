"""Helper Streamlit pour le composant React `lineup-pitch`.

Le composant React vit dans `artifacts/football-dashboard/components/lineup_pitch/`
et est buildé via `pnpm --filter @workspace/lineup-pitch build` → output
dans `dist/`. On le charge ici avec `streamlit.components.v1.declare_component`
en pointant directement sur ce dossier.

Chantier 1 (FAIT) : helper `render_lineup_pitch(event_data, key)` qui
expose un ping aller-retour bidirectionnel React ↔ Python pour valider
le pipe avant d'attaquer la vraie UI terrain.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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
    encore été généré (premier setup, CI sans build, etc.). Si le dossier
    n'existe pas, on retourne None et le caller affiche un message d'erreur
    explicite plutôt qu'une stack trace cryptique.
    """
    if not _BUILD_DIR.exists():
        return None
    return components.declare_component(_COMPONENT_NAME, path=str(_BUILD_DIR))


_component_func = _resolve_component()


def render_lineup_pitch(
    *,
    event_data: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    """Rend le composant terrain et retourne la valeur émise via setComponentValue.

    Args:
        event_data: dict passé en props au composant React (home_team,
            away_team, kickoff, league, et plus tard la liste joueurs).
        key: clé Streamlit unique par event (sinon collision si plusieurs
            matchs affichés simultanément).
        default: valeur retournée tant que le composant n'a rien émis.

    Returns:
        Le dernier dict émis par le composant via setComponentValue, ou
        `default` au premier rendu. Au chantier 1, il s'agit d'un dict
        `{action: "ping", ts: <ms>, count: <n>}` à chaque clic ping.
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
        key=key,
        default=default,
    )
