"""Opt-in real GitHub storage test. No scraper imports or source HTTP calls."""
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tm_career_checkpoints import Checkpoints


def require(value, message):
    if not value:
        raise AssertionError(message)


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True,
                          text=True, timeout=120).stdout


def release(store):
    return json.loads(gh("release", "view", store.tag, "--json", "isDraft,assets"))


def payload(pid):
    return {"performance": [{"gameInformation": {"gameId": f"synthetic-{pid}"}}],
            "test_only": True}


def retry_contract(campaign):
    """Execute the actual retry command, replacing only the gh executable.

    Never dispatch scrape-weekly: its publication/collection is out of scope.
    """
    source = Path(".github/workflows/scrape-weekly.yml").read_text()
    require("TM_CAMPAIGN_ID: ${{ inputs.campaign_id || format('run-{0}', github.run_id) }}" in source,
            "Campaign initialization contract changed")
    require(re.search(r"(?m)^      campaign_id:\s*$", source), "Missing dispatch input")
    match = re.search(r'gh workflow run "scrape-weekly.yml" \\\n(?:.*\\\n)*.*-f retry_round=1', source)
    require(match, "Cannot locate actual retry command")
    with tempfile.TemporaryDirectory() as tmp:
        executable = Path(tmp) / "gh"
        executable.write_text("#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        executable.chmod(0o755)
        env = {**os.environ, "PATH": tmp + os.pathsep + os.environ["PATH"],
               "TM_CAMPAIGN_ID": campaign, "FAILED_LEAGUES": "synthetic"}
        args = json.loads(subprocess.check_output(["bash", "-eu", "-c", match[0]],
                                                 env=env, text=True))
    require(f"campaign_id={campaign}" in args, "Retry lost campaign identity")
    if os.environ.get("GITHUB_OUTPUT"):
        forwarded = next(arg.split("=", 1)[1] for arg in args
                         if arg.startswith("campaign_id="))
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"campaign_id={forwarded}\n")
    print("PASS actual retry shell forwards campaign_id (dispatch intercepted)", flush=True)


def produce(root, campaign):
    retry_contract(campaign)
    store = Checkpoints(root, campaign, remote=True)
    require(release(store)["isDraft"], "Release must remain a draft")
    with store.periodic_flush():
        store.put("1", payload("1"))
        # Fewer than 25 records, no explicit flush: real 15-second timer.
        deadline = time.monotonic() + 110
        while time.monotonic() < deadline:
            with store.lock:
                if not store.pending:
                    break
            time.sleep(1)
        require(not store.pending and not store.error, "Periodic upload failed")
        require(len(release(store)["assets"]) == 1, "Missing periodic journal")
        stamp = store.get("1")["collected_at"]
        print(f"PASS periodic upload; original timestamp={stamp}", flush=True)
        # Store timestamp durably in synthetic payload for the next runner.
        store.put("2", {"performance": [], "original_stamp": stamp})
        store.flush()
        store.put("999", payload("999"))
        print("PASS abrupt exit with unpublished player 999; no context-manager exit", flush=True)
        os._exit(23)


def resume(root, campaign):
    require(not root.exists(), "Second runner must start without checkpoint files")
    store = Checkpoints(root, campaign, remote=True)
    require(release(store)["isDraft"], "Draft inaccessible with workflow token")
    require(store.get("1")["data"] == payload("1"), "Response not restored")
    require(store.get("1")["collected_at"] == store.get("2")["data"]["original_stamp"],
            "Restore changed response timestamp")
    require(store.get("999") is None, "Unpublished tail unexpectedly restored")
    print("PASS fresh runner restoration and preserved timestamp; pending tail lost", flush=True)

    # Seed real immutable assets to exercise the unmodified threshold of 100.
    with tempfile.TemporaryDirectory() as tmp:
        files = []
        record = store.get("1")
        for i in range(98):
            path = Path(tmp) / f"seed-{i:03d}.jsonl.gz"
            with gzip.open(path, "wt") as stream:
                stream.write(json.dumps(record) + "\n")
            files.append(str(path))
        gh("release", "upload", store.tag, *files)
    store.assets = release(store)["assets"]
    require(len(store.assets) == 100, "Compaction threshold not reached")
    original = store._gh
    old_names = {a["name"] for a in store.assets}
    deletes = []

    def fail_upload(*args):
        if args[:2] == ("release", "upload"):
            raise RuntimeError("Injected upload failure before remote write")
        require(args[:2] != ("release", "delete-asset"), "Deleted before upload")
        return original(*args)

    store._gh = fail_upload
    try:
        # put itself can flush if seeding took longer than the timer threshold.
        store.put("3", payload("3"))
        store.flush()
    except RuntimeError as exc:
        require(str(exc).startswith("Injected"), "Unexpected upload error")
    else:
        raise AssertionError("Expected upload failure")
    require({a["name"] for a in release(store)["assets"]} == old_names,
            "Failed upload removed old journals")
    print("PASS failed compaction upload preserves all 100 real assets", flush=True)

    def observe(*args):
        if args[:2] == ("release", "delete-asset"):
            if not deletes:
                current = {a["name"] for a in release(store)["assets"]}
                require(old_names <= current and len(current - old_names) == 1,
                        "Replacement not uploaded before first delete")
                name = (current - old_names).pop()
                with tempfile.TemporaryDirectory() as tmp:
                    gh("release", "download", store.tag, "--pattern", name, "--dir", tmp)
                    with gzip.open(Path(tmp) / name, "rt") as stream:
                        records = {r["player_id"]: r for r in map(json.loads, stream)}
                require(set(records) == {"1", "2", "3"}, "Replacement incomplete")
                for pid, record in records.items():
                    require(record == store.get(pid), "Replacement changed response")
            deletes.append(args[3])
        return original(*args)

    store._gh = observe
    store.flush()
    require(set(deletes) == old_names and len(deletes) == 100, "Incorrect deletion set")
    require(len(release(store)["assets"]) == 1, "Compaction did not leave one asset")
    with tempfile.TemporaryDirectory() as tmp:
        restored = Checkpoints(tmp, campaign, remote=True)
        require(all(restored.get(pid) == store.get(pid) for pid in ("1", "2", "3")),
                "Compacted snapshot cannot be restored")
    print("PASS real replacement downloaded and verified BEFORE deletion; compacted restore OK",
          flush=True)


def cleanup(campaign):
    tag = f"tm-checkpoints-{campaign}"
    releases = json.loads(gh("api", "--paginate", "--slurp",
                            "repos/{owner}/{repo}/releases?per_page=100"))
    matches = [r for page in releases for r in page if r["tag_name"] == tag]
    for item in matches:
        require(item["draft"], "Refuse to remove non-draft release")
        gh("api", "--method", "DELETE", f"repos/{{owner}}/{{repo}}/releases/{item['id']}")
    remaining = json.loads(gh("api", "--paginate", "--slurp",
                             "repos/{owner}/{repo}/releases?per_page=100"))
    require(not any(r["tag_name"] == tag for page in remaining for r in page),
            "Cleanup failed")
    # Draft creation should never materialize a Git tag.
    refs = json.loads(gh("api", f"repos/{{owner}}/{{repo}}/git/matching-refs/tags/{tag}"))
    require(not refs, "Unexpected tag left behind; manual inspection required")
    print("PASS cleanup: release/assets absent, no tag", flush=True)


if __name__ == "__main__":
    require(os.environ.get("GITHUB_ACTIONS") == "true", "GitHub runner required")
    require(os.environ.get("GH_REPO") == "MaloElPipo/ViveLaPiscine", "Unauthorized repository")
    campaign = os.environ["TM_CAMPAIGN_ID"]
    require(re.fullmatch(r"it-[0-9]+-[0-9]+", campaign), "Disposable campaign required")
    phase = sys.argv[1]
    root = Path(os.environ["RUNNER_TEMP"]) / "isolated-checkpoints"
    if phase == "cleanup":
        cleanup(campaign)
    elif phase == "produce":
        produce(root, campaign)
    elif phase == "resume":
        resume(root, campaign)
    else:
        raise ValueError("Unknown phase")
