"""Overrides manuels de transferts/prêts non reflétés par BSD.

Source : `live/data/transfers_overrides.json` (éditable manuellement).

Effets :
- `apply_to_pool(pool, slug)` : marque le joueur comme indisponible dans le
  pool de la ligue concernée (availability="loan" / "transfer"), ce qui le
  fait filtrer par `is_player_unavailable` dans `predict_today.py`.
- `inject_into_event_detail(detail, home_team_id, away_team_id)` : ajoute le
  joueur dans `unavailable_players[side]` du payload BSD pour qu'il apparaisse
  dans la section "🚑 Joueurs indisponibles" de l'UI.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parent / "data" / "transfers_overrides.json"


def load_overrides() -> list[dict[str, Any]]:
    if not DATA_PATH.exists():
        return []
    try:
        payload = json.loads(DATA_PATH.read_text())
    except json.JSONDecodeError:
        return []
    return payload.get("overrides") or []


def apply_to_pool(pool: dict, slug: str) -> int:
    """Marque les joueurs override comme indisponibles dans le pool de `slug`.
    Retourne le nombre de joueurs touchés."""
    n = 0
    for ov in load_overrides():
        if ov.get("from_league") != slug:
            continue
        pid = ov.get("player_id")
        if pid is None:
            continue
        pid = int(pid)
        entry = pool.get(pid)
        if entry is None:
            continue
        reason = ov.get("reason") or "loan"
        entry["availability"] = reason
        entry["injury_type"] = ov.get("detail") or reason.title()
        entry["injury_expected_return"] = ov.get("until")
        n += 1
    return n


def inject_into_event_detail(detail: dict, home_team_id: int | None,
                              away_team_id: int | None) -> None:
    """Ajoute les joueurs override des deux équipes dans `unavailable_players`
    du payload BSD pour qu'ils apparaissent dans l'UI. Mute `detail` en place."""
    if not detail or detail.get("_error"):
        return
    overrides = load_overrides()
    if not overrides:
        return

    unav = detail.get("unavailable_players") or {}
    if not isinstance(unav, dict):
        unav = {}
    unav.setdefault("home", [])
    unav.setdefault("away", [])

    sides_by_team_id = {}
    if home_team_id is not None:
        sides_by_team_id[int(home_team_id)] = "home"
    if away_team_id is not None:
        sides_by_team_id[int(away_team_id)] = "away"

    for ov in overrides:
        from_id = ov.get("from_team_id")
        if from_id is None:
            continue
        side = sides_by_team_id.get(int(from_id))
        if side is None:
            continue
        # Évite les doublons si BSD a déjà la même entrée
        pid = ov.get("player_id")
        existing_ids = {p.get("id") for p in unav[side] if isinstance(p, dict)}
        if pid in existing_ids:
            continue
        unav[side].append({
            "id": pid,
            "name": ov.get("player_name", f"Player {pid}"),
            "reason": ov.get("detail") or ov.get("reason", "loan"),
            "expected_return": ov.get("until"),
            "_override": True,
        })

    detail["unavailable_players"] = unav
