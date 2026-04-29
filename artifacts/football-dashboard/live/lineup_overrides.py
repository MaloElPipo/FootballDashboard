"""Persistance JSON des compositions manuelles sauvegardées par l'utilisateur
depuis le composant React `lineup_pitch` (chantier 4 du T023).

Schema disque (un fichier par event BSD, deux clés indépendantes) :

    live/data/lineup_overrides/{event_id}.json
    {
      "event_id": 338,
      "updated_at_ms": 1714430000000,
      "home": {
        "side": "home",
        "formation": "4-2-3-1",
        "starters_pids": [pid_gk, pid_def1, ..., pid_fwd1],   # len == 11
        "minutes_overrides": {"<pid>": 75, ...},
        "saved_at_ms": 1714430000000
      },
      "away": null
    }

Conventions :

* `starters_pids` est ordonné selon `FORMATIONS[formation]` côté React. Le
  composant restaure customAssignment en mappant `slots[i] -> starters_pids[i]`.
* Sauver le side `home` ne touche pas le side `away` du même fichier. Ça
  permet à l'utilisateur de personnaliser chaque équipe indépendamment.
* Tout payload reçu est validé en mode best-effort : un payload invalide
  est ignoré (loggué côté ui.py via st.warning) plutôt que de planter.

Le fichier est écrit de façon atomique (`tmp + os.replace`) pour qu'un
crash mid-write ne corrompe jamais l'état persisté.
"""

from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

DATA_DIR = Path(__file__).resolve().parent / "data"
OVERRIDES_DIR = DATA_DIR / "lineup_overrides"

Side = Literal["home", "away"]
_VALID_SIDES: tuple[str, ...] = ("home", "away")

# Doit rester aligné avec FormationKey dans
# components/lineup_pitch/src/types.ts. Toute formation hors de cet
# ensemble persistée crasherait React au reload (FORMATIONS[k] undefined).
_VALID_FORMATIONS: frozenset[str] = frozenset({
    "4-3-3",
    "4-2-3-1",
    "4-4-2",
    "3-5-2",
    "3-4-3",
    "5-3-2",
    "4-5-1",
    "4-1-4-1",
    "5-4-1",
    "3-4-2-1",
})

_STARTERS_LEN: int = 11
_MINUTE_MIN: float = 0.0
_MINUTE_MAX: float = 120.0  # bornage défensif (90' + prolongations)


def _coerce_event_id(event_id: Any) -> int:
    """Force event_id en int strictement positif pour éviter path traversal
    et toute valeur ambiguë (string, float, négatif). Lève ValueError sinon.
    """
    eid = int(event_id)
    if eid <= 0:
        raise ValueError(f"event_id must be > 0, got {eid!r}")
    return eid


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    """Verrou exclusif inter-process (Linux) sur un fichier sentinelle, pour
    sérialiser un read-modify-write sur le même event. Best-effort sur
    plateformes sans fcntl : pas de lock mais pas d'erreur.
    """
    _ensure_dir()
    lock_path = path.with_suffix(path.suffix + ".lock")
    try:
        import fcntl  # type: ignore[import-not-found]
    except ImportError:
        # Plateforme non-POSIX : on saute le lock plutôt que de planter.
        yield
        return
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _ensure_dir() -> None:
    OVERRIDES_DIR.mkdir(parents=True, exist_ok=True)


def _path(event_id: int) -> Path:
    return OVERRIDES_DIR / f"{_coerce_event_id(event_id)}.json"


def _atomic_write(path: Path, data: dict) -> None:
    """Écriture atomique : tmp puis os.replace pour éviter fichier corrompu."""
    _ensure_dir()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def _normalize_side_payload(payload: Any) -> dict | None:
    """Valide / normalise un payload Save émis par React. Retourne None si KO."""
    if not isinstance(payload, dict):
        return None
    side = payload.get("side")
    formation = payload.get("formation")
    starters = payload.get("starters_pids")
    if side not in _VALID_SIDES:
        return None
    # Whitelist strict de la formation : un état avec une key inconnue
    # crasherait React (FORMATIONS[k] undefined → .map sur undefined).
    if not isinstance(formation, str) or formation not in _VALID_FORMATIONS:
        return None
    if not isinstance(starters, list):
        return None
    # Sanitize : on garde int OU None (un slot vide reste possible si le
    # roster est < 11). On rejette les valeurs non-int.
    cleaned_starters: list[int | None] = []
    for v in starters:
        if v is None:
            cleaned_starters.append(None)
        else:
            try:
                cleaned_starters.append(int(v))
            except (TypeError, ValueError):
                cleaned_starters.append(None)
    # Tronque/pad à exactement 11 slots pour matcher FORMATIONS[k].length.
    if len(cleaned_starters) > _STARTERS_LEN:
        cleaned_starters = cleaned_starters[:_STARTERS_LEN]
    elif len(cleaned_starters) < _STARTERS_LEN:
        cleaned_starters = cleaned_starters + [None] * (
            _STARTERS_LEN - len(cleaned_starters)
        )
    minutes = payload.get("minutes_overrides") or {}
    cleaned_minutes: dict[str, float] = {}
    if isinstance(minutes, dict):
        for k, v in minutes.items():
            try:
                pid_int = int(k)
                mins = float(v)
            except (TypeError, ValueError):
                continue
            # Rejet NaN/Inf et bornage défensif.
            if not math.isfinite(mins):
                continue
            mins = max(_MINUTE_MIN, min(_MINUTE_MAX, mins))
            cleaned_minutes[str(pid_int)] = mins
    return {
        "side": side,
        "formation": formation,
        "starters_pids": cleaned_starters,
        "minutes_overrides": cleaned_minutes,
    }


def load_lineup_override(event_id: int) -> dict:
    """Charge l'override pour un event. Retourne toujours un dict avec les
    deux clés home/away (None si pas d'override pour ce side).

    Les payloads invalides (formation hors enum, etc.) sont silencieusement
    écartés via `_normalize_side_payload`, garantissant qu'un fichier
    legacy/corrompu ne casse pas le composant React au reload.
    """
    try:
        path = _path(event_id)
    except (TypeError, ValueError):
        return {"home": None, "away": None}
    empty = {"home": None, "away": None}
    if not path.exists():
        return empty
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return empty
    out: dict = {"home": None, "away": None}
    for s in _VALID_SIDES:
        candidate = raw.get(s)
        if not isinstance(candidate, dict):
            continue
        # Re-valide : si le fichier a été écrit par une version antérieure
        # avec une formation maintenant retirée, on l'ignore plutôt que de
        # le servir.
        normalized = _normalize_side_payload({**candidate, "side": s})
        if normalized is None:
            continue
        # Préserve saved_at_ms d'origine si présent (sinon laisse absent ;
        # les writers récents le posent toujours).
        ts = candidate.get("saved_at_ms")
        if isinstance(ts, (int, float)) and math.isfinite(float(ts)):
            normalized["saved_at_ms"] = int(ts)
        out[s] = normalized
    return out


def save_lineup_override(
    event_id: int,
    payload: Any,
    ts_ms: int | None = None,
) -> dict | None:
    """Sauve l'override pour le side défini DANS le payload (`payload['side']`).

    Préserve l'autre side si déjà sauvé. Retourne le dict normalisé écrit
    sur disque, ou None si le payload est invalide.

    Sérialisé via un verrou inter-process (fcntl) pour éviter qu'un save
    concurrent home/away n'écrase l'autre side via un read-modify-write
    sur snapshot stale.
    """
    cleaned = _normalize_side_payload(payload)
    if cleaned is None:
        return None
    try:
        path = _path(event_id)
    except (TypeError, ValueError):
        return None
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    cleaned["saved_at_ms"] = int(ts_ms)
    side: str = cleaned["side"]

    with _file_lock(path):
        existing = load_lineup_override(event_id)
        existing[side] = cleaned
        file_data = {
            "event_id": _coerce_event_id(event_id),
            "updated_at_ms": int(ts_ms),
            **existing,
        }
        _atomic_write(path, file_data)
    return cleaned


def clear_lineup_override(event_id: int, side: Side | None = None) -> bool:
    """Reset : si side est None, supprime le fichier entier. Sinon reset le
    side donné. Retourne True si quelque chose a été modifié.

    Sérialisé via le même verrou inter-process que `save_lineup_override`.
    """
    try:
        path = _path(event_id)
    except (TypeError, ValueError):
        return False
    if not path.exists():
        return False
    if side is not None and side not in _VALID_SIDES:
        return False
    with _file_lock(path):
        if not path.exists():
            return False
        if side is None:
            try:
                path.unlink()
                return True
            except OSError:
                return False
        existing = load_lineup_override(event_id)
        if existing.get(side) is None:
            return False
        existing[side] = None
        if existing["home"] is None and existing["away"] is None:
            try:
                path.unlink()
            except OSError:
                return False
        else:
            _atomic_write(
                path,
                {
                    "event_id": _coerce_event_id(event_id),
                    "updated_at_ms": int(time.time() * 1000),
                    **existing,
                },
            )
    return True
