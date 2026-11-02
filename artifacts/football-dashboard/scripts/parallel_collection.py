"""Five isolated collectors; only the coordinator writes the durable queue."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from tm_career_checkpoints import Checkpoints
from collection_metadata import read_metadata, fingerprints

WIDTH = 5
COOLDOWN = 120


def checkpoint_campaign(state, code):
    return state["leagues"][code].get("checkpoint_campaign", state["campaign"])


def seed_checkpoints(source, destination, campaign, ids=None):
    """Copy acquired responses, retaining collection dates, without source traffic."""
    destination.mkdir(parents=True, exist_ok=True)
    for record in source._all_records():
        if record and (ids is None or record["player_id"] in ids):
            target = destination / (record["player_id"] + ".json")
            if not target.exists():
                target.write_text(json.dumps({**record, "campaign": campaign}))


def collect(store, release_id, state, root, leagues, clock=time.time,
            sleep=time.sleep, run=subprocess.run, hours=3):
    from tm_collection_queue import suspend
    full = root / "live/data/tm_career"
    stop_at = clock() + hours * 3600
    state["parallel"] = True
    for item in state["leagues"].values():
        if item["state"] == "retry":
            item["due"] = min(item["due"], clock() + COOLDOWN)
    # One cold restore only. Isolated child campaigns retain the original dates.
    legacy = Checkpoints(root / "live/data/tm_checkpoints", state["campaign"], True)
    records = list(legacy._all_records())
    class Seed:
        def _all_records(self):
            return iter(records)
    seed = Seed()
    store.save(release_id, state)

    def worker(code):
        item = state["leagues"][code]
        squad = root / f"live/data/tm_scrap/{code}.csv"
        if not item["squad_done"] or not squad.exists():
            league = leagues[code]
            year = time.gmtime().tm_year
            p = run([sys.executable, "tm_league_scraper.py", "--comp", league["code_tm"],
                     "--slug", league["slug"], "--workers", "1", "--seasons",
                     f"{year-1},{year}", "--merge", "--out", str(squad)],
                    cwd=root, timeout=1200, check=False)
            if p.returncode:
                return p.returncode, False
        campaign = item["checkpoint_campaign"]
        folder = root / "live/data/tm_parallel_checkpoints" / code
        # Different local directory AND remote campaign per league.
        from tm_player_career import max_season_in_csv, load_player_meta_from_league_csv
        season = max_season_in_csv(str(squad))
        ids = set(load_player_meta_from_league_csv(
            str(squad), {season, season - 1} if season > 0 else None))
        if not ids:
            raise ValueError("Empty squad")
        seed_checkpoints(seed, folder / campaign, campaign, ids)
        p = run([sys.executable, "-u", "tm_player_career.py", "--league", code,
                 "--workers", "1", "--budget-seconds", "0",
                 "--campaign", campaign, "--checkpoint-dir", str(folder),
                 "--checkpoint-remote"], cwd=root, check=False,
                env={**os.environ, "TM_COLLECTION_DEADLINE": str(stop_at)})
        return p.returncode, True

    with concurrent.futures.ThreadPoolExecutor(max_workers=WIDTH) as pool:
        active = {}
        cooldown_until = 0
        while active or (state["status"] == "active" and clock() < stop_at):
            eligible = [c for c, i in state["leagues"].items()
                        if i["state"] in {"pending", "retry"} and i["due"] <= clock()]
            launch_batch = not active
            while (launch_batch and eligible and len(active) < WIDTH and state["status"] == "active"
                   and clock() < stop_at and clock() >= cooldown_until):
                code = eligible.pop(0)
                item = state["leagues"][code]
                item.update(state="running", attempts=item["attempts"] + 1,
                            started=clock(), run_id=state["owner"])
                item.setdefault("checkpoint_campaign", state["campaign"] + "-" + code)
                store.save(release_id, state)  # sole writer, before source traffic
                active[pool.submit(worker, code)] = code
            if not active:
                remaining = [i for i in state["leagues"].values()
                             if i["state"] in {"pending", "retry"}]
                if not remaining or state["status"] != "active" or clock() >= stop_at:
                    break
                sleep(min(5, max(0, stop_at - clock())))
                continue
            finished, _ = concurrent.futures.wait(
                active, timeout=2, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in finished:
                code = active.pop(future)
                item = state["leagues"][code]
                try:
                    rc, squad_done = future.result()
                    item["squad_done"] = squad_done
                    if rc == 0:
                        evidence = read_metadata(full, code).get("last_success", {})
                        if (evidence.get("campaign") != item["checkpoint_campaign"]
                                or evidence.get("sha256") != fingerprints(full, code)):
                            raise ValueError("Collection evidence mismatch")
                        item.update(state="collected", reason="success")
                    elif rc in (75, 76, 77):
                        # Retry intact checkpoints, never solve CAPTCHA. A new
                        # refusal ends that subprocess immediately.
                        item.update(state="retry", due=clock() + COOLDOWN,
                                    reason={75: "access_blocked", 76: "budget_exhausted",
                                            77: "temporary_network"}[rc])
                        if rc == 75:
                            cooldown_until = clock() + COOLDOWN
                    else:
                        raise RuntimeError(f"Unclassified collector exit {rc}")
                except Exception as exc:
                    item.update(state="suspended", reason="unclassified_failure")
                    suspend(state, "unclassified_failure")
                    print(f"COLLECTOR_ERROR {code}: {type(exc).__name__}: {exc}", flush=True)
                store.save(release_id, state)
                print(f"LEAGUE_RESULT {code} {item['state']}", flush=True)
            if finished and not active:
                cooldown_until = max(cooldown_until, clock() + COOLDOWN)
