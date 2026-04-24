"""Pipeline daily : pour chaque match Top 5 J/J+1, produit une prédiction
joueur (xG / xA / proba scorer / proba assist) + récupère les odds buteur/passeur
Betclic, puis append dans `data/forward_log.jsonl`.

Usage :
    python predict_today.py [--leagues bundesliga,ligue_1] [--days 2]
                            [--no-betclic]   # skip scraping (mode rapide)
                            [--dry-run]      # affiche sans écrire dans le log

Idempotent : un (event_id, player_id) déjà loggé n'est pas dupliqué.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
PARENT = ROOT.parent
sys.path.insert(0, str(PARENT))

from g2_engine import lambdas_buchdahl  # noqa: E402
from preview_player_odds._3_model_proxy import (  # noqa: E402  (import via proxy below)
    aggregate_player_pool,
    distribute_xg_to_players,
)
from live.bsd_helpers import (  # noqa: E402
    TOP5_LEAGUES,
    get_upcoming_events,
    get_event_detail,
    extract_odds,
    fetch_team_squads_parallel,
)
from live.file_lock import log_lock  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("predict_today")


FORWARD_LOG = DATA_DIR / "forward_log.jsonl"
FORWARD_LOG_LOCK = DATA_DIR / "forward_log.lock"


# ---------------------------------------------------------------------------
# Utilitaires noms (matching Betclic ↔ BSD)
# ---------------------------------------------------------------------------
def norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


def name_match_score(a: str, b: str) -> float:
    """Score 0-1 entre deux noms de joueurs (ou équipes)."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    overlap = len(a_tokens & b_tokens)
    union = len(a_tokens | b_tokens)
    jaccard = overlap / union
    # Bonus si le dernier token (souvent le nom de famille) match
    if a.split()[-1] == b.split()[-1]:
        jaccard = max(jaccard, 0.85)
    return jaccard


def find_betclic_match(ev: dict, betclic_matches: list[dict]) -> dict | None:
    """Trouve le BetclicMatch correspondant à un BSD event via fuzzy match équipes+date."""
    bsd_home = ev.get("home_team", "")
    bsd_away = ev.get("away_team", "")
    bsd_dt = ev.get("event_date", "")
    bsd_date = bsd_dt[:10] if bsd_dt else ""

    best, best_score = None, 0.0
    for bm in betclic_matches:
        sh = name_match_score(bsd_home, bm.get("home_team", ""))
        sa = name_match_score(bsd_away, bm.get("away_team", ""))
        if sh < 0.4 or sa < 0.4:
            continue
        # Bonus si même date kickoff
        bm_ko = bm.get("kickoff_utc")
        bm_date = bm_ko[:10] if bm_ko else ""
        date_bonus = 0.2 if bm_date == bsd_date else 0.0
        score = (sh + sa) / 2 + date_bonus
        if score > best_score:
            best, best_score = bm, score
    return best if best_score >= 0.6 else None


def find_betclic_player_odd(player_name: str, betclic_match: dict, market_type: str) -> float | None:
    """Cherche dans les selections Betclic du match un joueur donné pour un marché.
    market_type ∈ {'goalscorer', 'assist'}.
    """
    if not betclic_match:
        return None
    best, best_score = None, 0.0
    for sel in betclic_match.get("selections", []):
        if sel.get("market_type") != market_type:
            continue
        score = name_match_score(player_name, sel.get("selection_name", ""))
        if score > best_score:
            best, best_score = sel, score
    if best and best_score >= 0.7:
        return best.get("odds")
    return None


# ---------------------------------------------------------------------------
# Lineup (BSD prédite, fallback heuristique sur les 5 derniers matchs)
# ---------------------------------------------------------------------------
def is_player_unavailable(pool_entry: dict | None) -> bool:
    """Joueur exclu de la lineup s'il est blessé/suspendu/etc."""
    if not pool_entry:
        return False
    av = (pool_entry.get("availability") or "available").lower()
    return av not in ("available", "")


def build_lineup_fallback(team_id: int, team_side: str, pool: dict, n_starters: int = 11,
                          n_subs: int = 6) -> list[dict]:
    """Si BSD n'a pas de lineup, on prend les 17 joueurs disponibles ayant le plus
    de minutes dans la saison. Les joueurs non-disponibles (blessés / suspendus)
    sont systématiquement exclus."""
    players = [(pid, p) for pid, p in pool.items()
               if p.get("team_id") == team_id and not is_player_unavailable(p)]
    players.sort(key=lambda x: x[1].get("minutes_total", 0), reverse=True)
    out = []
    for i, (pid, p) in enumerate(players[:n_starters + n_subs]):
        out.append({
            "player_id": pid,
            "team_id": team_id,
            "side": team_side,
            "is_starter": i < n_starters,
            "position": "G" if p.get("is_gk") else None,
        })
    return out


def get_lineup_for_event(ev_detail: dict, home_id: int, away_id: int, pool: dict) -> tuple[list[dict], dict[str, bool], list[dict]]:
    """Retourne (lineup, lineup_confirmed_by_side, excluded_players).

    - `lineup` : liste de joueurs au format `get_lineup_players` du modèle, dédupliquée
    - `lineup_confirmed_by_side` : {"home": bool, "away": bool} ; True ssi BSD a
      publié les compos officielles pour ce côté précis. Permet à
      `distribute_xg_to_players` de gérer les minutes différemment côté confirmé
      (avg_mins_when_starter, sub à 25min) vs côté fallback (90 partout).
    - `excluded_players` : joueurs filtrés pour cause de blessure/suspension
      (renvoyés pour qu'ils apparaissent dans le forward log avec un flag).
    """
    lineups = ev_detail.get("lineups") or {}
    out: list[dict] = []
    excluded: list[dict] = []
    seen_pids: set[int] = set()
    confirmed_by_side: dict[str, bool] = {"home": False, "away": False}

    def _add(pid, team_id, side, is_starter, position):
        if pid is None:
            return
        pid = int(pid)
        if pid in seen_pids:
            return
        # Filtrage blessés / suspendus
        if is_player_unavailable(pool.get(pid)):
            excluded.append({
                "player_id": pid, "team_id": team_id, "side": side,
                "is_starter": is_starter, "position": position,
                "reason": (pool.get(pid) or {}).get("availability"),
                "injury_type": (pool.get(pid) or {}).get("injury_type"),
            })
            return
        seen_pids.add(pid)
        out.append({"player_id": pid, "team_id": team_id, "side": side,
                    "is_starter": is_starter, "position": position})

    for side, team_id in (("home", home_id), ("away", away_id)):
        side_block = lineups.get(side) if isinstance(lineups, dict) else None
        side_has_lineup = bool(side_block and (side_block.get("starters")
                                                or side_block.get("starting")))
        if side_has_lineup:
            confirmed_by_side[side] = True
            starters = side_block.get("starters") or side_block.get("starting") or []
            subs = side_block.get("substitutes") or side_block.get("subs") or []
            for p in starters:
                if isinstance(p, dict):
                    pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                    _add(pid, team_id, side, True, p.get("position"))
            for p in subs:
                if isinstance(p, dict):
                    pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                    _add(pid, team_id, side, False, p.get("position"))

        # Si pas de lineup confirmée pour ce côté → fallback : on prend tout le squad
        # actif. distribute_xg_to_players verra confirmed_by_side[side]=False et
        # forcera 90 minutes pour tout le monde côté fallback.
        if not any(lp["side"] == side for lp in out):
            for lp in build_lineup_fallback(team_id, side, pool):
                _add(lp["player_id"], team_id, side, lp["is_starter"], lp.get("position"))
    return out, confirmed_by_side, excluded


# ---------------------------------------------------------------------------
# Pool joueurs
# ---------------------------------------------------------------------------
def assign_team_ids_via_squads(pool: dict, league_team_ids: list[int],
                                cache_path: Path) -> int:
    """Pour chaque équipe de la ligue, récupère l'effectif actuel via BSD
    `/players/?team={id}` et assigne `team_id` (résout transferts hiver).
    Aussi : propage `position`, `specific_position`, `availability`, `injury_type`.
    Cache 24h dans `{league}_squads.json`.
    """
    cache: dict[int, list[dict]] = {}
    use_cache = False
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 24:
            try:
                cache = {int(k): v for k, v in json.loads(cache_path.read_text()).items()}
                use_cache = True
            except Exception:
                cache = {}

    if not use_cache:
        log.info("  Fetch squads BSD pour %d équipes...", len(league_team_ids))
        cache = fetch_team_squads_parallel(league_team_ids)
        cache_path.write_text(json.dumps({str(k): v for k, v in cache.items()}))

    assigned = 0
    for team_id, squad in cache.items():
        for p in squad:
            pid = p.get("id")
            if pid is None:
                continue
            pid = int(pid)
            squad_position = p.get("position")
            squad_spec_position = p.get("specific_position")
            squad_availability = p.get("availability") or "available"
            squad_injury_type = p.get("injury_type") or ""
            squad_injury_return = p.get("injury_expected_return")
            squad_jersey = p.get("jersey_number")

            if pid in pool:
                # Squad = équipe actuelle, prioritaire sur tout
                if pool[pid].get("team_id") != team_id:
                    pool[pid]["team_id"] = team_id
                    assigned += 1
                # Position du squad = source de vérité (BSD player-stats peut être imprécis)
                if squad_position:
                    pool[pid]["position"] = squad_position
                if squad_spec_position:
                    pool[pid]["specific_position"] = squad_spec_position
                pool[pid]["is_gk"] = pool[pid].get("is_gk") or squad_position == "G"
                pool[pid]["availability"] = squad_availability
                pool[pid]["injury_type"] = squad_injury_type
                pool[pid]["injury_expected_return"] = squad_injury_return
                if squad_jersey is not None:
                    pool[pid]["jersey_number"] = squad_jersey
            else:
                # Joueur existe en squad mais pas (encore) dans le pool de stats :
                # on l'ajoute avec valeurs neutres pour qu'il puisse hériter du
                # prior par poste quand il sera shrunk-per-90 (= prior).
                pool[pid] = {
                    "name": p.get("name") or p.get("short_name") or f"Player {pid}",
                    "team_id": team_id,
                    "is_gk": squad_position == "G",
                    "position": squad_position,
                    "specific_position": squad_spec_position,
                    "availability": squad_availability,
                    "injury_type": squad_injury_type,
                    "injury_expected_return": squad_injury_return,
                    "jersey_number": squad_jersey,
                    "minutes_total": 0,
                    "matches_played": 0,
                    "matches_played_curr": 0, "matches_played_prev": 0,
                    "goals_total": 0,
                    "assists_total": 0,
                    "xg_total": 0.0,
                    "xa_total": 0.0,
                    "shots_total": 0,
                    "key_pass_total": 0,
                    "starts": 0,
                    "starter_minutes_sum": 0,
                    "xg_per_90": 0.0, "xa_per_90": 0.0, "shots_per_90": 0.0,
                    "avg_mins_when_starter": 78.0,
                }
                assigned += 1
    return assigned


# Tier de championnat pour le coefficient α de pondération saison N-1.
# Si le championnat précédent du joueur (BSD `transfers`) est inconnu, on
# utilise la valeur par défaut.
LEAGUE_TIER = {
    1: "TOP5",   # Premier League
    3: "TOP5",   # La Liga
    4: "TOP5",   # Serie A
    5: "TOP5",   # Bundesliga
    6: "TOP5",   # Ligue 1
}
ALPHA_SAME_LEAGUE = 0.7  # joueur acclimaté au championnat
ALPHA_TOP5_TO_TOP5 = 0.6  # transfert entre Top 5
ALPHA_LOWER_TO_TOP5 = 0.5  # championnat moins compétitif


def _build_alpha_fn_from_prev_stats(prev_stats: dict, prev_matches: dict, current_team_by_pid: dict[int, int]) -> dict[int, float]:
    """Construit dict pid→alpha basé sur la comparaison team N vs team N-1.

    Règle :
      - team N == team N-1 → ALPHA_SAME_LEAGUE (joueur acclimaté, 0.7)
      - team N != team N-1 mais les 2 dans le pool de la même ligue → ALPHA_SAME_LEAGUE
        (transfert intra-ligue, joueur connaît le championnat)
      - team N-1 absente / extérieure à la ligue courante → ALPHA_TOP5_TO_TOP5 (0.6)
        (proxy : on suppose un transfert depuis un autre Top5 ; sans data
        transferts BSD pour distinguer Top5↔Top5 de lower↔Top5)

    Joueurs absents du pool N-1 → traités via le défaut scalaire dans aggregate.
    """
    out: dict[int, float] = {}
    if not prev_stats:
        return out

    # Reconstruit team_id_prev pour chaque pid en parcourant prev_stats.
    # On prend le DERNIER team_id rencontré côté N-1 (= équipe en fin de saison
    # N-1, plus représentative de "d'où vient le joueur" au moment de l'arrivée
    # en saison N). Idem côté courant (cf. _build_alpha_fn_from_prev_stats).
    team_prev_by_pid: dict[int, int] = {}
    for ev_block in prev_stats.values():
        for s in ev_block.get("stats", []):
            p = s.get("player")
            pid = p.get("id") if isinstance(p, dict) else p
            if pid is None:
                continue
            tid = s.get("team")
            if isinstance(tid, dict):
                tid = tid.get("id")
            if tid is not None:
                team_prev_by_pid[int(pid)] = int(tid)  # écrase → garde le dernier

    league_team_ids = set(current_team_by_pid.values())

    for pid, tid_prev in team_prev_by_pid.items():
        tid_curr = current_team_by_pid.get(pid)
        if tid_curr is None:
            # Joueur absent du pool N (parti, blessé long terme) → 0.5
            out[pid] = ALPHA_LOWER_TO_TOP5
        elif tid_prev == tid_curr:
            out[pid] = ALPHA_SAME_LEAGUE  # même équipe, parfait
        elif tid_prev in league_team_ids:
            out[pid] = ALPHA_SAME_LEAGUE  # transfert intra-ligue
        else:
            out[pid] = ALPHA_TOP5_TO_TOP5  # transfert externe (proxy)
    return out


def load_pool(slug: str) -> dict:
    pool_file = DATA_DIR / f"{slug}_pool.json"
    if not pool_file.exists():
        log.warning("Pool manquant pour %s — exécute build_player_pool.py %s", slug, slug)
        return {}
    raw = json.loads(pool_file.read_text())

    # Saison N-1 si fichier dispo
    prev_file = DATA_DIR / f"{slug}_pool_prev.json"
    prev_stats = prev_matches = None
    if prev_file.exists():
        try:
            prev_raw = json.loads(prev_file.read_text())
            prev_stats = prev_raw.get("by_event_stats")
            prev_matches = prev_raw.get("events")
            log.info("  Pool %s : saison N-1 trouvée (%d matchs)",
                     slug, prev_raw.get("n_matches", 0))
        except Exception as e:
            log.warning("  Pool %s : pool_prev illisible (%s)", slug, e)

    # 1ʳᵉ passe : agrégation sans alpha pour récupérer les team_id N (par joueur)
    if prev_stats:
        # Team_id N par joueur : on prend le DERNIER match observé en N (gère les
        # transferts intra-saison hiver — un joueur arrivé en janvier sera classé
        # avec sa team de janvier, pas celle où il a éventuellement joué avant).
        current_team_by_pid: dict[int, int] = {}
        for ev_block in raw["by_event_stats"].values():
            for s in ev_block.get("stats", []):
                p = s.get("player")
                pid = p.get("id") if isinstance(p, dict) else p
                if pid is None:
                    continue
                tid = s.get("team")
                if isinstance(tid, dict):
                    tid = tid.get("id")
                if tid is not None:
                    current_team_by_pid[int(pid)] = int(tid)  # écrase → garde le dernier
        alpha_by_pid = _build_alpha_fn_from_prev_stats(prev_stats, prev_matches or {},
                                                       current_team_by_pid)
        n_07 = sum(1 for v in alpha_by_pid.values() if abs(v - ALPHA_SAME_LEAGUE) < 1e-6)
        n_06 = sum(1 for v in alpha_by_pid.values() if abs(v - ALPHA_TOP5_TO_TOP5) < 1e-6)
        n_05 = sum(1 for v in alpha_by_pid.values() if abs(v - ALPHA_LOWER_TO_TOP5) < 1e-6)
        log.info("  Pool %s : alpha N-1 par joueur — 0.7=%d, 0.6=%d, 0.5=%d",
                 slug, n_07, n_06, n_05)

        def _alpha_fn(pid, _d=alpha_by_pid):
            return _d.get(int(pid), ALPHA_SAME_LEAGUE)
        alpha_arg = _alpha_fn
    else:
        alpha_arg = ALPHA_SAME_LEAGUE

    pool = aggregate_player_pool(
        raw["by_event_stats"], raw["events"],
        prev_player_stats_by_event=prev_stats,
        prev_matches_by_id=prev_matches,
        alpha_prev=alpha_arg,
    )

    # Récupère tous les team_ids de la ligue depuis les events
    team_ids = set()
    for ev in raw["events"].values():
        h = (ev.get("home_team_obj") or {}).get("id")
        a = (ev.get("away_team_obj") or {}).get("id")
        if h: team_ids.add(h)
        if a: team_ids.add(a)

    cache_path = DATA_DIR / f"{slug}_squads.json"
    n_assigned = assign_team_ids_via_squads(pool, sorted(team_ids), cache_path)
    n_with_team = sum(1 for p in pool.values() if p.get("team_id") is not None)
    log.info("Pool %s : %d joueurs (%d/%d ont team_id, %d assignations via squads)",
             slug, len(pool), n_with_team, len(pool), n_assigned)
    return pool


# ---------------------------------------------------------------------------
# Betclic scraper async
# ---------------------------------------------------------------------------
LEAGUE_TO_BETCLIC_KEY = {
    "premier_league": "premier_league",
    "la_liga": "la_liga",
    "serie_a": "serie_a",
    "bundesliga": "bundesliga",
    "ligue_1": "ligue_1",
}


async def scrape_betclic_leagues(slugs: list[str]) -> dict[str, list[dict]]:
    from betclic_scraper import scrape_betclic
    comp_keys = [LEAGUE_TO_BETCLIC_KEY[s] for s in slugs if s in LEAGUE_TO_BETCLIC_KEY]
    if not comp_keys:
        return {}
    log.info("Scraping Betclic pour %d ligues : %s", len(comp_keys), ", ".join(comp_keys))
    res = await scrape_betclic(
        competitions=comp_keys,
        include_1x2=False,
        include_goalscorer=True,
        include_assist=True,
        include_outright=False,
    )
    by_slug: dict[str, list[dict]] = {}
    for comp_data in res:
        ck = comp_data.get("competition", "")
        slug = next((s for s, k in LEAGUE_TO_BETCLIC_KEY.items() if k == ck), ck)
        # Convertir BetclicMatch → dict
        ms = []
        for bm in comp_data.get("matches", []):
            ms.append({
                "home_team": bm.home_team,
                "away_team": bm.away_team,
                "match_id": bm.match_id,
                "kickoff_utc": bm.kickoff_utc.isoformat() if bm.kickoff_utc else None,
                "selections": [
                    {"market_type": s.market_type, "selection_name": s.selection_name,
                     "odds": s.odds, "market_name": s.market_name}
                    for s in bm.selections
                ],
            })
        by_slug[slug] = ms
        log.info("  %s : %d matchs scrapés", slug, len(ms))
    return by_slug


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def load_seen_keys() -> set[tuple[int, int]]:
    """Retourne l'ensemble des (event_id, player_id) déjà loggés (toutes dates)."""
    seen: set[tuple[int, int]] = set()
    if not FORWARD_LOG.exists():
        return seen
    with FORWARD_LOG.open() as f:
        for line in f:
            try:
                d = json.loads(line)
                seen.add((int(d["event_id"]), int(d["player_id"])))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
    return seen


def predict_one_event(ev: dict, slug: str, pool: dict,
                      betclic_matches: list[dict]) -> list[dict]:
    """Construit les lignes de log pour un match à venir."""
    ev_id = ev["id"]
    home_id = (ev.get("home_team_obj") or {}).get("id")
    away_id = (ev.get("away_team_obj") or {}).get("id")
    if not home_id or not away_id:
        return []

    odds = extract_odds(ev)
    if not (odds["odds_h"] and odds["odds_d"] and odds["odds_a"]):
        log.warning("Event %s : odds 1X2 manquantes", ev_id)
        return []

    try:
        xg_h, xg_a, method = lambdas_buchdahl(
            odds["odds_h"], odds["odds_d"], odds["odds_a"],
            odds["ou25_under"], odds["ou25_over"],
            odds["btts_yes"], odds["btts_no"],
        )
    except Exception as e:
        log.warning("Event %s : lambdas_buchdahl a échoué (%s)", ev_id, e)
        return []

    # Détail matche pour récupérer la lineup si dispo
    detail = get_event_detail(ev_id) or ev
    lineup_players, confirmed_by_side, excluded = get_lineup_for_event(
        detail, home_id, away_id, pool)
    if not lineup_players:
        log.warning("Event %s : aucune lineup ni fallback possible", ev_id)
        return []

    if excluded:
        log.info("  Event %s : %d joueurs exclus pour blessure/suspension",
                 ev_id, len(excluded))

    # Distribution : minutes calculées par side (les côtés non confirmés → 90 partout)
    predictions = distribute_xg_to_players(
        xg_h, xg_a, home_id, away_id, lineup_players, pool,
        lineup_confirmed=confirmed_by_side,
    )

    # Pour le forward log : conserve un bool global rétro-compatible (ET les 2 booléens)
    home_confirmed = bool(confirmed_by_side.get("home"))
    away_confirmed = bool(confirmed_by_side.get("away"))
    lineup_confirmed = home_confirmed or away_confirmed

    # Match Betclic (par équipes)
    bm = find_betclic_match(ev, betclic_matches)
    if bm:
        log.info("  Event %s : Betclic match trouvé (%d selections)",
                 ev_id, len(bm.get("selections", [])))

    logged_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[dict] = []
    for pid, pred in predictions.items():
        bc_scorer = find_betclic_player_odd(pred["name"], bm or {}, "goalscorer")
        bc_assist = find_betclic_player_odd(pred["name"], bm or {}, "assist")

        edge_scorer = None
        if bc_scorer and pred["p_scorer"]:
            edge_scorer = pred["p_scorer"] * bc_scorer - 1.0
        edge_assist = None
        if bc_assist and pred["p_assist"]:
            edge_assist = pred["p_assist"] * bc_assist - 1.0

        # Position : on prend prioritairement la position annoncée dans la lineup,
        # sinon celle du squad (specific_position puis position).
        pool_p = pool.get(pid, {})
        lines.append({
            "logged_at": logged_at,
            "league_slug": slug,
            "league_name": TOP5_LEAGUES[slug]["name"],
            "event_id": ev_id,
            "match": f"{ev.get('home_team')} - {ev.get('away_team')}",
            "kickoff": ev.get("event_date"),
            "player_id": pid,
            "player_name": pred["name"],
            "team_id": pred["team_id"],
            "team_side": pred["team_side"],
            # Si lineup non confirmée, is_starter est dénué de sens → on remonte None
            # is_starter n'a de sens que si la compo du SIDE du joueur est confirmée
            "is_starter": pred.get("is_starter") if confirmed_by_side.get(pred["team_side"]) else None,
            "is_gk": pred.get("is_gk"),
            "lineup_confirmed": lineup_confirmed,
            "home_lineup_confirmed": home_confirmed,
            "away_lineup_confirmed": away_confirmed,
            "position": pred.get("position_used") or pool_p.get("specific_position")
                        or pool_p.get("position"),
            "availability": pool_p.get("availability") or "available",
            "minutes_expected": pred.get("minutes_expected"),
            "xg_team_home": xg_h,
            "xg_team_away": xg_a,
            "lambdas_method": method,
            "xg_player": pred["xg_calibrated"],
            "xa_player": pred["xa_calibrated"],
            "xg_per_90_used": pred.get("xg_per_90_used"),
            "xa_per_90_used": pred.get("xa_per_90_used"),
            "p_model_scorer": pred["p_scorer"],
            "p_model_assist": pred["p_assist"],
            "fair_odd_scorer": pred["odd_scorer"],
            "fair_odd_assist": pred["odd_assist"],
            "betclic_odd_scorer": bc_scorer,
            "betclic_odd_assist": bc_assist,
            "edge_scorer": edge_scorer,
            "edge_assist": edge_assist,
            # Champs à remplir post-match
            "outcome_scored": None,
            "outcome_assisted": None,
            "outcome_minutes_played": None,
            "enriched_at": None,
        })

    # Lignes "exclus" pour traçabilité côté UI (pas de prédictions, pas de pari)
    for ex in excluded:
        ex_pool = pool.get(ex["player_id"], {})
        lines.append({
            "logged_at": logged_at,
            "league_slug": slug,
            "league_name": TOP5_LEAGUES[slug]["name"],
            "event_id": ev_id,
            "match": f"{ev.get('home_team')} - {ev.get('away_team')}",
            "kickoff": ev.get("event_date"),
            "player_id": ex["player_id"],
            "player_name": ex_pool.get("name", f"id={ex['player_id']}"),
            "team_id": ex["team_id"],
            "team_side": ex["side"],
            "is_starter": None,
            "is_gk": ex_pool.get("is_gk", False),
            "lineup_confirmed": lineup_confirmed,
            "position": ex.get("position") or ex_pool.get("specific_position")
                        or ex_pool.get("position"),
            "availability": ex.get("reason") or ex_pool.get("availability") or "missing",
            "injury_type": ex.get("injury_type"),
            "minutes_expected": 0,
            "xg_team_home": xg_h,
            "xg_team_away": xg_a,
            "lambdas_method": method,
            "xg_player": None, "xa_player": None,
            "xg_per_90_used": None, "xa_per_90_used": None,
            "p_model_scorer": None, "p_model_assist": None,
            "fair_odd_scorer": None, "fair_odd_assist": None,
            "betclic_odd_scorer": None, "betclic_odd_assist": None,
            "edge_scorer": None, "edge_assist": None,
            "outcome_scored": None, "outcome_assisted": None,
            "outcome_minutes_played": None, "enriched_at": None,
            "excluded": True,
        })
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="all",
                    help="Comma-separated slugs (default: all top 5)")
    ap.add_argument("--days", type=int, default=2,
                    help="Nombre de jours à venir à scanner (default: 2)")
    ap.add_argument("--no-betclic", action="store_true",
                    help="Skip scraping Betclic (utile en debug)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Affiche sans écrire dans forward_log.jsonl")
    args = ap.parse_args()

    if args.leagues == "all":
        slugs = list(TOP5_LEAGUES.keys())
    else:
        slugs = [s.strip() for s in args.leagues.split(",") if s.strip() in TOP5_LEAGUES]
    if not slugs:
        log.error("Aucune ligue valide")
        return

    today = date.today()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=args.days)).isoformat()

    # 1. Pools (1× par ligue)
    pools = {slug: load_pool(slug) for slug in slugs}
    for slug, pool in pools.items():
        log.info("Pool %s : %d joueurs", slug, len(pool))

    # 2. Events upcoming (déduplication par event_id pour blinder contre BSD doublons)
    all_events: list[tuple[dict, str]] = []
    seen_event_ids: set[int] = set()
    for slug in slugs:
        evs = get_upcoming_events(TOP5_LEAGUES[slug]["bsd_id"], date_from, date_to)
        log.info("%s : %d matchs entre %s et %s", slug, len(evs), date_from, date_to)
        for ev in evs:
            try:
                eid = int(ev["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if eid in seen_event_ids:
                continue
            seen_event_ids.add(eid)
            all_events.append((ev, slug))

    if not all_events:
        log.info("Aucun match upcoming — rien à faire.")
        return

    # 3. Scrape Betclic en parallèle (1 fois pour toutes les ligues)
    betclic_by_slug: dict[str, list[dict]] = {}
    if not args.no_betclic:
        try:
            betclic_by_slug = asyncio.run(scrape_betclic_leagues(slugs))
        except Exception as e:
            log.warning("Scraping Betclic a échoué : %s — on continue sans odds book", e)

    # 4. Pipeline event par event
    # Le calcul (sans I/O log) reste hors lock pour ne pas bloquer enrich.
    candidate_lines: list[dict] = []
    for ev, slug in all_events:
        ev_id = ev["id"]
        bc_matches = betclic_by_slug.get(slug, [])
        try:
            lines = predict_one_event(ev, slug, pools.get(slug, {}), bc_matches)
        except Exception as e:
            log.exception("Event %s : pipeline error : %s", ev_id, e)
            continue
        candidate_lines.extend(lines)
        log.info("Event %s (%s) : %d lignes candidates (xG team %.2f - %.2f, %s)",
                 ev_id, ev.get("home_team", "")[:18] + " - " + ev.get("away_team", "")[:18],
                 len(lines),
                 lines[0]["xg_team_home"] if lines else 0,
                 lines[0]["xg_team_away"] if lines else 0,
                 lines[0]["lambdas_method"] if lines else "-")

    if args.dry_run:
        log.info("DRY-RUN : %d lignes candidates (non écrites)", len(candidate_lines))
        for ln in candidate_lines[:5]:
            print(json.dumps(ln, indent=2, ensure_ascii=False))
        return

    if not candidate_lines:
        log.info("Aucune ligne candidate.")
        return

    # Section critique : recharge seen sous lock + filtre + append en une seule
    # transaction → résiste aux runs concurrents (2× clic UI / cron+manuel).
    with log_lock(FORWARD_LOG_LOCK, timeout=30.0):
        seen = load_seen_keys()
        new_lines: list[dict] = []
        local_seen: set[tuple[int, int]] = set()
        for ln in candidate_lines:
            key = (int(ln["event_id"]), int(ln["player_id"]))
            if key in seen or key in local_seen:
                continue
            local_seen.add(key)
            new_lines.append(ln)

        if not new_lines:
            log.info("Aucune nouvelle prédiction à logger (toutes déjà présentes).")
            return

        with FORWARD_LOG.open("a") as f:
            for ln in new_lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
        log.info("✅ %d lignes appendées dans %s (%d candidates filtrées)",
                 len(new_lines), FORWARD_LOG, len(candidate_lines) - len(new_lines))


if __name__ == "__main__":
    main()
