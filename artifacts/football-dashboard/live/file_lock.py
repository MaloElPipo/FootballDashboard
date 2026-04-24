"""Verrou inter-process pour protéger les écritures sur forward_log.jsonl.

Utilise fcntl.flock (Linux/macOS) sur un fichier sentinel séparé pour éviter
les race conditions entre predict_today.py (append) et enrich_results.py
(read+rewrite atomique). Bloquant; timeout configurable.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from pathlib import Path


@contextlib.contextmanager
def log_lock(lock_path: Path | str, timeout: float = 30.0, poll: float = 0.1):
    """Acquire an exclusive flock on `lock_path`. Bloquant, abandonne après timeout."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.time() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    raise TimeoutError(
                        f"Impossible d'acquérir le verrou {lock_path} en {timeout}s"
                    )
                time.sleep(poll)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def atomic_rewrite(target: Path | str, lines: list[str]) -> None:
    """Écrit `lines` (chaînes sans \\n final) dans target via tmp + os.replace."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln.rstrip("\n") + "\n")
    os.replace(tmp, target)
