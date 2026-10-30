"""Durable campaign queue. No scraping or dispatch on import.

All writers run under the SAME GitHub workflow concurrency group. A release
body is the atomic state record; read-back is mandatory before source traffic.
Unknown writes/runner interruptions fail closed, never acquire a new session.
"""
import hashlib
import io
import json
import re
import subprocess
import time
import urllib.request
import zipfile

PREFIX = "tm-queue-"
MAX_ATTEMPTS = 4
BACKOFF = (3600, 7200, 14400)
PUBLICATION_LIMIT = 48 * 3600
STATES = {"pending", "running", "retry", "collected", "publishing", "done",
          "exhausted", "suspended"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def new_campaign(campaign, codes, refresh=True):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", campaign):
        raise ValueError("Invalid campaign")
    codes = list(dict.fromkeys(codes))
    if not codes or any(not re.fullmatch(r"[a-z0-9_-]+", c) for c in codes):
        raise ValueError("Invalid leagues")
    return {"version": 1, "campaign": campaign, "revision": 0,
            "status": "active", "owner": None, "refresh": refresh,
            "leagues": {c: {"state": "pending", "attempts": 0,
                            "due": 0, "squad_done": not refresh} for c in codes}}


def validate(state):
    if state["version"] != 1 or state["status"] not in {"active", "suspended", "complete", "closed"}:
        raise ValueError("Invalid queue state")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", state["campaign"]):
        raise ValueError("Invalid campaign")
    if not state["leagues"]:
        raise ValueError("Empty queue")
    for code, item in state["leagues"].items():
        if not re.fullmatch(r"[a-z0-9_-]+", code) or item["state"] not in STATES:
            raise ValueError("Invalid league state")
        if not 0 <= item["attempts"] <= MAX_ATTEMPTS:
            raise ValueError("Invalid attempt count")
    return state


def due_codes(state, now):
    if state["status"] != "active":
        return []
    return [c for c, r in state["leagues"].items()
            if r["state"] in {"pending", "retry"} and r["due"] <= now
            and r["attempts"] < MAX_ATTEMPTS]


def suspend(state, reason):
    state["status"] = "suspended"
    state["reason"] = reason
    if reason == "access_blocked":
        state["access_hold"] = True


def begin(state, code, now):
    if code not in due_codes(state, now):
        raise ValueError("League not eligible")
    item = state["leagues"][code]
    item.update(state="running", attempts=item["attempts"] + 1,
                started=now, run_id=state["owner"])


def result(state, code, outcome, now):
    item = state["leagues"][code]
    if item["state"] != "running":
        raise ValueError("No active attempt")
    item["reason"] = outcome
    if outcome == "success":
        item["state"] = "collected"
    elif outcome == "access_blocked":
        item["state"] = "suspended"
        suspend(state, "access_blocked")
    elif outcome in {"budget_exhausted", "temporary_network"}:
        if item["attempts"] >= MAX_ATTEMPTS:
            item["state"] = "exhausted"
        else:
            item.update(state="retry", due=now + BACKOFF[item["attempts"] - 1])
    else:
        item["state"] = "suspended"
        suspend(state, outcome)


def reconcile_owner(state, run):
    """Never interpret a watcher timeout as the end of the source process."""
    if not state["owner"]:
        return True
    if str(run["id"]) != state["owner"]:
        raise ValueError("Wrong run")
    if run["status"] != "completed":
        return False
    if run.get("conclusion") in {"cancelled", "timed_out", "action_required", "stale"}:
        suspend(state, "run_" + run["conclusion"])
    elif any(i["state"] == "running" for i in state["leagues"].values()):
        suspend(state, "interrupted_attempt")
    elif any(i["state"] == "collected" for i in state["leagues"].values()):
        suspend(state, "publication_not_prepared")
    state["last_owner"] = state["owner"]
    state["owner"] = None
    return state["status"] == "active"


def zip_matches(raw, expected):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            return (len(names) == len(set(names)) and set(names) == set(expected)
                    and all(digest(archive.read(n)) == h for n, h in expected.items()))
    except (ValueError, OSError, zipfile.BadZipFile, RuntimeError):
        return False


def guard_existing_archives(tree, build):
    """Do not erase acquired league archives during a partial checkout/build."""
    if tree.get("truncated"):
        raise ValueError("Cannot verify complete public inventory")
    previous = {entry["path"] for entry in tree["tree"]
                if re.fullmatch(r"data/[a-z0-9_-]+_(all|current)\.zip", entry["path"])}
    missing = sorted(p for p in previous if not (build / p).is_file())
    if missing:
        raise ValueError("Previously public league archives missing from build: " + ", ".join(missing))


def verify_publication(state, fetch, now):
    """Both archives must contain EXACTLY the validated CSV bytes."""
    for code, item in state["leagues"].items():
        if item["state"] != "publishing":
            continue
        try:
            valid = all(zip_matches(fetch(f"data/{code}_{kind}.zip"), hashes)
                        for kind, hashes in item["expected"].items())
        except (OSError, TimeoutError):
            valid = False
        if valid:
            item.update(state="done", verified_at=now)
        elif now - item["publication_started"] >= PUBLICATION_LIMIT:
            item.update(state="suspended", reason="publication_timeout")
            suspend(state, "publication_timeout")
    if all(i["state"] == "done" for i in state["leagues"].values()):
        state["status"] = "complete"


class GitHubStore:
    """No POST dispatch, no retries of mutations, no local-state fallback."""
    def api(self, path, method="GET", data=None):
        cmd = ["gh", "api", path, "--method", method]
        if data is not None:
            cmd += ["--input", "-"]
        proc = subprocess.run(cmd, input=json.dumps(data) if data is not None else None,
                              text=True, capture_output=True, timeout=90)
        if proc.returncode:
            raise RuntimeError("GitHub state unavailable; no source request authorized")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def inventory(self):
        releases = []
        for page in range(1, 101):
            batch = self.api(f"repos/{{owner}}/{{repo}}/releases?per_page=100&page={page}")
            releases.extend(batch)
            if len(batch) < 100:
                break
        else:
            raise RuntimeError("Incomplete queue inventory")
        queues = []
        for release in releases:
            if release["tag_name"].startswith(PREFIX):
                if not release["draft"]:
                    raise ValueError("Queue must remain private draft")
                state = validate(json.loads(release["body"]))
                if release["tag_name"] != PREFIX + state["campaign"]:
                    raise ValueError("Queue identity mismatch")
                queues.append((release["id"], state))
        if len({s["campaign"] for _, s in queues}) != len(queues):
            raise ValueError("Duplicate campaigns; operator reconciliation required")
        return queues

    def create(self, state):
        release = self.api("repos/{owner}/{repo}/releases", "POST", {
            "tag_name": PREFIX + state["campaign"], "draft": True,
            "name": PREFIX + state["campaign"], "body": json.dumps(state)})
        self.confirm(release["id"], state)
        return release["id"]

    def confirm(self, release_id, state):
        release = self.api(f"repos/{{owner}}/{{repo}}/releases/{release_id}")
        if (release["tag_name"] != PREFIX + state["campaign"]
                or not release["draft"] or json.loads(release["body"]) != state):
            raise RuntimeError("Queue write not confirmed")

    def save(self, release_id, state):
        validate(state)
        # Concurrency group is mandatory, plus reject stale/duplicate writers.
        current = self.api(f"repos/{{owner}}/{{repo}}/releases/{release_id}")
        if json.loads(current["body"])["revision"] != state["revision"]:
            raise RuntimeError("Stale queue writer")
        state["revision"] += 1
        body = json.dumps(state)
        if len(body.encode()) > 120000:
            raise RuntimeError("Queue too large")
        self.api(f"repos/{{owner}}/{{repo}}/releases/{release_id}", "PATCH", {
            "tag_name": PREFIX + state["campaign"], "draft": True, "body": body})
        self.confirm(release_id, state)

    def run(self, run_id):
        return self.api(f"repos/{{owner}}/{{repo}}/actions/runs/{int(run_id)}")

    def public_fetcher(self):
        # Actual Pages URL, not a guessed owner/repo URL.
        url = self.api("repos/{owner}/{repo}/pages")["html_url"].rstrip("/") + "/"
        if not url.startswith("https://"):
            raise ValueError("Expected HTTPS Pages URL")

        def fetch(path):
            request = urllib.request.Request(url + path + f"?queue={int(time.time())}",
                                             headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        return fetch
