"""Workflow entry point for the durable queue; tests inject all I/O."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tm_collection_queue import (GitHubStore, new_campaign, due_codes, begin,
                                 result, reconcile_owner, verify_publication,
                                 digest, zip_matches, suspend, guard_existing_archives)
from collection_metadata import read_metadata, fingerprints
from scripts.scrape_all_squads import select_leagues

FULL = ROOT / "live/data/tm_career"
CURRENT = ROOT / "live/data/tm_career_current"
ACCESS_FILE = ROOT / "tm_collection_access.json"


def require_access_clearance():
    """Tracked migration latch: absence of a remote queue is NOT permission.

    Only an explicit, reviewed operator change may reconcile the historical
    refusal. Missing/corrupt/unknown state fails closed, including fresh IDs.
    """
    try:
        clearance = json.loads(ACCESS_FILE.read_text())
        reviewed = datetime.fromisoformat(clearance.get("reviewed_at") or "")
        allowed = (clearance["version"] == 1
                   and clearance["status"] == "reconciled"
                   and isinstance(clearance.get("resolution"), str)
                   and bool(clearance["resolution"].strip())
                   and reviewed.tzinfo is not None)
    except (OSError, ValueError, KeyError, TypeError):
        allowed = False
    if not allowed:
        raise RuntimeError(
            "Historical Transfermarkt refusal is not reconciled. "
            "No new campaign or source session authorized; see docs/tm-durable-queue.md")


def prepare(store, run_id, campaign="", selection="", create=False, refresh=True):
    require_access_clearance()
    queues = store.inventory()
    # Successful leagues remain independently verifiable even after a refusal
    # elsewhere. A suspended campaign still never authorizes source traffic.
    for release_id, state in queues:
        if state["status"] == "suspended" and any(
                i["state"] == "publishing" for i in state["leagues"].values()):
            verify_publication(state, store.public_fetcher(), time.time())
            store.save(release_id, state)
    # A refusal is a global stop, including future Mondays/new campaign IDs.
    if any(s["status"] == "suspended" or s.get("access_hold") for _, s in queues):
        raise RuntimeError("Campaign suspended; explicit operator reconciliation required")
    active = [(i, s) for i, s in queues if s["status"] == "active"]
    if len(active) > 1:
        raise RuntimeError("Multiple active campaigns; no source traffic")
    if campaign:
        matches = [(i, s) for i, s in queues if s["campaign"] == campaign]
        if not matches:
            # Legacy campaigns have no queue/provenance for attempts. In particular
            # do not restart the existing 47-league catch-up stopped on CAPTCHA.
            raise RuntimeError("Unknown campaign; automatic legacy adoption forbidden")
        if active and active[0][1]["campaign"] != campaign:
            raise RuntimeError("Another campaign is active")
        active = matches
    if active:
        release_id, state = active[0]
        if state["status"] != "active":
            return None
        if state["owner"]:
            # Same-run retries/re-runs are not new ownership grants.
            if state["owner"] == run_id:
                return None
            available = reconcile_owner(state, store.run(state["owner"]))
            store.save(release_id, state)
            if not available:
                return None
        if any(i["state"] == "publishing" for i in state["leagues"].values()):
            verify_publication(state, store.public_fetcher(), time.time())
            store.save(release_id, state)
        if not due_codes(state, time.time()):
            return None
    elif create:
        if any(s["campaign"] == "run-" + run_id for _, s in queues):
            return None  # GitHub rerun of a completed campaign, not a new week
        codes = [l["code_tm"].lower() for l in select_leagues(selection)]
        state = new_campaign("run-" + run_id, codes, refresh)
        release_id = store.create(state)
    else:
        return None
    state["owner"] = run_id
    store.save(release_id, state)  # confirmation BEFORE browser/session/network
    return release_id, state


def load_owned(store, campaign, run_id):
    matches = [(i, s) for i, s in store.inventory() if s["campaign"] == campaign]
    if len(matches) != 1 or matches[0][1]["owner"] != run_id:
        raise RuntimeError("Queue ownership not established")
    return matches[0]


def classify(exit_code, metadata):
    if exit_code == 75:
        return "access_blocked"
    if exit_code == 76:
        return "budget_exhausted"
    if exit_code == 77:
        return "temporary_network"
    # Unknown exits/storage errors/invalid data are NOT network errors.
    return "success" if exit_code == 0 else "unclassified_failure"


def collect(store, release_id, state, run=subprocess.run, clock=time.time):
    require_access_clearance()
    started = clock()
    leagues = {l["code_tm"].lower(): l for l in select_leagues("")}
    for code in due_codes(state, clock()):
        if clock() - started >= 3 * 3600:
            break  # fresh ownership next tick; not an attempt or a failure
        begin(state, code, clock())
        store.save(release_id, state)
        item = state["leagues"][code]
        squad = ROOT / f"live/data/tm_scrap/{code}.csv"
        if not item["squad_done"] or not squad.exists():
            league = leagues[code]
            year = time.gmtime().tm_year
            cmd = [sys.executable, "tm_league_scraper.py", "--comp", code,
                   "--slug", league["slug"], "--workers", "2",
                   "--seasons", f"{year-1},{year}", "--merge", "--out", str(squad)]
            proc = run(cmd, cwd=ROOT, timeout=1200, check=False)
            if proc.returncode:
                result(state, code, classify(proc.returncode, {}), clock())
                store.save(release_id, state)
                if state["status"] != "active":
                    break
                continue
            item["squad_done"] = True
            store.save(release_id, state)
        proc = run([sys.executable, "tm_player_career.py", "--league", code,
                    "--workers", "2", "--budget-seconds", "240"],
                   cwd=ROOT, timeout=1800, check=False)
        outcome = classify(proc.returncode, read_metadata(FULL, code))
        if outcome == "success":
            evidence = read_metadata(FULL, code).get("last_success", {})
            if (evidence.get("campaign") != state["campaign"]
                    or evidence.get("sha256") != fingerprints(FULL, code)):
                outcome = "invalid_evidence"
        result(state, code, outcome, clock())
        store.save(release_id, state)
        if state["status"] != "active":
            break


def seal(store, release_id, state, full=FULL, current=CURRENT,
         build=ROOT / "gh_pages_build/data"):
    """Persist intended CSV fingerprints BEFORE publishing, not build timestamps."""
    for code, item in state["leagues"].items():
        if item["state"] != "collected":
            continue
        evidence = read_metadata(full, code).get("last_success", {})
        if (evidence.get("campaign") != state["campaign"]
                or evidence.get("sha256") != fingerprints(full, code)):
            raise ValueError("Collection evidence mismatch")
        from scripts.make_current_season import detect_current_season, filter_csv_by_season
        season = detect_current_season(full / f"{code}_career.csv")
        if season is None:
            raise ValueError("Current season cannot be validated")
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in ("career", "matches"):
                name = f"{code}_{suffix}.csv"
                expected_csv = Path(tmp) / name
                filter_csv_by_season(full / name, expected_csv, season)
                if expected_csv.read_bytes() != (current / name).read_bytes():
                    raise ValueError("Stale or incorrect current-season CSV")
        expected = {
            "all": {f"{code}_{s}.csv": h for s, h in evidence["sha256"].items()},
            "current": {f"{code}_{s}.csv": digest((current / f"{code}_{s}.csv").read_bytes())
                        for s in ("career", "matches")},
        }
        for kind, hashes in expected.items():
            if not zip_matches((build / f"{code}_{kind}.zip").read_bytes(), hashes):
                raise ValueError("Built ZIP does not match validated CSV")
        item.update(state="publishing", expected=expected, publication_started=time.time())
        store.save(release_id, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "collect", "seal", "finish", "guard"])
    args = parser.parse_args()
    store = GitHubStore()
    run_id = os.environ["GITHUB_RUN_ID"]
    if args.command == "guard":
        guard_existing_archives(store.api("repos/{owner}/{repo}/git/trees/gh-pages?recursive=1"),
                                ROOT / "gh_pages_build")
        return
    if args.command == "prepare":
        prepared = prepare(store, run_id, os.getenv("REQUESTED_CAMPAIGN", ""),
                           os.getenv("REQUESTED_LEAGUES", ""),
                           os.getenv("ALLOW_CREATE") == "true",
                           os.getenv("REFRESH_SQUADS") != "false")
        # Observation-only ticks also expose progress/exhaustion without scraping.
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
            for _, state in store.inventory():
                if state["status"] == "complete":
                    continue
                summary.write(f"\n## Campagne {state['campaign']} — {state['status']}\n")
                for code, item in state["leagues"].items():
                    summary.write(f"- {code}: {item['state']}, "
                                  f"{item['attempts']}/4 tentative(s), "
                                  f"{item.get('reason', '')}\n")
        with open(os.environ["GITHUB_OUTPUT"], "a") as output:
            output.write(f"ready={'true' if prepared else 'false'}\n")
            if prepared:
                output.write(f"campaign={prepared[1]['campaign']}\n")
        return
    release_id, state = load_owned(store, os.environ["TM_CAMPAIGN_ID"], run_id)
    if args.command == "collect":
        collect(store, release_id, state)
    elif args.command == "seal":
        seal(store, release_id, state)
    else:
        # No rescraping if a publish failed; only public-byte checks on next tick.
        # Leave owner set: next tick reconciles the actual terminal run outcome.
        if any(i["state"] == "running" for i in state["leagues"].values()):
            suspend(state, "interrupted_attempt")
        store.save(release_id, state)
        summary = [f"## Campagne {state['campaign']}", f"État : {state['status']}",
                   "| Ligue | État | Tentatives | Motif |", "|---|---|---:|---|"]
        for code, item in state["leagues"].items():
            summary.append(f"| {code} | {item['state']} | {item['attempts']} | "
                           f"{item.get('reason', '')} |")
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write("\n".join(summary) + "\n")
        if state["status"] == "suspended" or any(
                i["state"] == "exhausted" for i in state["leagues"].values()):
            raise RuntimeError("Campaign needs operator attention")


if __name__ == "__main__":
    main()
