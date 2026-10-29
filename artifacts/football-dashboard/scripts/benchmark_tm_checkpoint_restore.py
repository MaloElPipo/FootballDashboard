"""Offline restore benchmark. No GitHub/Transfermarkt requests.

Run with --baseline pointing to the pre-change tm_career_checkpoints.py.
Large outputs belong outside Git (default: generated-artifacts/).
Each measurement runs in a fresh process; warm means the same local disk,
not a Python memory cache. Transport is a local copy, not measured WAN speed.
"""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import random
import resource
import shutil
import subprocess
import sys
import time
from unittest.mock import patch

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))


def load(path):
    spec = importlib.util.spec_from_file_location("bench_checkpoints", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Checkpoints


def generate(folder, target):
    rng = random.Random(48)
    path = folder / "legacy.jsonl.gz"
    count = 0
    # Independent match data defeats unrealistic compression of identical rows.
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0) as gz:
            while raw.tell() < target:
                count += 1
                rows = [
                    {"gameInformation": {"gameId": count * 1000 + i,
                                         "date": "2020-01-01"},
                     "competition": f"league-{count % 78}",
                     "minutes": rng.randrange(91),
                     "synthetic_match_detail": rng.randbytes(320).hex()}
                    for i in range(120)
                ]
                record = dict(version=1, campaign="bench", player_id=str(count),
                              collected_at="2020-01-01T00:00:00+00:00",
                              data={"performance": rows})
                gz.write((json.dumps(record) + "\n").encode())
    return count


def worker(args):
    cls = load(args.module)
    archive = Path(args.archive)
    transferred = [0]
    calls = [0]
    def gh(*parts):
        calls[0] += 1
        if parts[0] == "api":
            return json.dumps([[{"tag_name": "tm-checkpoints-bench"}]])
        if parts[1] == "view":
            return json.dumps({"assets": [{"name": archive.name, "id": "1",
                                          "size": archive.stat().st_size}]})
        if parts[1] == "download":
            dest = Path(parts[parts.index("--dir") + 1]) / archive.name
            shutil.copyfile(archive, dest)
            transferred[0] += archive.stat().st_size
            return ""
        raise AssertionError(f"Unexpected command: {parts[:2]}")
    started = time.perf_counter()
    with patch.object(cls, "_gh", side_effect=gh):
        store = cls(args.root, "bench", True)
        restored = time.perf_counter()
        for pid in range(1, args.players + 1):
            assert store.get(str(pid))["collected_at"] == "2020-01-01T00:00:00+00:00"
    elapsed = time.perf_counter() - started
    print(json.dumps({
        "restore_seconds": restored - started,
        "inventory_seconds": elapsed - (restored - started),
        "total_seconds": elapsed,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "download_bytes": transferred[0], "github_commands": calls[0],
        "local_bytes": sum(p.stat().st_size for p in Path(args.root).rglob("*")
                           if p.is_file()),
    }))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline")
    parser.add_argument("--output", default="generated-artifacts/tm-restore")
    parser.add_argument("--bytes", type=int, default=575938816)
    parser.add_argument("--players", type=int, default=600)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--module")
    parser.add_argument("--root")
    parser.add_argument("--archive")
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    if not args.baseline:
        parser.error("--baseline is required")
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    count = generate(folder, args.bytes)
    archive = folder / "legacy.jsonl.gz"
    results = {"records": count, "matches_per_record": 120,
               "league_labels": 78, "selected_players": min(args.players, count),
               "archive_bytes": archive.stat().st_size,
               "transport": "local file copy; no network; fresh subprocess per run",
               "measurements": {}}
    for label, module in (("before", Path(args.baseline).resolve()),
                          ("after", APP / "tm_career_checkpoints.py")):
        root = folder / label
        if root.exists():
            raise RuntimeError(f"Use a fresh output directory: {root}")
        for phase in ("cold", "warm", "warm_repeat"):
            output = subprocess.check_output([
                sys.executable, __file__, "--worker", "--module", str(module),
                "--root", str(root), "--archive", str(archive),
                "--players", str(min(args.players, count)),
            ], text=True)
            results["measurements"][f"{label}_{phase}"] = json.loads(output)
            print(label, phase, output.strip(), flush=True)
    (folder / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
