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
from tm_checkpoint_index import RemoteIndex, partition_bounds

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
    def __init__(self, root, campaign, remote=False, partitioned=False):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", campaign):
            raise ValueError("Invalid campaign identifier")
        self.campaign = campaign
        self.folder = Path(root) / campaign
        self.folder.mkdir(parents=True, exist_ok=True)
        self.remote = remote
        # Explicit opt-in for writing/migrating; reading v2 is automatic.
        self.partitioned = partitioned
        self.tag = f"tm-checkpoints-{campaign}"
        self.lock = threading.RLock()
        self.pending = {}
        self.last_flush = time.monotonic()
        self.assets = []
        self.error = None
        self.index = None
        self._imported = set()
        self.restore_bytes = 0
        self.restore_downloads = 0
        self.restore_cached_assets = 0
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
        self.index = RemoteIndex(self.folder)
        self._import_assets(legacy_only=True)
        # Local successes from a failed upload must be sent on the next flush.
        for path in self.folder.glob("*.json"):
            record = self._local_get(path.stem)
            self._import_assets(pid=path.stem)
            durable = self.index.get(path.stem)
            if record and (not durable or durable["collected_at"] < record["collected_at"]):
                self.pending[path.stem] = record

    def _import_assets(self, pid=None, legacy_only=False):
        """Legacy journals are eager; ranged journals are fetched on demand."""
        with tempfile.TemporaryDirectory() as tmp:
            for asset in self.assets:
                if not asset["name"].endswith(".jsonl.gz"):
                    continue
                bounds = partition_bounds(asset["name"])
                if bounds and (legacy_only or (
                        pid is not None and not bounds[0] <= int(pid) <= bounds[1])):
                    continue
                identity = self.index.identity(asset)
                if identity in self._imported:
                    continue
                if self.index.contains(asset):
                    self.restore_cached_assets += 1
                    self._imported.add(identity)
                    continue
                # Exact asset, never download every journal again. The index
                # receipt is committed atomically with all validated records.
                self._gh("release", "download", self.tag, "--dir", tmp,
                         "--pattern", asset["name"])
                path = Path(tmp) / asset["name"]
                self.restore_bytes += path.stat().st_size
                self.restore_downloads += 1
                def records():
                    with gzip.open(path, "rt", encoding="utf-8") as stream:
                        for line in stream:
                            record = json.loads(line)
                            if not valid_record(record, self.campaign):
                                raise ValueError("Invalid remote checkpoint")
                            if bounds and not bounds[0] <= int(record["player_id"]) <= bounds[1]:
                                raise ValueError("Checkpoint outside partition bounds")
                            yield record
                self.index.ingest(asset, records())
                self._imported.add(identity)
                path.unlink()

    def get(self, pid):
        if not re.fullmatch(r"[0-9]+", pid):
            raise ValueError("Invalid player id")
        if self.index:
            with self.lock:
                self._import_assets(pid=pid)
        local = self._local_get(pid)
        remote = self.index.get(pid) if self.index else None
        if remote and not valid_record(remote, self.campaign, pid):
            raise ValueError("Invalid indexed checkpoint")
        if remote and (not local or remote["collected_at"] > local["collected_at"]):
            return remote
        return local

    def _local_get(self, pid):
        try:
            record = json.loads((self.folder / f"{pid}.json").read_text())
            return record if valid_record(record, self.campaign, pid) else None
        except (OSError, ValueError):
            return None

    def _all_records(self):
        # The index contains ALL leagues, even when this process only calls
        # get() for a small subset. Never compact from that subset alone.
        if self.index:
            self._import_assets()
        local_ids = {p.stem for p in self.folder.glob("*.json")}
        if self.index:
            for pid in self.index.ids():
                yield self.get(pid)
                local_ids.discard(pid)
        for pid in local_ids:
            yield self.get(pid)

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
                if self.partitioned or any(partition_bounds(a["name"]) for a in self.assets
                                           if a["name"].endswith(".jsonl.gz")):
                    self._publish_partitions(compact)
                    self.pending.clear()
                    self.last_flush = time.monotonic()
                    return
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / f"{uuid.uuid4().hex}.jsonl.gz"
                    with gzip.open(path, "wt", encoding="utf-8") as stream:
                        records = self._all_records() if compact else self.pending.values()
                        for record in records:
                            if record:
                                stream.write(json.dumps(record) + "\n")
                    self._gh("release", "upload", self.tag, str(path))
                    if compact:
                        for asset in self.assets:
                            if asset["name"].endswith(".jsonl.gz"):
                                self._gh("release", "delete-asset", self.tag,
                                         asset["name"], "--yes")
                        self.assets = []
                    self.assets.append({"name": path.name})
            self.pending.clear()
            self.last_flush = time.monotonic()

    def compact_partitioned(self):
        """Explicit migration operation; caller must hold the campaign run lock.

        No release metadata changes: closure and retention policy stay intact.
        Never invoke automatically merely because a campaign was opened.
        """
        if not self.remote or not self.partitioned:
            raise ValueError("Migration requires explicit partitioned remote mode")
        with self.lock:
            self._publish_partitions(compact=True)
            self.pending.clear()
            self.last_flush = time.monotonic()

    def _publish_partitions(self, compact):
        # Materialize identifiers only, not all response bodies. Import ALL
        # assets before taking the inventory, including unvisited leagues.
        if compact:
            self._import_assets()
            ids = set(self.index.ids()) | {p.stem for p in self.folder.glob("*.json")}
        else:
            ids = set(self.pending)
        ids = sorted(ids, key=int)
        previous = list(self.assets)
        replacements = []
        with tempfile.TemporaryDirectory() as tmp:
            for offset in range(0, len(ids), 128):
                chunk = ids[offset:offset + 128]
                name = f"tm-part-v2-{int(chunk[0])}-{int(chunk[-1])}-{uuid.uuid4().hex}.jsonl.gz"
                path = Path(tmp) / name
                with gzip.open(path, "wt", encoding="utf-8") as stream:
                    for pid in chunk:
                        record = self.get(pid) if compact else self.pending[pid]
                        if not record:
                            raise ValueError("Missing record during partition compaction")
                        stream.write(json.dumps(record) + "\n")
                self._gh("release", "upload", self.tag, str(path))
                replacements.append({"name": name})
        # A crash before/during deletion leaves overlapping immutable copies,
        # never a partial replacement. Next restore merges by original date.
        self.assets.extend(replacements)
        if compact:
            for asset in previous:
                if asset["name"].endswith(".jsonl.gz"):
                    self._gh("release", "delete-asset", self.tag, asset["name"], "--yes")
                    self.assets.remove(asset)

    def evidence(self, ids):
        records = [self.get(pid) for pid in ids]
        if not all(records):
            raise ValueError("Missing checkpoint evidence")
        stamps = [r["collected_at"] for r in records]
        return dict(campaign=self.campaign, response_version=VERSION,
                    collected_from=min(stamps), collected_through=max(stamps))
