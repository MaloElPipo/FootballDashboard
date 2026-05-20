"""Phase 5 — Tracker de mouvement de cotes (sharp money detection).

Snapshot bi-quotidien des cotes Pinnacle pour le forward log ouvert.
Stocke en JSONL (append-only). Detecte SHORTENING / DRIFTING en comparant
au snapshot precedent par event_id + outcome.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import bsd_client


HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "movement_history.jsonl"


def snapshot_event_odds(event_id: int, market: str = "1x2") -> list[dict]:
    """Snapshot mcpBSD_compareOdds equivalent via REST BSD."""
    candidates = [
        (f"v2/events/{event_id}/compare-odds/", {"market": market}),
        (f"v2/matches/{event_id}/odds/compare/", {"market": market}),
        ("v2/odds/compare/", {"event": event_id, "market": market}),
    ]
    payload = None
    for ep, p in candidates:
        try:
            data = bsd_client.bsd_get(ep, params=p, ttl=60)
            if data:
                payload = data
                break
        except Exception:
            continue
    if not payload:
        return []

    out = []
    rows = payload.get("results") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    for r in rows:
        out.append({
            "event_id": event_id,
            "market": market,
            "bookmaker": r.get("bookmaker") or r.get("book") or "?",
            "outcome": r.get("outcome") or r.get("selection") or "?",
            "decimal_odds": r.get("decimal_odds") or r.get("odds"),
            "previous_odds": r.get("previous_decimal_odds") or r.get("previous_odds"),
            "movement": r.get("movement") or "",
            "is_max_quote": r.get("is_max_quote", False),
            "implied_proba": r.get("implied_probability"),
        })
    return out


def append_snapshot(records: list[dict]) -> int:
    """Append-only en JSONL avec timestamp."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().isoformat() + "Z"
    n = 0
    with HISTORY_PATH.open("a") as f:
        for r in records:
            r2 = dict(r)
            r2["snapshot_at"] = ts
            f.write(json.dumps(r2, ensure_ascii=False) + "\n")
            n += 1
    return n


def load_history(event_id: int | None = None) -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    out = []
    with HISTORY_PATH.open() as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_id is None or r.get("event_id") == event_id:
                out.append(r)
    return out


def detect_movements(event_id: int, bookmaker: str = "pinnacle") -> dict:
    """Pour un event, identifie SHORTENING / DRIFTING par outcome sur la fenetre history."""
    hist = [r for r in load_history(event_id) if r.get("bookmaker", "").lower() == bookmaker.lower()]
    if not hist:
        return {"event_id": event_id, "bookmaker": bookmaker, "outcomes": {}}

    by_outcome: dict[str, list[dict]] = {}
    for r in hist:
        by_outcome.setdefault(r["outcome"], []).append(r)

    out = {}
    for outcome, lst in by_outcome.items():
        lst_sorted = sorted(lst, key=lambda x: x.get("snapshot_at", ""))
        first_odd = lst_sorted[0].get("decimal_odds")
        last_odd = lst_sorted[-1].get("decimal_odds")
        try:
            delta_pct = (float(last_odd) - float(first_odd)) / float(first_odd) * 100
        except (TypeError, ValueError, ZeroDivisionError):
            delta_pct = None
        signal = ""
        if delta_pct is not None:
            if delta_pct < -3:
                signal = "SHORTENING"  # cote baisse > 3 % = money in
            elif delta_pct > 3:
                signal = "DRIFTING"  # cote monte > 3 % = money out
        out[outcome] = {
            "first_odd": first_odd,
            "last_odd": last_odd,
            "delta_pct": round(delta_pct, 2) if delta_pct is not None else None,
            "signal": signal,
            "n_snapshots": len(lst_sorted),
            "series": [(r.get("snapshot_at"), r.get("decimal_odds")) for r in lst_sorted],
        }
    return {"event_id": event_id, "bookmaker": bookmaker, "outcomes": out}


def load_open_forward_log_events(prod_dir: Path) -> list[int]:
    """Liste les event_id encore ouverts dans le forward log prod."""
    fl = prod_dir / "live" / "data" / "forward_log.jsonl"
    if not fl.exists():
        return []
    open_ids = set()
    with fl.open() as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("outcome_scored"):
                continue
            eid = rec.get("event_id") or rec.get("match_id")
            if eid:
                open_ids.add(int(eid))
    return sorted(open_ids)
