"""Rebuildable, campaign-local SQLite index of immutable remote journals.

An asset receipt and its records commit together. Never acknowledge an asset
before all its rows have been validated. Source responses remain fsynced JSON
until uploaded; this database only caches already durable remote responses.
"""
import json
import sqlite3
import re
from contextlib import contextmanager


def partition_bounds(name):
    """Self-indexing immutable v2 assets remain readable by legacy readers."""
    if not name.startswith("tm-part-v2-"):
        return None
    match = re.fullmatch(r"tm-part-v2-([0-9]+)-([0-9]+)-[a-f0-9]{32}\.jsonl\.gz", name)
    if not match or int(match[1]) > int(match[2]):
        raise ValueError("Invalid checkpoint partition name")
    return int(match[1]), int(match[2])


class RemoteIndex:
    def __init__(self, folder):
        self.path = folder / "remote-index.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records (
                    pid TEXT PRIMARY KEY, stamp TEXT NOT NULL, body TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assets (
                    identity TEXT PRIMARY KEY
                );
            """)

    @contextmanager
    def connect(self):
        # DELETE journal + FULL sync: crash rolls back the whole import,
        # including its receipt. No per-response fsync.
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def identity(asset):
        # gh supplies an opaque (often GraphQL) id, not necessarily an integer.
        # A same-name re-upload must miss the old receipt. Do not key by name.
        return json.dumps({k: asset.get(k) for k in
                           ("name", "id", "size", "updatedAt")}, sort_keys=True)

    def contains(self, asset):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM assets WHERE identity=?",
                              (self.identity(asset),)).fetchone() is not None

    def ingest(self, asset, records):
        with self.connect() as db:
            for record in records:
                db.execute("""
                    INSERT INTO records VALUES (?, ?, ?)
                    ON CONFLICT(pid) DO UPDATE SET stamp=excluded.stamp,
                    body=excluded.body WHERE excluded.stamp > records.stamp
                """, (record["player_id"], record["collected_at"],
                      json.dumps(record, ensure_ascii=False)))
            db.execute("INSERT OR IGNORE INTO assets VALUES (?)",
                       (self.identity(asset),))

    def get(self, pid):
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE pid=?", (pid,)).fetchone()
        return json.loads(row[0]) if row else None

    def ids(self):
        with self.connect() as db:
            for row in db.execute("SELECT pid FROM records"):
                yield row[0]
