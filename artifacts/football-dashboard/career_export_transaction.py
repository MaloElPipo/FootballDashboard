"""Recoverable CSV-set replacement on a local POSIX filesystem.

Flat filenames cannot be swapped atomically as a group. Readers must not run
concurrently with a collection. After SIGKILL, recovery runs at the next
collection entry and before downstream export consumption.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil

SUFFIXES = ("summary", "career", "matches", "competitions_seen")
CURRENT_SUFFIXES = ("career", "matches")


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class ExportTransaction:
    def __init__(self, out, league, suffixes=SUFFIXES):
        if not league or Path(league).name != league or league in (".", ".."):
            raise ValueError("Invalid export league")
        self.out = Path(out)
        self.names = [f"{league}_{suffix}.csv" for suffix in suffixes]
        self.preparing = self.out / f".{league}.preparing"
        self.pending = self.out / f".{league}.pending"
        self.committed = self.out / f".{league}.committed"
        self.lock = self.out / f".{league}.export.lock"

    def recover(self):
        if self.pending.is_dir():
            # Backups remain intact until ALL restores are durable. Recovery
            # itself may be interrupted and is therefore idempotent.
            for name in self.names:
                backup = self.pending / "old" / name
                dest = self.out / name
                if backup.is_file():
                    temp = self.pending / "restore"
                    temp.unlink(missing_ok=True)
                    os.link(backup, temp)
                    os.replace(temp, dest)
                else:
                    dest.unlink(missing_ok=True)
            _sync(self.out)
            os.replace(self.pending, self.preparing)
            _sync(self.out)
        for directory in (self.preparing, self.committed):
            if directory.is_dir():
                shutil.rmtree(directory)
        _sync(self.out)

    def write(self, prepare, *, preserve_unwritten=False):
        """Stage payloads before replacement; optionally leave omitted files unchanged."""
        try:
            self.preparing.mkdir()
            new = self.preparing / "new"
            old = self.preparing / "old"
            new.mkdir()
            old.mkdir()
            prepare(new)
            for name in self.names:
                if not preserve_unwritten or (new / name).exists():
                    _sync(new / name)
                dest = self.out / name
                if dest.is_file():
                    # No duplicate CSV bytes needed for rollback on a full disk.
                    os.link(dest, old / name)
            _sync(new)
            _sync(old)
            _sync(self.preparing)
            os.replace(self.preparing, self.pending)
            _sync(self.out)
            for name in self.names:
                staged = self.pending / "new" / name
                if not preserve_unwritten or staged.exists():
                    os.replace(staged, self.out / name)
            _sync(self.pending / "new")
            _sync(self.out)
            # Durable commit boundary: committed directories are only garbage,
            # never rollback journals, even if cleanup gets interrupted.
            os.replace(self.pending, self.committed)
            _sync(self.out)
        except BaseException:
            # If restoration also fails, retain the journal and propagate the
            # error: the next invocation retries before collecting anything.
            self.recover()
            raise
        self.recover()


@contextmanager
def export_transaction(out, league, suffixes=SUFFIXES):
    tx = ExportTransaction(out, league, suffixes)
    tx.out.mkdir(parents=True, exist_ok=True)
    # Keep the lock inode: unlinking it would let concurrent writers bypass it.
    with tx.lock.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        tx.recover()
        yield tx


def recover_exports(out, suffixes=SUFFIXES):
    """Recover all interrupted leagues, including ones with no CSV yet."""
    root = Path(out)
    if not root.is_dir():
        return
    leagues = set()
    for suffix in ("preparing", "pending", "committed"):
        for directory in root.glob(f".*.{suffix}"):
            leagues.add(directory.name[1:-(len(suffix) + 1)])
    for league in sorted(leagues):
        with export_transaction(root, league, suffixes):
            pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Recover interrupted career exports")
    parser.add_argument("out_dir")
    parser.add_argument("--current", action="store_true",
                        help="Recover the two current-season CSVs only")
    args = parser.parse_args()
    recover_exports(args.out_dir, CURRENT_SUFFIXES if args.current else SUFFIXES)
