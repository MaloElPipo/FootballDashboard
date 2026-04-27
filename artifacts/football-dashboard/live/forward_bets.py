"""Store dédié au tracking forward test edge buteurs (T015).

Séparé volontairement de `bet_tracker.py` (qui gère bets_tracker.json pour
la page « 📊 Suivi des paris »). Ici, chaque bet capture le contexte complet
au moment de la prise (cote prise, cote juste calculée par le modèle 4.1,
edge %, mise, lien event_id pour pouvoir auto-résoudre via forward_log).

Schéma d'un forward bet :
{
    "id": 1,                                    # auto-incrément
    "added_at": "2026-04-27T18:30:00",          # ISO local Europe/Paris
    "event_id": 12345,                          # BSD event id (lien forward_log)
    "match": "Lazio - Udinese",
    "league_slug": "italy-serie-a",
    "league_name": "Serie A",
    "kickoff": "2026-04-27T20:45:00+00:00",     # ISO UTC
    "player_id": 67890,
    "player_name": "Castellanos",
    "market": "Buteur",                         # ou "Passeur"
    "p_model": 0.32,                            # probabilité modèle (0-1)
    "fair_odd": 3.10,                           # cote juste modèle 4.1
    "betclic_odd": 3.50,                        # cote prise (Betclic)
    "edge_pct": 12.0,                           # (cote_book * p) - 1, en %
    "stake": 1.0,                               # mise en unités
    "result": "pending",                        # pending / won / lost / void
    "profit_units": null,                       # P/L en unités si résolu
}
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FORWARD_BETS_FILE = DATA_DIR / "forward_bets.json"


def load_forward_bets() -> list[dict[str, Any]]:
    if not FORWARD_BETS_FILE.exists():
        return []
    try:
        with FORWARD_BETS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_forward_bets(bets: list[dict[str, Any]]) -> None:
    with FORWARD_BETS_FILE.open("w", encoding="utf-8") as f:
        json.dump(bets, f, indent=2, ensure_ascii=False)


def _next_id(bets: list[dict[str, Any]]) -> int:
    return (max((b.get("id", 0) for b in bets), default=0) or 0) + 1


def add_forward_bet(
    *,
    event_id: int,
    match: str,
    league_slug: str | None,
    league_name: str | None,
    kickoff: str | None,
    player_id: int | None,
    player_name: str,
    market: str,
    p_model: float | None,
    fair_odd: float | None,
    betclic_odd: float,
    edge_pct: float,
    stake: float,
) -> dict[str, Any]:
    bets = load_forward_bets()
    bet = {
        "id": _next_id(bets),
        "added_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "event_id": int(event_id),
        "match": str(match),
        "league_slug": (str(league_slug) if league_slug else None),
        "league_name": (str(league_name) if league_name else None),
        "kickoff": (str(kickoff) if kickoff else None),
        "player_id": (int(player_id) if player_id is not None else None),
        "player_name": str(player_name),
        "market": str(market),
        "p_model": (float(p_model) if p_model is not None else None),
        "fair_odd": (round(float(fair_odd), 2) if fair_odd is not None else None),
        "betclic_odd": round(float(betclic_odd), 2),
        "edge_pct": round(float(edge_pct), 2),
        "stake": round(float(stake), 2),
        "result": "pending",
        "profit_units": None,
    }
    bets.append(bet)
    save_forward_bets(bets)
    return bet


def update_forward_bet_result(bet_id: int, result: str) -> None:
    """result ∈ {'pending', 'won', 'lost', 'void'}"""
    bets = load_forward_bets()
    for b in bets:
        if b.get("id") == bet_id:
            b["result"] = result
            stake = float(b.get("stake") or 0)
            odd = float(b.get("betclic_odd") or 0)
            if result == "won":
                b["profit_units"] = round(stake * (odd - 1), 2)
            elif result == "lost":
                b["profit_units"] = round(-stake, 2)
            elif result == "void":
                b["profit_units"] = 0.0
            else:
                b["profit_units"] = None
            break
    save_forward_bets(bets)


def delete_forward_bet(bet_id: int) -> None:
    bets = [b for b in load_forward_bets() if b.get("id") != bet_id]
    save_forward_bets(bets)


def clear_all_forward_bets() -> None:
    save_forward_bets([])
