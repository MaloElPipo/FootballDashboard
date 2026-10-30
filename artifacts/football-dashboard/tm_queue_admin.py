"""Offline-testable queue administration; never collects, dispatches or deletes."""
import argparse
import copy
import json
import os
from pathlib import Path
import time

from tm_collection_queue import GitHubStore, MAX_ATTEMPTS, BACKOFF, digest, zip_matches


def fingerprint(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def inspect(store, campaign, action, resolution, acknowledge_refusal=False, exports=None):
    queues = store.inventory()
    matches = [(rid, s) for rid, s in queues if s["campaign"] == campaign]
    if len(matches) != 1:
        raise ValueError("Expected exactly one existing tm-queue campaign; no legacy adoption")
    rid, state = matches[0]
    # Inspect all recorded runs, including an owner cleared by the observer.
    ids = {str(i["run_id"]) for i in state["leagues"].values() if i.get("run_id")}
    if state["owner"]:
        ids.add(str(state["owner"]))
    if state.get("last_owner"):
        ids.add(str(state["last_owner"]))
    runs = {}
    for run_id in sorted(ids):
        run = store.run(run_id)
        if str(run["id"]) != run_id:
            raise ValueError("Wrong run returned")
        runs[run_id] = {k: run.get(k) for k in
                        ("id", "status", "conclusion", "html_url", "run_attempt")}
    proofs = {}
    # Missing/unavailable evidence is never treated as a successful publication.
    fetch = None
    for code, item in state["leagues"].items():
        proofs[code] = {}
        for kind in ("all", "current"):
            expected = item.get("expected", {}).get(kind)
            if not expected:
                proofs[code][kind] = {"status": "no_expected_fingerprints"}
                continue
            try:
                if fetch is None:
                    fetch = store.public_fetcher()
                raw = fetch(f"data/{code}_{kind}.zip")
                proofs[code][kind] = {
                    "status": "match" if zip_matches(raw, expected) else "mismatch",
                    "archive_sha256": digest(raw),
                }
            except (OSError, RuntimeError, ValueError, KeyError):
                proofs[code][kind] = {"status": "unavailable"}
    report = {
        "release_id": rid, "queue": state, "runs": runs, "public_proofs": proofs,
        "action": action, "resolution": resolution,
        "acknowledge_refusal": acknowledge_refusal,
        "other_active_campaigns": sorted(s["campaign"] for _, s in queues
                                        if s["status"] == "active" and s["campaign"] != campaign),
        "warning": "No source request. Historical access latch is NOT changed.",
    }
    if action == "recover-publication":
        from tm_publication_recovery import inspect_exports
        report["recovery"] = (inspect_exports(state, exports) if exports else
                              {"status": "unavailable_or_invalid", "error": "Exports required"})
    report["confirmation"] = "ADMIN-" + fingerprint(report)
    return report


def transition(report, now, admin_run):
    state = copy.deepcopy(report["queue"])
    if state["status"] not in {"suspended", "closed"} and not (
            state["status"] == "complete" and state.get("access_hold")):
        raise ValueError("Only suspended or closed campaigns may be administered")
    if not report["resolution"].strip():
        raise ValueError("An operator resolution is required")
    if any(r["status"] != "completed" or not r["conclusion"]
           for r in report["runs"].values()):
        raise ValueError("A recorded run is active or uncertain; wait, do not interrupt")
    blocked = (state.get("access_hold", False) or state.get("reason") == "access_blocked"
               or any(i.get("reason") == "access_blocked"
                      for i in state["leagues"].values()))
    action = report["action"]
    if action not in {"close", "reconcile", "recover-publication"}:
        raise ValueError("Unknown operation")
    if action == "recover-publication":
        from tm_publication_recovery import candidates
        if state["status"] != "suspended" or not candidates(state):
            raise ValueError("Recovery requires suspended collected or publishing leagues")
        if report["acknowledge_refusal"]:
            raise ValueError("Recovery cannot lift a source refusal")
        if report.get("recovery", {}).get("status") != "validated":
            raise ValueError("Validated collection exports required")
    if action == "reconcile":
        if state["status"] == "closed" and not state.get("access_hold"):
            raise ValueError("Closed campaign cannot be reopened")
        if blocked and not report["acknowledge_refusal"]:
            raise ValueError("Transfermarkt refusal requires explicit acknowledgement")
        if report["other_active_campaigns"] and state["status"] == "suspended":
            raise ValueError("Another campaign is active")
    state["access_hold"] = bool(blocked and not report["acknowledge_refusal"])
    if action == "close":
        # Preserve every league as-is: closure is abandonment, never success.
        state["status"] = "closed"
    elif action == "reconcile" and state["status"] != "closed":
        for code, item in state["leagues"].items():
            proof = report["public_proofs"][code]
            if all(proof[k]["status"] == "match" for k in ("all", "current")):
                item.update(state="done", verified_at=now)
            elif item["state"] in {"running", "suspended"}:
                if item.get("expected"):
                    raise ValueError("Publication evidence must match before reconciliation")
                if item["attempts"] >= MAX_ATTEMPTS:
                    item["state"] = "exhausted"
                else:
                    # Unknown/interrupted attempt remains consumed; no immediate retry.
                    item.update(state="retry", due=max(item.get("due", 0),
                                now + BACKOFF[max(0, item["attempts"] - 1)]))
            elif item["state"] == "collected":
                raise ValueError("Unsealed collection: close or repair publication first")
            elif item["state"] == "publishing":
                raise ValueError("Publication evidence must match before reconciliation")
        state["status"] = ("complete" if all(i["state"] == "done"
                           for i in state["leagues"].values()) else "active")
    if state["owner"]:
        state["last_owner"] = state["owner"]
    state["owner"] = None
    state.setdefault("administration", []).append({
        "at": now, "run_id": admin_run, "action": action,
        "resolution": report["resolution"],
        "acknowledge_refusal": report["acknowledge_refusal"],
        "previous_owner": report["queue"]["owner"],
        "previous_status": report["queue"]["status"],
        "previous_reason": report["queue"].get("reason"),
        "confirmation": report["confirmation"],
        "runs": report["runs"], "public_proofs": report["public_proofs"],
    })
    if action == "recover-publication":
        state["administration"][-1]["recovery"] = report["recovery"]
    return state


def apply(store, report, confirmation, admin_run, now=None, exports=None, bundle=None):
    if confirmation != report["confirmation"]:
        raise ValueError("Confirmation does not match this simulation")
    fresh = inspect(store, report["queue"]["campaign"], report["action"],
                    report["resolution"], report["acknowledge_refusal"], exports)
    if fresh != report:
        raise ValueError("Evidence or queue changed; simulate and confirm again")
    state = transition(fresh, time.time() if now is None else now, admin_run)
    if report["action"] == "recover-publication":
        from tm_publication_recovery import prepare_recovery
        if bundle is None:
            raise ValueError("Recovery bundle destination required")
        state = prepare_recovery(state, exports, bundle, report["recovery"])
    store.save(report["release_id"], state)  # revision guard + mandatory read-back
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--action", choices=["close", "reconcile", "recover-publication"],
                        default="reconcile")
    parser.add_argument("--exports", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--resolution", default="")
    parser.add_argument("--acknowledge-refusal", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = GitHubStore()
    report = inspect(store, args.campaign, args.action, args.resolution,
                     args.acknowledge_refusal, args.exports)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as out:
            out.write("## Simulation administration TM\n\n````json\n"
                      + json.dumps(report, indent=2) + "\n````\n")
    if args.confirm:
        # Mutations are only exposed through the workflow sharing the collector lock.
        expected = os.getenv("GITHUB_REPOSITORY", "") + "/.github/workflows/tm-queue-admin.yml@"
        if (os.getenv("GITHUB_ACTIONS") != "true" or
                not os.getenv("GITHUB_WORKFLOW_REF", "").startswith(expected)):
            raise RuntimeError("Apply only through the locked tm-queue-admin workflow")
        apply(store, report, args.confirm, os.environ["GITHUB_RUN_ID"],
              exports=args.exports, bundle=args.bundle)
        print("Administration saved and read back successfully.")
    else:
        try:
            proposed = transition(report, time.time(), "simulation")
            print("Simulation only; proposed status:", proposed["status"])
        except ValueError as error:
            print("Simulation only; operation refused:", error)


if __name__ == "__main__":
    main()
