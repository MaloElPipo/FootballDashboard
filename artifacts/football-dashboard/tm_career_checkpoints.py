"""Campaign-scoped player checkpoints; no HTTP headers or credentials stored.

GitHub mode writes immutable compressed journal batches to a draft release.
Upload succeeds before old journals are compacted/deleted. A killed runner loses
at most the unpublished batch, not the earlier successes. Local mode uses fsync
and atomic rename and is intended for a persistent local disk.
"""
import gzip
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from tm_checkpoint_retention import CLOSED_MARKER

VERSION = 1


def valid_payload(data):
    # An explicit empty performance list is legitimate (no appearances).
    return (isinstance(data, dict) and isinstance(data.get("performance"), list)
            and all(isinstance(row, dict)
                    and isinstance(row.get("gameInformation"), dict)
                    and row["gameInformation"].get("gameId") is not None
                    for row in data["performance"]))


def valid_record(record, campaign, pid=None):
    try:
        stamp = datetime.fromisoformat(record["collected_at"])
        return (record["version"] == VERSION and record["campaign"] == campaign
                and re.fullmatch(r"[0-9]+", record["player_id"]) is not None
                and (pid is None or record["player_id"] == pid)
                and stamp.tzinfo is not None
                and stamp <= datetime.now(timezone.utc)
                and valid_payload(record["data"]))
    except (KeyError, TypeError, ValueError):
        return False


class Checkpoints:
    def __init__(self, root, campaign, remote=False):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", campaign):
            raise ValueError("Invalid campaign identifier")
        self.campaign = campaign
        self.folder = Path(root) / campaign
        self.folder.mkdir(parents=True, exist_ok=True)
        self.remote = remote
        self.tag = f"tm-checkpoints-{campaign}"
        self.lock = threading.RLock()
        self.pending = {}
        self.last_flush = time.monotonic()
        self.assets = []
        self.error = None
        started = time.monotonic()
        if remote:
            self._restore()
        self.restore_seconds = time.monotonic() - started

    def _gh(self, *args):
        # gh receives the workflow's scoped GH_TOKEN, never logged/read here.
        return subprocess.run(["gh", *args], check=True, capture_output=True,
                              text=True, timeout=60).stdout

    def _restore(self):
        # List first so authentication/network errors cannot masquerade as
        # a missing campaign and silently start an empty collection.
        releases = json.loads(self._gh("api", "--paginate", "--slurp",
                                      "repos/{owner}/{repo}/releases?per_page=100"))
        matching = [r for page in releases for r in page if r["tag_name"] == self.tag]
        if any(CLOSED_MARKER in (r.get("body") or "") for r in matching):
            raise RuntimeError("Campaign explicitly closed; start a new campaign")
        exists = bool(matching)
        if not exists:
            self._gh("release", "create", self.tag, "--draft", "--title", self.tag,
                     "--notes", "Private collection checkpoints; not public CSV exports.")
        self.assets = json.loads(self._gh("release", "view", self.tag,
                                         "--json", "assets"))["assets"]
        durable = {}
        with tempfile.TemporaryDirectory() as tmp:
            if self.assets:
                self._gh("release", "download", self.tag, "--dir", tmp,
                         "--pattern", "*.jsonl.gz")
            for path in Path(tmp).glob("*.jsonl.gz"):
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        record = json.loads(line)
                        if not valid_record(record, self.campaign):
                            raise ValueError("Invalid remote checkpoint")
                        pid = record["player_id"]
                        durable[pid] = max(durable.get(pid, ""), record["collected_at"])
                        current = self.get(record["player_id"])
                        if not current or current["collected_at"] < record["collected_at"]:
                            # Already durable in GitHub. Atomic local replacement
                            # is enough: after a crash the remote journal is replayed.
                            # New source responses still require fsync in put().
                            self._write(record, durable=False)
        # Local successes from a failed upload must be sent on the next flush,
        # even when they are reused without another source request.
        for path in self.folder.glob("*.json"):
            record = self.get(path.stem)
            if record and durable.get(path.stem, "") < record["collected_at"]:
                self.pending[path.stem] = record

    def get(self, pid):
        if not re.fullmatch(r"[0-9]+", pid):
            raise ValueError("Invalid player id")
        try:
            record = json.loads((self.folder / f"{pid}.json").read_text())
            return record if valid_record(record, self.campaign, pid) else None
        except (OSError, ValueError):
            return None

    def _write(self, record, durable=True):
        target = self.folder / f"{record['player_id']}.json"
        temporary = target.with_suffix(".tmp")
        with temporary.open("w") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
        os.replace(temporary, target)
        if not durable:
            return
        fd = os.open(self.folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def put(self, pid, data):
        record = dict(version=VERSION, campaign=self.campaign, player_id=pid,
                      collected_at=datetime.now(timezone.utc).isoformat(), data=data)
        if not valid_record(record, self.campaign, pid):
            raise ValueError("Invalid player response")
        with self.lock:
            if self.error:
                raise RuntimeError("Checkpoint storage unavailable") from self.error
            self._write(record)
            self.pending[pid] = record
            if len(self.pending) >= 25 or time.monotonic() - self.last_flush >= 15:
                self.flush()

    @contextmanager
    def periodic_flush(self):
        """Persist small batches even if all subsequent requests stall."""
        stop = threading.Event()
        def run():
            while not stop.wait(15):
                try:
                    self.flush()
                except Exception as exc:
                    self.error = exc
                    return
        thread = threading.Thread(target=run, daemon=True)
        if self.remote:
            thread.start()
        try:
            yield
            if self.error:
                raise RuntimeError("Checkpoint storage unavailable") from self.error
        finally:
            stop.set()
            if self.remote:
                thread.join()

    def flush(self):
        with self.lock:
            if not self.pending:
                return
            if self.remote:
                # Compact at 100 journals, well below GitHub's asset limit.
                # No overwrite/delete until the replacement is durable.
                compact = len(self.assets) >= 100
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"{uuid.uuid4().hex}.jsonl.gz"
                    with gzip.open(path, "wt", encoding="utf-8") as stream:
                        records = (self.get(p.stem) for p in self.folder.glob("*.json")) \
                            if compact else self.pending.values()
                        for record in records:
                            if record:
                                stream.write(json.dumps(record) + "\n")
                    self._gh("release", "upload", self.tag, str(path))
                    if compact:
                        for asset in self.assets:
                            self._gh("release", "delete-asset", self.tag,
                                     asset["name"], "--yes")
                        self.assets = []
                    self.assets.append({"name": path.name})
            self.pending.clear()
            self.last_flush = time.monotonic()

    def evidence(self, ids):
        records = [self.get(pid) for pid in ids]
        if not all(records):
            raise ValueError("Missing checkpoint evidence")
        stamps = [r["collected_at"] for r in records]
        return dict(campaign=self.campaign, response_version=VERSION,
                    collected_from=min(stamps), collected_through=max(stamps))
