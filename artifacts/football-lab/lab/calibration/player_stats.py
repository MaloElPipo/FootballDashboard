"""Phase 4 — Migration player stats : wrapper BSD getPlayerStats + comparaison.

Compare BSD getPlayerStats vs Sofascore (legacy prod) sur les joueurs du forward
log. Mesure la couverture hors top 5 (MLS, Eredivisie, Primeira).
"""
from __future__ import annotations

from pathlib import Path

import json

from . import bsd_client


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper BSD
# ─────────────────────────────────────────────────────────────────────────────


def fetch_player_season_stats(player_id: int, season_id: int | None = None) -> dict | None:
    """Aggrege stats joueur sur une saison (somme par-match BSD getPlayerStats)."""
    candidates = [
        ("v2/player-stats/", {"player": player_id, "season": season_id}),
        ("v2/players/{0}/stats/".format(player_id), {"season": season_id}),
        ("player-stats/", {"player": player_id, "season": season_id}),
    ]
    for ep, params in candidates:
        try:
            data = bsd_client.bsd_get(ep, params={k: v for k, v in params.items() if v is not None})
            rows = _extract_rows(data)
            if rows:
                return _aggregate(rows, player_id, season_id)
        except Exception:
            continue
    return None


def _extract_rows(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("results", "stats", "data", "items"):
            v = data.get(k)
            if isinstance(v, list):
                return v
    return []


def _aggregate(rows: list[dict], player_id: int, season_id: int | None) -> dict:
    n = len(rows)
    g = sum(int(r.get("goals") or 0) for r in rows)
    a = sum(int(r.get("assists") or 0) for r in rows)
    sh = sum(int(r.get("shots") or 0) for r in rows)
    sot = sum(int(r.get("shots_on_target") or r.get("sot") or 0) for r in rows)
    xg = sum(float(r.get("xg") or r.get("expected_goals") or 0.0) for r in rows)
    xa = sum(float(r.get("xa") or r.get("expected_assists") or 0.0) for r in rows)
    mins = sum(int(r.get("minutes_played") or r.get("minutes") or 0) for r in rows)
    yc = sum(int(r.get("yellow_cards") or 0) for r in rows)
    rc = sum(int(r.get("red_cards") or 0) for r in rows)
    return {
        "player_id": player_id,
        "season_id": season_id,
        "matches": n,
        "goals": g,
        "assists": a,
        "shots": sh,
        "shots_on_target": sot,
        "xg": round(xg, 3),
        "xa": round(xa, 3),
        "minutes": mins,
        "yellow_cards": yc,
        "red_cards": rc,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Comparaison BSD vs Sofascore (snapshot du forward log)
# ─────────────────────────────────────────────────────────────────────────────


def compare_with_sofascore(
    bsd_stats: dict, sofascore_stats: dict, tolerance: dict | None = None
) -> dict:
    """Calcule les ecarts par champ. tolerance : seuils par champ pour flag DISAGREE."""
    tolerance = tolerance or {
        "goals": 1, "assists": 1, "xg": 0.5, "xa": 0.3, "minutes": 90
    }
    out = {}
    for field, tol in tolerance.items():
        v_bsd = bsd_stats.get(field)
        v_sof = sofascore_stats.get(field)
        if v_bsd is None or v_sof is None:
            out[field] = {"bsd": v_bsd, "sofa": v_sof, "delta": None, "flag": "MISSING"}
            continue
        try:
            delta = float(v_bsd) - float(v_sof)
        except (TypeError, ValueError):
            out[field] = {"bsd": v_bsd, "sofa": v_sof, "delta": None, "flag": "TYPE_ERR"}
            continue
        out[field] = {
            "bsd": v_bsd,
            "sofa": v_sof,
            "delta": round(delta, 3),
            "flag": "OK" if abs(delta) <= tol else "DISAGREE",
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Couverture hors top 5
# ─────────────────────────────────────────────────────────────────────────────


def coverage_extension(player_ids: list[int], season_id: int) -> dict:
    """Pour une liste de joueurs hors top 5, taux de couverture stats BSD."""
    n_total = len(player_ids)
    n_with = 0
    detail = []
    for pid in player_ids:
        s = fetch_player_season_stats(pid, season_id)
        if s and s["matches"] > 0:
            n_with += 1
            detail.append({"player_id": pid, "matches": s["matches"], "goals": s["goals"]})
        else:
            detail.append({"player_id": pid, "matches": 0, "goals": 0})
    return {
        "total": n_total,
        "with_data": n_with,
        "coverage_pct": round(100 * n_with / max(n_total, 1), 1),
        "detail": detail,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers : sample forward log (snapshot 30 joueurs)
# ─────────────────────────────────────────────────────────────────────────────


def load_forward_log_players(prod_dir: Path, limit: int = 30) -> list[dict]:
    """Lit forward_log.jsonl prod, retourne les N joueurs les plus suivis."""
    fl = prod_dir / "live" / "data" / "forward_log.jsonl"
    if not fl.exists():
        return []
    counts: dict[int, dict] = {}
    with fl.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            pid = rec.get("player_id")
            if not pid:
                continue
            d = counts.setdefault(int(pid), {"player_id": int(pid), "name": rec.get("player_name"), "n_picks": 0})
            d["n_picks"] += 1
    top = sorted(counts.values(), key=lambda x: -x["n_picks"])
    return top[:limit]
