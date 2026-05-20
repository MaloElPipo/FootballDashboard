"""Gestion des snapshots prod en lecture seule.

Le labo ne touche jamais aux fichiers prod. Il en copie une image datee dans
lab/data/snapshots/ qu'il consomme ensuite.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = LAB_ROOT / "lab" / "data" / "snapshots"
SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

PROD_DIR = Path("/home/runner/workspace/artifacts/football-dashboard")

PROD_FILES_TO_SNAPSHOT = [
    "pin_calibrated_elo.json",
    "elorating_cache.json",
    "elo_overrides.json",
    "pinnacle_wc2026_odds.json",
    "implied_elo.json",
]


def snapshot_prod(tag: str | None = None) -> dict[str, str]:
    """Copie les fichiers prod critiques avec horodatage.

    Args:
        tag: optional suffixe ('pre_phase1', ...). Sinon timestamp YYYY-MM-DD.
    """
    stamp = tag or datetime.utcnow().strftime("%Y-%m-%d")
    target_dir = SNAPSHOT_DIR / stamp
    target_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for fname in PROD_FILES_TO_SNAPSHOT:
        src = PROD_DIR / fname
        if not src.exists():
            out[fname] = "missing"
            continue
        dst = target_dir / fname
        shutil.copy2(src, dst)
        out[fname] = str(dst.relative_to(LAB_ROOT))
    (target_dir / "_meta.json").write_text(
        json.dumps(
            {
                "taken_at": datetime.utcnow().isoformat() + "Z",
                "files": out,
            },
            indent=2,
        )
    )
    return out


def list_snapshots() -> list[dict]:
    """Liste les snapshots disponibles avec leur meta."""
    out = []
    for d in sorted(SNAPSHOT_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        meta_file = d / "_meta.json"
        meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        out.append(
            {
                "tag": d.name,
                "path": str(d.relative_to(LAB_ROOT)),
                "files": meta.get("files", {}),
                "taken_at": meta.get("taken_at", "?"),
            }
        )
    return out


def load_snapshot(tag: str, filename: str) -> dict | list:
    """Charge un fichier d'un snapshot specifique."""
    path = SNAPSHOT_DIR / tag / filename
    return json.loads(path.read_text())
