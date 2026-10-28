"""Conservative, opt-in retention for private TM checkpoint releases.

Read-only outside the dedicated Actions workflow. Never contact Transfermarkt.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PREFIX = "tm-checkpoints-"
CLOSED_MARKER = "TM_CHECKPOINT_CLOSED_V1:"
WORKFLOW = ".github/workflows/tm-checkpoint-retention.yml"
COLLECTOR = ".github/workflows/scrape-weekly.yml"
POLICY = {"version": 1, "min_days": 30, "keep_latest": 3}


def timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Timezone required")
    return stamp


def closure(body):
    lines = [line for line in (body or "").splitlines()
             if line.startswith(CLOSED_MARKER)]
    if len(lines) != 1:
        raise ValueError("Missing or ambiguous closure")
    value = json.loads(lines[0][len(CLOSED_MARKER):])
    if value["no_resume_needed"] is not True or not value["reason"].strip():
        raise ValueError("Explicit closure required")
    timestamp(value["closed_at"])
    return value


class GitHub:
    def __init__(self, repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Explicit owner/repository required")
        self.repo = repo

    def api(self, path, method="GET", payload=None, paginate=False):
        args = ["gh", "api", "--hostname", "github.com", "--method", method,
                f"repos/{self.repo}/{path}"]
        if paginate:
            args += ["--paginate", "--slurp"]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(
            args, input=json.dumps(payload) if payload is not None else None,
            capture_output=True, text=True, timeout=120, check=True)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def releases(self):
        releases = []
        for page in self.api("releases?per_page=100", paginate=True):
            for release in page:
                if not release["tag_name"].startswith(PREFIX):
                    continue
                # The embedded assets array is not a reliable full inventory.
                release["assets"] = [
                    a for batch in self.api(
                        f"releases/{release['id']}/assets?per_page=100",
                        paginate=True) for a in batch]
                releases.append(release)
        return releases

    def active_runs(self):
        own = os.environ.get("GITHUB_RUN_ID")
        runs = []
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            for page in self.api(
                    f"actions/runs?status={status}&per_page=100", paginate=True):
                # GitHub caps filtered searches at 1000: refuse ambiguity.
                if page["total_count"] >= 1000:
                    raise RuntimeError("Too many active runs to verify safety")
                runs.extend(r for r in page["workflow_runs"]
                            if r["path"].split("@")[0] in (WORKFLOW, COLLECTOR)
                            and str(r["id"]) != own)
        return sorted({r["id"]: r for r in runs}.values(), key=lambda r: r["id"])

    def require_maintenance_lock(self):
        run_id = os.environ.get("GITHUB_RUN_ID", "")
        if (os.environ.get("GITHUB_ACTIONS") != "true" or not run_id.isdigit()
                or os.environ.get("GITHUB_REPOSITORY") != self.repo):
            raise RuntimeError("Mutation requires the dedicated locked Actions workflow")
        run = self.api(f"actions/runs/{run_id}")
        if (run["path"].split("@")[0] != WORKFLOW
                or run["status"] != "in_progress"
                or run["event"] != "workflow_dispatch"):
            raise RuntimeError("Not a running manual retention workflow")
        if self.active_runs():
            raise RuntimeError("Collection/maintenance active or queued; retry later")


def inventory(releases, repo, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=POLICY["min_days"])
    # Unknown/malformed data fails closed, never guesses age or status.
    ordered = sorted(releases, key=lambda r: timestamp(r["created_at"]), reverse=True)
    latest = {r["id"] for r in ordered[:POLICY["keep_latest"]]}
    rows = []
    for r in ordered:
        assets = sorted(r["assets"], key=lambda a: a["id"])
        changed = max(timestamp(s) for s in
                      [r["created_at"], r["updated_at"]]
                      + [a[k] for a in assets for k in ("created_at", "updated_at")])
        reason = "eligible"
        try:
            closed = closure(r.get("body"))
            closed_at = timestamp(closed["closed_at"])
        except (ValueError, KeyError, TypeError, AttributeError):
            closed_at = None
        if not r["draft"]:
            reason = "not-draft"
        elif not re.fullmatch(r"tm-checkpoints-[A-Za-z0-9_-]{1,100}", r["tag_name"]):
            reason = "invalid-campaign"
        elif closed_at is None:
            reason = "resumable-or-unknown"
        elif r["id"] in latest:
            reason = "latest-three"
        elif max(changed, closed_at) > cutoff:
            reason = "younger-than-30-days"
        rows.append({
            "id": r["id"], "campaign": r["tag_name"][len(PREFIX):],
            "draft": r["draft"], "created_at": r["created_at"],
            "last_changed": changed.isoformat(), "body": r.get("body"),
            "assets": [{"id": a["id"], "name": a["name"], "size": a["size"],
                        "updated_at": a["updated_at"]} for a in assets],
            "bytes": sum(a["size"] for a in assets),
            "reason": reason, "delete": reason == "eligible",
        })
    plan = {"repo": repo, "policy": POLICY, "campaigns": rows}
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    return {**plan, "confirmation": f"PURGE-{digest}",
            "total_bytes": sum(r["bytes"] for r in rows),
            "reclaimable_bytes": sum(r["bytes"] for r in rows if r["delete"]),
            "delete_count": sum(r["delete"] for r in rows)}


def close_campaign(gh, campaign, reason, confirmation):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", campaign):
        raise ValueError("Invalid campaign")
    if confirmation != f"CLOSE-{campaign}" or not reason.strip():
        raise ValueError("Closure needs CLOSE-<campaign> and an explicit reason")
    gh.require_maintenance_lock()
    matches = [r for r in gh.releases() if r["tag_name"] == PREFIX + campaign]
    if len(matches) != 1 or not matches[0]["draft"]:
        raise ValueError("Expected exactly one existing draft campaign")
    release = matches[0]
    if CLOSED_MARKER in (release.get("body") or ""):
        raise ValueError("Already closed or ambiguous closure; do not overwrite")
    marker = {"closed_at": datetime.now(timezone.utc).isoformat(),
              "no_resume_needed": True, "reason": reason.strip()}
    gh.api(f"releases/{release['id']}", method="PATCH",
           payload={"body": (release.get("body") or "") + "\n" +
                    CLOSED_MARKER + json.dumps(marker)})


def apply_plan(gh, confirmation):
    gh.require_maintenance_lock()
    plan = inventory(gh.releases(), gh.repo)
    if confirmation != plan["confirmation"]:
        raise ValueError("Inventory changed or confirmation missing: simulate again")
    for row in plan["campaigns"]:
        if not row["delete"]:
            continue
        gh.require_maintenance_lock()
        # Recheck full snapshot before every destructive call. A partial failure
        # stops; rerunning requires a fresh inventory and confirmation.
        fresh = inventory(gh.releases(), gh.repo)
        expected = next((r for r in fresh["campaigns"] if r["id"] == row["id"]), None)
        if expected != row:
            raise RuntimeError("Campaign changed since confirmation; stopped")
        gh.api(f"releases/{row['id']}", method="DELETE")
        print(f"Deleted closed campaign {row['campaign']}: {row['bytes']} bytes", flush=True)
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--operation", choices=("inventory", "close", "apply"),
                        default="inventory")
    parser.add_argument("--campaign", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gh = GitHub(args.repo)
    if args.operation == "close":
        close_campaign(gh, args.campaign, args.reason, args.confirm)
    elif args.operation == "apply":
        apply_plan(gh, args.confirm)
    report = inventory(gh.releases(), gh.repo)
    report["active_runs"] = [{"id": r["id"], "status": r["status"]}
                             for r in gh.active_runs()]
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
