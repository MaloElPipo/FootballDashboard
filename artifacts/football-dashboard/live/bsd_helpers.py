"""Wrappers REST minimaux autour de l'API BSD pour le pipeline forward live.

Pas de Streamlit, pas de cache st.session — utilisable depuis n'importe quel script.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

BSD_BASE = "https://sports.bzzoiro.com/api"
DEFAULT_TIMEOUT = 30


def _headers() -> dict[str, str]:
    key = os.environ.get("BSD_API_KEY", "")
    if not key:
        raise RuntimeError("BSD_API_KEY environment variable not set")
    return {"Authorization": f"Token {key}"}


# Ligues du forward test (Top 5 européens). IDs vérifiés via listLeagues BSD.
TOP5_LEAGUES = {
    "premier_league": {"bsd_id": 1, "name": "Premier League", "country": "England"},
    "la_liga":        {"bsd_id": 3, "name": "La Liga",        "country": "Spain"},
    "serie_a":        {"bsd_id": 4, "name": "Serie A",        "country": "Italy"},
    "bundesliga":     {"bsd_id": 5, "name": "Bundesliga",     "country": "Germany"},
    "ligue_1":        {"bsd_id": 6, "name": "Ligue 1",        "country": "France"},
}


def get_upcoming_events(league_id: int, date_from: str, date_to: str) -> list[dict]:
    """Liste les matchs notstarted dans la fenêtre [date_from, date_to] (YYYY-MM-DD)."""
    out: list[dict] = []
    offset = 0
    while True:
        r = requests.get(
            f"{BSD_BASE}/events/",
            params={
                "league": league_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": "notstarted",
                "limit": 50,
                "offset": offset,
            },
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        out.extend(results)
        if len(out) >= data.get("count", 0):
            break
        offset += 50
    return out


def get_finished_events(league_id: int, date_from: str, date_to: str) -> list[dict]:
    """Liste les matchs finished dans la fenêtre."""
    out: list[dict] = []
    offset = 0
    while True:
        r = requests.get(
            f"{BSD_BASE}/events/",
            params={
                "league": league_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": "finished",
                "limit": 50,
                "offset": offset,
            },
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])
        if not results:
            break
        out.extend(results)
        if len(out) >= data.get("count", 0):
            break
        offset += 50
    return out


def get_event_detail(event_id: int) -> dict | None:
    """Détail complet d'un match (odds, lineups, incidents...).

    Deux corrections de format BSD avant retour, pour rendre le payload
    consommable par `predict_today.get_lineup_for_event` (intouchable) :

    1. **Mismatch clés `players` ↔ `starters`** : BSD renvoie les titulaires
       sous `lineups.{home,away}.players`, mais le V1 lit `starters` ou
       `starting`. On copie systématiquement `players → starters` quand
       non vide pour que la compo officielle soit reconnue comme confirmée.

    2. **Fallback `/matches/` quand `/events/` est vide** : l'endpoint
       `/events/{id}/` peut être en retard de quelques minutes par rapport
       à `/matches/{id}/` pour les compos confirmées. Si `players=[]` au
       sortir du premier call, on retente sur `/matches/`.

    Les autres champs (odds, status, head_to_head, …) proviennent toujours
    du premier appel `/events/{id}/`.
    """
    try:
        r = requests.get(
            f"{BSD_BASE}/events/{event_id}/",
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    lineups = data.get("lineups") or {}
    if not isinstance(lineups, dict):
        return data

    # Étape 1 : si /events/ a déjà des players non vides, on les copie
    # vers starters (le V1 ne lit que starters/starting).
    for side in ("home", "away"):
        sb = lineups.get(side) or {}
        players = sb.get("players") or []
        if players and not (sb.get("starters") or sb.get("starting")):
            sb["starters"] = players
            data["lineups"][side] = sb

    # Étape 2 : si starters reste vide pour au moins un côté, fallback
    # sur /matches/{id}/ qui sert souvent un payload plus à jour.
    home_starters = ((data.get("lineups") or {}).get("home") or {}).get("starters") or []
    away_starters = ((data.get("lineups") or {}).get("away") or {}).get("starters") or []
    if not home_starters or not away_starters:
        try:
            rm = requests.get(
                f"{BSD_BASE}/matches/{event_id}/",
                headers=_headers(),
                timeout=DEFAULT_TIMEOUT,
            )
            if rm.status_code == 200:
                mlineups = (rm.json() or {}).get("lineups") or {}
                if isinstance(mlineups, dict):
                    for side in ("home", "away"):
                        sb_m = mlineups.get(side) or {}
                        players_m = sb_m.get("players") or []
                        existing = (
                            (data["lineups"].get(side) or {}).get("starters") or []
                        )
                        if players_m and not existing:
                            data.setdefault("lineups", {}).setdefault(side, {})
                            data["lineups"][side]["starters"] = players_m
                            data["lineups"][side]["substitutes"] = (
                                sb_m.get("substitutes") or []
                            )
                            data["lineups"][side]["formation"] = sb_m.get("formation")
        except Exception:
            # Fallback silencieux : on garde ce qu'on a (peut-être vide
            # côté home ou away → predict_today fera build_lineup_fallback).
            pass

    return data


def get_event_player_stats(event_id: int) -> list[dict]:
    """Stats par joueur pour un match."""
    try:
        r = requests.get(
            f"{BSD_BASE}/player-stats/",
            params={"event": event_id, "limit": 200},
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except Exception:
        return []


def get_event_incidents(event_id: int) -> list[dict]:
    """Incidents (buts, passes décisives, cartons, subs) pour un match."""
    try:
        r = requests.get(
            f"{BSD_BASE}/incidents/",
            params={"event": event_id, "limit": 200},
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        if r.status_code != 200:
            return []
        return r.json().get("results", [])
    except Exception:
        return []


def fetch_events_details_parallel(event_ids: list[int], max_workers: int = 12) -> dict[int, dict]:
    """Récupère le détail de plusieurs matchs en parallèle."""
    out: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(get_event_detail, eid): eid for eid in event_ids}
        for fut in as_completed(futures):
            eid = futures[fut]
            res = fut.result()
            if res is not None:
                out[eid] = res
    return out


def fetch_events_player_stats_parallel(event_ids: list[int], max_workers: int = 12) -> dict[int, list[dict]]:
    """Récupère les stats joueurs de plusieurs matchs en parallèle."""
    out: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(get_event_player_stats, eid): eid for eid in event_ids}
        for fut in as_completed(futures):
            eid = futures[fut]
            out[eid] = fut.result()
    return out


def get_team_squad(team_id: int) -> list[dict]:
    """Effectif actuel d'une équipe (résout les transferts hiver, plus complet
    que d'agréger les lineups historiques)."""
    out: list[dict] = []
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{BSD_BASE}/players/",
                params={"team": team_id, "limit": 50, "offset": offset},
                headers=_headers(),
                timeout=DEFAULT_TIMEOUT,
            )
            if r.status_code != 200:
                break
            data = r.json()
        except Exception:
            break
        results = data.get("results", [])
        if not results:
            break
        out.extend(results)
        if len(out) >= data.get("count", 0):
            break
        offset += 50
    return out


def fetch_team_squads_parallel(team_ids: list[int], max_workers: int = 8) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(get_team_squad, tid): tid for tid in team_ids}
        for fut in as_completed(futures):
            tid = futures[fut]
            out[tid] = fut.result()
    return out


def extract_odds(event: dict) -> dict[str, float | None]:
    """Extrait les odds 1X2 + O/U 2.5 + BTTS d'un event BSD.

    Retourne None pour les valeurs manquantes — l'appelant gère les fallbacks.
    """
    return {
        "odds_h": event.get("odds_home"),
        "odds_d": event.get("odds_draw"),
        "odds_a": event.get("odds_away"),
        "ou25_under": event.get("odds_under_25"),
        "ou25_over": event.get("odds_over_25"),
        "btts_yes": event.get("odds_btts_yes"),
        "btts_no": event.get("odds_btts_no"),
    }
