"""Prepare publication from proven exports only; no source or remote writes."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from collection_metadata import SUFFIXES, collection_evidence, fingerprints, read_metadata
from scripts.collection_queue import seal
from scripts.make_current_season import detect_current_season, filter_csv_by_season
from tm_collection_queue import digest, zip_matches


def candidates(state):
    return [code for code, item in state["leagues"].items()
            if (item["state"] == "collected" and not item.get("expected"))
            or (item["state"] == "publishing" and item.get("expected"))]


def restore_and_build(state, source, destination):
    """Restore into isolated staging; never overwrite retained production exports.

    All leagues are checked before seal is called. Missing or stale exports are
    an explicit refusal, not permission to fall back to caches or recollect.
    """
    source, destination = Path(source), Path(destination)
    full, current, build = (destination / p for p in ("full", "current", "data"))
    for folder in (full, current, build):
        folder.mkdir(parents=True, exist_ok=True)
    proofs = {}
    for code in candidates(state):
        # Do not consume a possibly half-written export transaction.
        if (source / f".{code}.pending").exists():
            raise ValueError(f"{code}: unresolved export transaction")
        for suffix in (*SUFFIXES, "collection"):
            name = f"{code}_{suffix}.{'json' if suffix == 'collection' else 'csv'}"
            shutil.copyfile(source / name, full / name)
        evidence = read_metadata(full, code).get("last_success", {})
        stamp, _ = collection_evidence(full, code)
        if (stamp is None or evidence.get("campaign") != state["campaign"]
                or evidence.get("sha256") != fingerprints(full, code)):
            raise ValueError(f"{code}: collection evidence mismatch or missing date")
        season = detect_current_season(full / f"{code}_career.csv")
        if season is None:
            raise ValueError(f"{code}: current season cannot be validated")
        for suffix in ("career", "matches"):
            name = f"{code}_{suffix}.csv"
            filter_csv_by_season(full / name, current / name, season)
        archives = {}
        for kind, folder, suffixes in (("all", full, SUFFIXES),
                                       ("current", current, ("career", "matches"))):
            archive_path = build / f"{code}_{kind}.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                for suffix in suffixes:
                    name = f"{code}_{suffix}.csv"
                    # Fixed ZIP timestamps make confirmations stable across runners.
                    info = zipfile.ZipInfo(name)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, (folder / name).read_bytes())
            raw = archive_path.read_bytes()
            item = state["leagues"][code]
            if item["state"] == "publishing":
                expected = item["expected"]
                if (set(expected) != {"all", "current"}
                        or not zip_matches(raw, expected[kind])):
                    raise ValueError(f"{code}: rebuilt ZIP differs from sealed fingerprints")
            archives[kind] = digest(raw)
        proofs[code] = {"collection": evidence, "archives": archives,
                        "metadata_sha256": digest((full / f"{code}_collection.json").read_bytes())}
    return proofs


def inspect_exports(state, source):
    try:
        with tempfile.TemporaryDirectory() as tmp:
            return {"status": "validated", "leagues": restore_and_build(state, source, tmp)}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"status": "unavailable_or_invalid", "error": str(error)}


def prepare_recovery(state, source, destination, expected):
    actual = {"status": "validated",
              "leagues": restore_and_build(state, source, destination)}
    if actual != expected:
        raise ValueError("Restored exports changed; simulate and confirm again")

    class StagingStore:
        def save(self, release_id, value):
            pass  # Validate every league before the single remote state write.

    staged = copy.deepcopy(state)
    root = Path(destination)
    seal(StagingStore(), None, staged, full=root / "full",
         current=root / "current", build=root / "data")
    (root / "recovery.json").write_text(json.dumps(actual, indent=2) + "\n")
    return staged
