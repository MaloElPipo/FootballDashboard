"""
Orchestrateur : génère les fichiers `live/data/tm_scrap/{code}.csv` (effectifs)
pour toutes les ligues déclarées dans `live/leagues_master.LEAGUES`.

- Skip les ligues dont le CSV existe déjà (sauf --force).
- Sauve un fichier d'état JSON `tm_scrap_progress.json` à chaque ligue terminée
  pour permettre relance sans perte.
- Continue malgré les erreurs partielles (loggées).

Usage :
    python scripts/scrape_all_squads.py            # toutes les ligues manquantes
    python scripts/scrape_all_squads.py --force    # tout refaire
    python scripts/scrape_all_squads.py --only L1  # une ligue précise
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TM_SCRAP_DIR = REPO_ROOT / "live" / "data" / "tm_scrap"
PROGRESS_FILE = REPO_ROOT / "tm_scrap_progress.json"
SCRAPER = REPO_ROOT / "tm_league_scraper.py"


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {"started_at": datetime.utcnow().isoformat(), "leagues": {}}


def save_progress(p: dict) -> None:
    p["updated_at"] = datetime.utcnow().isoformat()
    PROGRESS_FILE.write_text(json.dumps(p, indent=2, ensure_ascii=False))


def run_one(code: str, slug: str, timeout: int = 600) -> dict:
    """Lance le scraper pour 1 ligue. Retourne dict statut."""
    out_path = TM_SCRAP_DIR / f"{code.lower()}.csv"
    cmd = [
        sys.executable,
        str(SCRAPER),
        "--comp", code,
        "--slug", slug,
        "--workers", "5",
        "--out", str(out_path),
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - t0
        if proc.returncode == 0 and out_path.exists():
            n_rows = sum(1 for _ in out_path.open("r", encoding="utf-8")) - 1
            return {
                "ok": True,
                "elapsed_s": round(elapsed, 1),
                "n_rows": n_rows,
                "size_kb": round(out_path.stat().st_size / 1024, 1),
            }
        else:
            tail = (proc.stderr or proc.stdout or "")[-400:]
            return {
                "ok": False,
                "elapsed_s": round(elapsed, 1),
                "error": tail.strip(),
            }
    except subprocess.TimeoutExpired:
        return {"ok": False, "elapsed_s": timeout, "error": "TIMEOUT"}
    except Exception as e:
        return {"ok": False, "elapsed_s": round(time.time() - t0, 1), "error": str(e)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Re-scraper même les ligues déjà présentes")
    parser.add_argument("--only", help="Code TM unique (ex: L1)")
    parser.add_argument("--max-per-run", type=int, default=999,
                        help="Limite de ligues à traiter dans cette exécution")
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    from live.leagues_master import LEAGUES  # type: ignore

    TM_SCRAP_DIR.mkdir(parents=True, exist_ok=True)
    progress = load_progress()
    progress.setdefault("leagues", {})

    if args.only:
        candidates = [l for l in LEAGUES if l["code_tm"].upper() == args.only.upper()]
    else:
        candidates = list(LEAGUES)

    todo: list[dict] = []
    for l in candidates:
        code = l["code_tm"]
        out_path = TM_SCRAP_DIR / f"{code.lower()}.csv"
        if out_path.exists() and not args.force:
            continue
        todo.append(l)

    print(f"[INFO] {len(todo)}/{len(candidates)} ligue(s) à traiter "
          f"(les autres déjà présentes ; utiliser --force pour tout refaire)")
    if args.max_per_run < len(todo):
        print(f"[INFO] Limite à {args.max_per_run} dans cette exécution")
        todo = todo[:args.max_per_run]

    n_ok = 0
    n_ko = 0
    t_start = time.time()
    for i, l in enumerate(todo, 1):
        code = l["code_tm"]
        slug = l["slug"]
        elapsed_total = int(time.time() - t_start)
        print(f"\n[{i}/{len(todo)}] {code:6s} ({l['nom']}) [{elapsed_total}s écoulées]", flush=True)
        res = run_one(code, slug)
        progress["leagues"][code] = {**res, "slug": slug, "ts": datetime.utcnow().isoformat()}
        save_progress(progress)
        if res["ok"]:
            n_ok += 1
            print(f"  OK  {res['n_rows']:5d} lignes  "
                  f"{res['size_kb']:>6.1f} Ko  {res['elapsed_s']:>5.1f}s", flush=True)
        else:
            n_ko += 1
            print(f"  KO  {res['elapsed_s']:>5.1f}s  err={res['error'][:120]}", flush=True)

    total = time.time() - t_start
    print(f"\n[FIN] {n_ok} OK / {n_ko} KO en {total/60:.1f} min")
    return 0 if n_ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
