"""Persistent collection evidence; never infer collection time from file dates."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SUFFIXES = ("summary", "career", "matches", "competitions_seen")
FAILURE_REASONS = {
    "missing_squad": "Effectif absent",
    "player_requests_failed": "Requêtes joueurs échouées",
    "write_failed": "Écriture échouée",
    "interrupted": "Collecte interrompue",
}


def read_metadata(folder, code):
    path = Path(folder) / f"{code}_collection.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_metadata(folder, code, data):
    path = Path(folder) / f"{code}_collection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def fingerprints(folder, code):
    result = {}
    for suffix in SUFFIXES:
        path = Path(folder) / f"{code}_{suffix}.csv"
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        result[suffix] = digest.hexdigest()
    return result


def start_attempt(folder, code):
    data = read_metadata(folder, code)
    data["last_attempt"] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "incomplete",
        "reason": "interrupted",
    }
    write_metadata(folder, code, data)


def fail_attempt(folder, code, reason):
    """Persist only a public reason code, never exception text or request data."""
    if reason not in FAILURE_REASONS:
        raise ValueError("Unknown collection failure reason")
    data = read_metadata(folder, code)
    attempt = data.get("last_attempt")
    if not isinstance(attempt, dict):
        return
    attempt.update(status="incomplete", reason=reason)
    write_metadata(folder, code, data)


def incomplete_attempt(folder, code):
    """Safe display fields; legacy/unknown reasons are intentionally not guessed."""
    attempt = read_metadata(folder, code).get("last_attempt")
    if not isinstance(attempt, dict) or attempt.get("status") != "incomplete":
        return None, None
    reason = attempt.get("reason")
    label = FAILURE_REASONS.get(reason) if isinstance(reason, str) else None
    try:
        stamp = datetime.fromisoformat(attempt["started_at"])
        if stamp.tzinfo is None:
            stamp = None
    except (KeyError, TypeError, ValueError):
        stamp = None
    return stamp, label


def complete_attempt(folder, code, evidence=None):
    data = read_metadata(folder, code)
    # Called only after validation and all four exports have finished.
    data["last_success"] = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "sha256": fingerprints(folder, code),
    }
    if evidence:
        data["last_success"].update(evidence)
        # Conservative freshness: never re-date cached responses as collected now.
        data["last_success"]["completed_at"] = evidence["collected_from"]
    data["last_attempt"]["status"] = "success"
    data["last_attempt"].pop("reason", None)
    write_metadata(folder, code, data)


def collection_evidence(folder, code):
    data = read_metadata(folder, code)
    success = data.get("last_success") or {}
    attempt = data.get("last_attempt")
    status = attempt.get("status") if isinstance(attempt, dict) else None
    unknown_status = "retained" if status == "incomplete" else "unknown"
    try:
        stamp = datetime.fromisoformat(success["completed_at"])
        if stamp.tzinfo is None or success["sha256"] != fingerprints(folder, code):
            return None, unknown_status
    except (OSError, ValueError, KeyError, TypeError):
        return None, unknown_status
    return stamp, "updated" if status == "success" else "retained"
