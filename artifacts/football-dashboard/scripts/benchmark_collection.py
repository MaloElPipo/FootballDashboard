"""Bounded live throughput experiment. Never writes production exports or checkpoints."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LEAGUES = ("cdn1", "pr1a", "clpd", "rsk1", "aus1")
SAMPLE = int(os.environ.get("BENCHMARK_SAMPLE", "20"))
PROFILE = os.environ.get("BENCHMARK_PROFILE", "compare")
if SAMPLE not in (20, 200) or PROFILE not in ("compare", "five", "full"):
    raise ValueError("Unsupported bounded benchmark settings")
FULL = PROFILE == "full"


def campaign(width, code):
    if FULL:
        run = os.environ["GITHUB_RUN_ID"]
        attempt = os.environ["GITHUB_RUN_ATTEMPT"]
        if not run.isdigit() or not attempt.isdigit():
            raise ValueError("Invalid run identity")
        return f"benchmark-full-{run}-{attempt}-{code}"
    return f"benchmark-{width}-{code}"


def expected_ids(code):
    sys.path.insert(0, str(ROOT))
    from tm_player_career import max_season_in_csv, load_player_meta_from_league_csv
    src = str(ROOT / "live/data/tm_scrap" / f"{code}.csv")
    season = max_season_in_csv(src)
    ids = list(load_player_meta_from_league_csv(src, {season, season - 1} if season > 0 else None))
    if not ids:
        raise ValueError(f"No expected players for {code}")
    return set(ids if FULL else ids[:SAMPLE])


def verify_remote(width, folder, results):
    """Restore from an empty directory; compare every saved record, no TM requests."""
    sys.path.insert(0, str(ROOT))
    from tm_career_checkpoints import Checkpoints, valid_record
    for result in results:
        code = result["league"]
        identity = campaign(width, code)
        fresh = folder / code / "cold-restore"
        assert not fresh.exists()
        began = time.monotonic()
        remote = Checkpoints(fresh, identity, remote=True)
        ids = expected_ids(code)
        for pid in ids:
            restored = remote.get(pid)
            local = json.loads((folder / code / "checkpoints" / identity / f"{pid}.json").read_text())
            assert valid_record(restored, identity, pid), f"Invalid remote record: {code}/{pid}"
            assert restored == local, f"Remote mismatch: {code}/{pid}"
        result["remote_restored_players"] = len(ids)
        result["remote_restore_seconds"] = round(time.monotonic() - began, 2)
        result["checkpoint_tag"] = remote.tag
        print("REMOTE_RESTORE_VERIFIED", code, len(ids), flush=True)


def run_profile(width, output):
    folder = output / str(width)
    folder.mkdir()
    pending = list(LEAGUES)
    active, results = {}, []
    started = time.monotonic()
    failure = False
    try:
        while pending or active:
            while pending and len(active) < width and not failure:
                code = pending.pop(0)
                log = (folder / f"{code}.log").open("w")
                exports = folder / code / "exports"
                command = [
                    sys.executable, "-u", "tm_player_career.py", "--league", code,
                    "--workers", "1",
                    "--budget-seconds", "1200" if FULL or SAMPLE == 200 else "240",
                    "--out-dir", str(exports),
                    "--checkpoint-dir", str(folder / code / "checkpoints"),
                    "--campaign", campaign(width, code),
                ]
                if FULL:
                    command.append("--checkpoint-remote")
                else:
                    command.extend(["--test", "--test-n", str(SAMPLE)])
                env = {**os.environ, "TM_CHECKPOINT_REMOTE": "github" if FULL else "",
                       "TM_CHECKPOINT_COMPACT_AFTER": "900"}
                proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                active[code] = (proc, log, time.monotonic(), exports)
            for code, (proc, log, began, exports) in list(active.items()):
                rc = proc.poll()
                if rc is None:
                    continue
                log.close()
                result = {"league": code, "returncode": rc, "seconds": round(time.monotonic() - began, 2)}
                if rc == 0:
                    try:
                        path = exports / f"{code}_summary.csv"
                        with path.open(encoding="utf-8-sig", newline="") as stream:
                            rows = list(csv.DictReader(stream))
                        if FULL:
                            ids = expected_ids(code)
                            assert len(rows) == len(ids) and {r["player_id"] for r in rows} == ids, "Incomplete league"
                            meta = json.loads((exports / f"{code}_collection.json").read_text())
                            assert meta["last_attempt"]["status"] == "success"
                            assert meta["last_success"]["campaign"] == campaign(width, code)
                            for suffix, digest in meta["last_success"]["sha256"].items():
                                assert hashlib.sha256((exports / f"{code}_{suffix}.csv").read_bytes()).hexdigest() == digest
                        else:
                            assert len(rows) == SAMPLE, "Incomplete sample"
                        result["players"] = len(rows)
                        result["sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                            for p in exports.glob("*.csv")}
                        assert len(result["sha256"]) == 4, "Missing CSV"
                    except Exception as exc:
                        result["validation_error"] = str(exc)
                        failure = True
                else:
                    failure = True
                results.append(result)
                del active[code]
                print("BENCHMARK_RESULT", width, json.dumps(result), flush=True)
            if failure:
                break
            time.sleep(0.5)
    finally:
        # No other worker continues traffic after a detected refusal/error.
        for proc, log, _, _ in active.values():
            proc.terminate()
        for code, (proc, log, began, _) in active.items():
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log.close()
            results.append({"league": code, "cancelled": True, "seconds": round(time.monotonic() - began, 2)})
        report = {"concurrency": width, "sample_per_league": "full" if FULL else SAMPLE, "leagues": list(LEAGUES),
                  "seconds": round(time.monotonic() - started, 2), "results": results,
                  "success": not failure and len(results) == len(LEAGUES) and not active}
        (folder / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main():
    output = Path(os.environ["RUNNER_TEMP"]) / "tm-parallel-benchmark"
    output.mkdir(exist_ok=False)
    reports = []
    for width in ((5,) if PROFILE in ("five", "full") else (1, 2, 3, 5)):
        if reports:
            time.sleep(120)
        report = run_profile(width, output)
        if FULL and report["success"]:
            try:
                verify_remote(width, output / str(width), report["results"])
                report["remote_restore_success"] = True
            except Exception as exc:
                report["remote_restore_success"] = False
                report["remote_restore_error"] = str(exc)
                report["success"] = False
            (output / str(width) / "report.json").write_text(json.dumps(report, indent=2))
        reports.append(report)
        (output / "report.json").write_text(json.dumps(reports, indent=2))
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write(f"- Parallelism {width}: {report['seconds']} s; success={report['success']}\n")
        if not report["success"]:
            print("BENCHMARK STOPPED: no automatic retry after source refusal or invalid data", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
