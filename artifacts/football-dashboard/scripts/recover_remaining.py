"""Supervised historical catch-up: same runner, verified exports, no publication."""
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = "recovery-2026-10-28"
REMAINING = "mex1 col1 pr1a clpd ec1n bra2 sa1 uae1 jap1 rsk1 aus1 csl mar1 egy1 alg1 sfa1".split()
SUFFIXES = ("summary", "career", "matches", "competitions_seen")


def verified(code):
    folder = ROOT / "live/data/tm_career"
    try:
        meta = json.loads((folder / f"{code}_collection.json").read_text())
        success = meta["last_success"]
        if meta["last_attempt"]["status"] != "success" or success["campaign"] != CAMPAIGN:
            return False
        for suffix in SUFFIXES:
            path = folder / f"{code}_{suffix}.csv"
            if hashlib.sha256(path.read_bytes()).hexdigest() != success["sha256"][suffix]:
                return False
            with path.open(newline="", encoding="utf-8-sig") as stream:
                rows = csv.reader(stream)
                if not next(rows, None):
                    return False
                if suffix == "summary" and not next(rows, None):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def git(*args, capture=False, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check,
                          capture_output=capture, text=True)


def persist(code):
    """One push, with read-only reconciliation if its response was lost."""
    paths = [f"live/data/tm_career/{code}_{s}.csv" for s in SUFFIXES]
    paths.append(f"live/data/tm_career/{code}_collection.json")
    git("add", "--force", "--", *paths)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    git("commit", "-m", f"chore(data): verified historical recovery {code}")
    git("pull", "--rebase", "origin", "main")
    expected = git("rev-parse", "HEAD", capture=True).stdout.strip()
    result = git("push", "origin", "HEAD:main", check=False)
    if result.returncode:
        actual = git("ls-remote", "origin", "refs/heads/main", capture=True).stdout.split()
        if not actual or actual[0] != expected:
            raise RuntimeError("Export persistence unconfirmed; stopping without another push")


def main():
    os.chdir(ROOT)
    git("config", "user.name", "github-actions[bot]")
    git("config", "user.email", "github-actions[bot]@users.noreply.github.com")
    # Leave margin for one final attempt, artifact upload and a single dispatch.
    deadline = time.monotonic() + 270 * 60
    for code in REMAINING:
        if verified(code):
            print(f"RECOVERY {code}: already verified in this campaign; skipped", flush=True)
            continue
        for attempt in range(1, 5):
            if time.monotonic() >= deadline:
                with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                    stream.write("continue=true\n")
                return 0
            print(f"RECOVERY {code}: attempt {attempt}/4, retained campaign checkpoints", flush=True)
            result = subprocess.run([
                sys.executable, "-u", "tm_player_career.py", "--league", code,
                "--campaign", CAMPAIGN, "--checkpoint-remote",
                "--workers", "1", "--budget-seconds", "1200",
            ])
            if result.returncode == 0:
                if not verified(code):
                    raise RuntimeError(f"{code}: collector exited successfully but export proof is invalid")
                persist(code)
                print(f"RECOVERY {code}: VERIFIED AND SAVED ON MAIN (not published)", flush=True)
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
                    stream.write(f"- **{code}** : collecte vérifiée et sauvegardée, publication différée.\n")
                break
            if result.returncode not in (76, 77):
                raise SystemExit(result.returncode)
            if attempt == 4:
                raise SystemExit(result.returncode)
            print(f"RECOVERY {code}: temporary stop {result.returncode}; cooldown 120 seconds", flush=True)
            time.sleep(120)
    print("RECOVERY COMPLETE: all remaining league exports verified", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
