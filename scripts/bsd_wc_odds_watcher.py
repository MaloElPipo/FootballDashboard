"""Polling quotidien — détecte l'ouverture des cotes BSD sur la CDM 2026.

Contexte:
    Au 20/05/2026, les 72 matchs de poule CDM2026 existent dans BSD
    (league_id=27, season_id=383, rounds 1-3) avec les vrais noms d'équipes,
    mais aucun bookmaker n'a encore agrégé de cotes (`bookmakers_count=0`
    sur 1x2/btts/over_under_25). Ce script poll quotidiennement et alerte
    dès qu'une couverture apparaît, pour débloquer la "Passe 1" (triple
    inversion Dixon-Coles branchée en prod).

Usage:
    python scripts/bsd_wc_odds_watcher.py [--sample 10]

Variables d'env requises:
    BSD_API_KEY

Sortie:
    - Append-only dans live/data/bsd_wc_coverage.jsonl (1 ligne par run)
    - Crée `.local/bsd_wc_odds_ready.flag` à la première transition 0 -> >0
    - Exit 0 normalement, exit 2 si erreur réseau bloquante

Aucune écriture sur le code prod. Ne touche jamais aux caches du dashboard.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
COVERAGE_LOG = REPO_ROOT / "live" / "data" / "bsd_wc_coverage.jsonl"
READY_FLAG = REPO_ROOT / ".local" / "bsd_wc_odds_ready.flag"

BSD_BASE = "https://sports.bzzoiro.com/api"
WC_LEAGUE_ID = 27
WC_SEASON_ID = 383  # "2025/2026" — contient les 72 matchs de poule avec vrais noms
POOL_ROUNDS = {1, 2, 3}
MARKETS = ("1x2", "btts", "over_under_25")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bsd_wc_odds_watcher")


def _headers() -> dict[str, str]:
    key = os.environ.get("BSD_API_KEY", "")
    if not key:
        raise RuntimeError("BSD_API_KEY manquant")
    return {"Authorization": f"Token {key}"}


def _bsd_get(endpoint: str, params: dict | None = None) -> requests.Response:
    """GET brut. Le caller décide quoi faire des codes HTTP non-200."""
    url = f"{BSD_BASE}/{endpoint.lstrip('/')}"
    return requests.get(url, headers=_headers(), params=params or {}, timeout=30)


def list_pool_matches() -> list[dict]:
    """Renvoie les 72 fixtures phase de poule CDM2026 (vrais noms d'équipes).

    Endpoint REST = `/api/events/?league=27&season=383` (validé manuellement
    le 20/05/2026 : 78 résultats sur l'ensemble CDM, dont 72 phase de poule).
    """
    resp = _bsd_get(
        "events/",
        {"league": WC_LEAGUE_ID, "season": WC_SEASON_ID, "limit": 200},
    )
    resp.raise_for_status()
    data = resp.json()
    arr = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(arr, list):
        return []
    return [m for m in arr if m.get("round_number") in POOL_ROUNDS]


def check_event_coverage(event_id: int) -> dict[str, int]:
    """Pour un event, renvoie {market: bookmakers_count} sur les 3 marchés.

    Convention BSD REST observée le 20/05/2026 :
    - 200 + `bookmakers_count: N` quand au moins un book agrégé
    - 404 + `{"error":"No odds found for this event"}` quand aucune cote
      (état actuel pour les 72 matchs de poule CDM)
    - Autre 4xx/5xx ou exception réseau -> -1 (indéterminé)
    """
    out: dict[str, int] = {}
    for market in MARKETS:
        try:
            resp = _bsd_get("odds/compare/", {"event": event_id, "market": market})
        except Exception as exc:  # noqa: BLE001
            log.warning("event=%s market=%s ERREUR réseau %s", event_id, market, exc)
            out[market] = -1
            continue

        if resp.status_code == 200:
            try:
                d = resp.json()
            except ValueError:
                out[market] = -1
                continue
            count = d.get("bookmakers_count") if isinstance(d, dict) else None
            if count is None:
                rows = d.get("results") if isinstance(d, dict) else d
                if isinstance(rows, list):
                    books = {r.get("bookmaker") or r.get("book")
                             for r in rows if isinstance(r, dict)}
                    books.discard(None)
                    count = len(books)
                else:
                    count = 0
            try:
                out[market] = int(count or 0)
            except (TypeError, ValueError):
                out[market] = 0
        elif resp.status_code == 404:
            # "No odds found" = pas encore de book agrégé. Compte = 0, pas une erreur.
            out[market] = 0
        else:
            log.warning(
                "event=%s market=%s HTTP %s body=%s",
                event_id, market, resp.status_code, resp.text[:120],
            )
            out[market] = -1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=int,
        default=10,
        help="Nombre de matchs à sonder (échantillon stratifié MD1+chocs). "
             "Défaut: 10. Utiliser 72 pour un balayage complet.",
    )
    args = parser.parse_args()

    try:
        pool = list_pool_matches()
    except Exception as exc:  # noqa: BLE001
        log.error("Échec listing fixtures CDM: %s", exc)
        return 2

    if not pool:
        log.error("Aucune fixture CDM trouvée — vérifier season_id=%d", WC_SEASON_ID)
        return 2

    log.info("Fixtures phase de poule CDM trouvées: %d", len(pool))

    # Échantillonnage stratifié : MD1 d'abord (cotes ouvrent en premier),
    # puis chocs réputés (Brazil, France, Argentina, England, Spain, Germany).
    big_teams = {"Brazil", "France", "Argentina", "England", "Spain", "Germany", "Portugal"}
    md1 = sorted(
        [m for m in pool if m["round_number"] == 1],
        key=lambda m: m.get("event_date", ""),
    )
    blockbusters = [
        m for m in pool
        if m["home_team"] in big_teams or m["away_team"] in big_teams
    ]
    seen_ids: set[int] = set()
    targets: list[dict] = []
    for m in md1 + blockbusters + pool:
        if m["id"] in seen_ids:
            continue
        seen_ids.add(m["id"])
        targets.append(m)
        if len(targets) >= args.sample:
            break

    log.info("Échantillon sondé: %d matchs", len(targets))

    per_event: list[dict] = []
    matches_with_any = 0
    market_totals = {m: 0 for m in MARKETS}

    for i, m in enumerate(targets, start=1):
        cov = check_event_coverage(m["id"])
        any_market = any(cov[mk] > 0 for mk in MARKETS)
        if any_market:
            matches_with_any += 1
        for mk in MARKETS:
            if cov[mk] > 0:
                market_totals[mk] += 1
        per_event.append({
            "event_id": m["id"],
            "home": m["home_team"],
            "away": m["away_team"],
            "date": m["event_date"],
            "round": m["round_number"],
            "coverage": cov,
        })
        log.info(
            "[%d/%d] %s vs %s (%s) -> %s",
            i, len(targets), m["home_team"], m["away_team"],
            m["event_date"][:10], cov,
        )

    # Écriture log append-only
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "checked_at": now,
        "fixtures_total": len(pool),
        "sample_size": len(targets),
        "matches_with_any_coverage": matches_with_any,
        "market_coverage_in_sample": market_totals,
        "per_event": per_event,
    }
    COVERAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with COVERAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    log.info(
        "Bilan: %d/%d matchs avec >=1 marché ouvert | par marché: %s",
        matches_with_any, len(targets), market_totals,
    )

    # Gate transition 0 -> >0 : crée le flag si cov apparaît pour la première fois
    if matches_with_any > 0 and not READY_FLAG.exists():
        READY_FLAG.parent.mkdir(parents=True, exist_ok=True)
        READY_FLAG.write_text(json.dumps({
            "detected_at": now,
            "matches_with_any_coverage": matches_with_any,
            "sample_size": len(targets),
            "market_coverage_in_sample": market_totals,
        }, ensure_ascii=False, indent=2))
        log.warning(
            "FLAG CRÉÉ: %s -- les cotes BSD CDM s'ouvrent ! "
            "Passe 1 (triple inversion en prod) déblocable.",
            READY_FLAG,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
