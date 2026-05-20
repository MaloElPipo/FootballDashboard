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
from live.bsd_player_id_resolver import resolve_bsd_player_id  # noqa: E402

# === Manual positions (overrides Excel "Buteurs Maison") ===================
# Mapping league_slug → code pays utilisé dans manual_positions.json (Top 5).
LEAGUE_TO_COUNTRY: dict[str, str] = {
    "premier_league": "ENG",
    "la_liga":        "ESP",
    "serie_a":        "ITA",
    "bundesliga":     "GER",
    "ligue_1":        "FRA",
}

_MANUAL_POSITIONS_PATH = DATA_DIR / "manual_positions.json"
_MANUAL_POSITIONS_CACHE: dict | None = None


def _load_manual_positions() -> dict:
    """Charge `manual_positions.json` (cache module). Retourne struct vide
    si le fichier est absent (graceful : la cascade BSD reste fonctionnelle).
    """
    global _MANUAL_POSITIONS_CACHE
    if _MANUAL_POSITIONS_CACHE is not None:
        return _MANUAL_POSITIONS_CACHE
    if not _MANUAL_POSITIONS_PATH.exists():
        _MANUAL_POSITIONS_CACHE = {"by_key": {}, "by_name": {}, "metadata": {}}
        return _MANUAL_POSITIONS_CACHE
    try:
        _MANUAL_POSITIONS_CACHE = json.loads(_MANUAL_POSITIONS_PATH.read_text())
    except Exception:
        _MANUAL_POSITIONS_CACHE = {"by_key": {}, "by_name": {}, "metadata": {}}
    return _MANUAL_POSITIONS_CACHE


def _norm_for_match(s: str | None) -> str:
    """Normalisation pour matching nom/équipe (lowercase + sans accents)."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s).strip())
    s = "".join(c for c in nfkd if not unicodedata.combining(c)).lower()
    for ch in (".", ",", "'", "-"):
        s = s.replace(ch, " ")
    return " ".join(s.split())


def lookup_manual_position(player_name: str | None,
                            team_name: str | None,
                            league_slug: str | None) -> str | None:
    """Retourne le poste BSD (ST, SS, RW, CB, …) trouvé dans l'Excel manuel,
    ou None. Matching à 2 niveaux :
      1) clé exacte `nom|équipe|pays` (priorité — preuve forte)
      2) nom seul + même pays si UN seul candidat (récupère les transferts
         intra-ligue où l'Excel n'a pas encore été remis à jour).
    """
    if not player_name:
        return None
    country = LEAGUE_TO_COUNTRY.get(league_slug or "")
    if not country:
        return None
    mp = _load_manual_positions()
    nm = _norm_for_match(player_name)
    team = _norm_for_match(team_name)
    key = f"{nm}|{team}|{country}"
    if key in mp["by_key"]:
        return mp["by_key"][key]
    cands = mp["by_name"].get(nm) or []
    same_country = [c for c in cands if c.get("country") == country]
    if len(same_country) == 1:
        return same_country[0].get("poste")
    return None


# === Codes positions BSD niveau "fin" (à conserver tels quels pour affichage) ==
# Source: distribution observée dans squads BSD + spec_position retournés par /players.
# Inclut variantes US (CAM/CDM/LWB/RWB/CF/SS) au cas où BSD les remonte.
_BSD_FINE_POSITION_CODES: frozenset[str] = frozenset({
    "GK",
    # Defenders
    "CB", "RB", "LB", "RWB", "LWB",
    # Midfielders
    "CM", "DM", "AM", "RM", "LM", "CAM", "CDM",
    # Forwards
    "ST", "CF", "SS", "RW", "LW",
})
# Codes "grossiers" qu'on garde tels quels en fallback (lisibles : MID/DEF/FWD)
_BSD_COARSE_POSITION_CODES: frozenset[str] = frozenset({"GK", "DEF", "MID", "FWD"})


def resolve_detailed_position(player: dict | None,
                                lineup_position: str | None = None) -> str | None:
    """Cascade de résolution de la position affichée :
       0) `manual_position` (override depuis l'Excel "Buteurs Maison") si présent,
       1) `lineup_position` (annoncé par BSD pour CE match) si code fin,
       2) `positions_detailed[0]` du squad si non vide,
       3) `specific_position` si code fin (ST, CM, CB, …),
       4) `specific_position` grossier (MID/DEF/FWD/GK),
       5) `position` générique (M/D/F/G) en dernier recours.

    Le step 0 est prioritaire car l'Excel propriétaire de l'utilisateur
    (~2 500 joueurs Top 5) annote des positions fines (ex: AT/SS pour
    Griezmann, AD/RW pour Salah) que BSD remonte en grossier (FWD/MID).
    """
    # 0) Override manuel Excel (priorité absolue)
    if isinstance(player, dict):
        mpos = player.get("manual_position")
        if mpos:
            mp = str(mpos).strip().upper()
            if mp:
                return mp

    # 1) Lineup explicite (peut être un code fin remonté par BSD)
    if lineup_position:
        lp = str(lineup_position).strip().upper()
        if lp in _BSD_FINE_POSITION_CODES:
            return lp

    if not isinstance(player, dict):
        return (str(lineup_position).upper() if lineup_position else None)

    # 2) positions_detailed (le plus précis quand renseigné)
    pdet = player.get("positions_detailed") or []
    if isinstance(pdet, list) and pdet:
        first = str(pdet[0]).strip().upper()
        if first:
            return first

    # 3-4) specific_position (peut être fin OU grossier)
    spec = player.get("specific_position")
    if spec:
        s = str(spec).strip().upper()
        if s in _BSD_FINE_POSITION_CODES or s in _BSD_COARSE_POSITION_CODES:
            return s
        if s:
            return s  # any non-empty value, rare

    # 5) position générique 1 lettre
    pos = player.get("position")
    if pos:
        return str(pos).strip().upper()
    return None


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


def compute_team_match_counts(events: dict) -> dict[int, int]:
    """Pour chaque team_id, compte les matchs joués (= avec stats) dans la saison.
    Sert de dénominateur pour `start_rate = starts / team_matches`."""
    counts: dict[int, int] = {}
    for ev in events.values():
        for k in ("home_team_obj", "away_team_obj"):
            tid = (ev.get(k) or {}).get("id") if isinstance(ev.get(k), dict) else None
            if tid is not None:
                counts[int(tid)] = counts.get(int(tid), 0) + 1
    return counts


def compute_start_rates(pool: dict, team_match_counts: dict[int, int]) -> None:
    """Mute le pool : ajoute pool[pid]['start_rate'] = starts / team_matches.
    Mesure de "régularité titulaire" sur la saison courante. Plafonné à 1.0 pour
    se prémunir contre des arrondis du compteur de starts (T002 weights)."""
    for p in pool.values():
        tid = p.get("team_id")
        n = team_match_counts.get(int(tid), 0) if tid is not None else 0
        starts = p.get("starts", 0) or 0
        p["start_rate"] = min(starts / n, 1.0) if n > 0 else 0.0


def compute_lineup_confidence(lineup_players: list[dict], pool: dict) -> dict[str, float]:
    """Pour chaque side, retourne la moyenne des `start_rate` des titulaires
    présumés (top-11). 1.0 = onze type qui ne change jamais ; 0.5 = forte rotation."""
    out: dict[str, float] = {"home": 0.0, "away": 0.0}
    for side in ("home", "away"):
        starters = [lp for lp in lineup_players
                    if lp["side"] == side and lp.get("is_starter")]
        if not starters:
            continue
        rates = [(pool.get(lp["player_id"]) or {}).get("start_rate", 0.0)
                 for lp in starters[:11]]
        if rates:
            out[side] = sum(rates) / len(rates)
    return out


def build_lineup_fallback(team_id: int, team_side: str, pool: dict, n_starters: int = 11,
                          n_subs: int = 6) -> list[dict]:
    """Si BSD n'a pas de lineup, on présume le onze probable via le **taux de
    titularisation historique** (`start_rate = starts/team_matches`) plutôt que
    via `minutes_total`. Avantage : un joueur qui a fait beaucoup de minutes en
    rentrant (sub à 30min × 25 matchs = 750 min) ne supplante pas un titulaire
    qui a manqué 5 matchs (10 starts × 85min = 850 min mais start_rate plus haut).
    Tie-break sur `minutes_total` pour départager 2 joueurs au même rate.
    Les joueurs non-disponibles (blessés / suspendus) sont systématiquement exclus.

    H1 fix : on garantit qu'au moins 1 gardien (`is_gk=True`) figure parmi les
    titulaires présumés. Sans cette contrainte, une équipe alternant 2 GK 50/50
    pouvait se retrouver avec 11 joueurs de champ dans le top-11 (dilution xG +
    `lineup_confidence` faussée)."""
    players = [(pid, p) for pid, p in pool.items()
               if p.get("team_id") == team_id and not is_player_unavailable(p)]
    players.sort(key=lambda x: (x[1].get("start_rate", 0.0),
                                x[1].get("minutes_total", 0.0)), reverse=True)
    # H1 : sélection garantie d'1 GK parmi les titulaires si dispo dans le pool
    gks = [(pid, p) for pid, p in players if p.get("is_gk")]
    starters_picked: list[tuple] = []
    if gks:
        starters_picked.append(gks[0])  # GK le plus titularisé
    # Compléter avec les meilleurs non-GK jusqu'à n_starters
    for pid, p in players:
        if len(starters_picked) >= n_starters:
            break
        if p.get("is_gk"):
            continue  # GK déjà inclus (ou aucun)
        starters_picked.append((pid, p))
    starters_pids = {pid for pid, _ in starters_picked}
    # Subs : suivants dans l'ordre du tri, hors titulaires déjà pris
    subs_picked: list[tuple] = []
    for pid, p in players:
        if pid in starters_pids:
            continue
        if len(subs_picked) >= n_subs:
            break
        subs_picked.append((pid, p))
    out = []
    for pid, p in starters_picked:
        out.append({
            "player_id": pid, "team_id": team_id, "side": team_side,
            "is_starter": True,
            "position": "G" if p.get("is_gk") else None,
        })
    for pid, p in subs_picked:
        out.append({
            "player_id": pid, "team_id": team_id, "side": team_side,
            "is_starter": False,
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

    def _add(pid, team_id, side, is_starter, position, force_include=False):
        """Ajoute un joueur à `out`. Si `force_include=True` (cas BSD lineup
        confirmée → ex: Sorloth annoncé blessé mais finalement titulaire),
        on bypasse le filtre `is_player_unavailable` car BSD est source de
        vérité. Sinon, joueur indispo → skip + entry dans `excluded` (sera
        réinjecté plus loin avec is_unavailable=True pour affichage UI)."""
        if pid is None:
            return
        pid = int(pid)
        if pid in seen_pids:
            return
        # Filtrage blessés / suspendus (sauf override BSD)
        if not force_include and is_player_unavailable(pool.get(pid)):
            excluded.append({
                "player_id": pid, "team_id": team_id, "side": side,
                "is_starter": is_starter, "position": position,
                "reason": (pool.get(pid) or {}).get("availability"),
                "injury_type": (pool.get(pid) or {}).get("injury_type"),
            })
            return
        seen_pids.add(pid)
        out.append({"player_id": pid, "team_id": team_id, "side": side,
                    "is_starter": is_starter, "position": position,
                    "is_unavailable": False})

    for side, team_id in (("home", home_id), ("away", away_id)):
        side_block = lineups.get(side) if isinstance(lineups, dict) else None
        side_has_lineup = bool(side_block and (side_block.get("starters")
                                                or side_block.get("starting")))
        if side_has_lineup:
            confirmed_by_side[side] = True
            starters = side_block.get("starters") or side_block.get("starting") or []
            subs = side_block.get("substitutes") or side_block.get("subs") or []
            # T011 : force_include=True → BSD a confirmé sa présence, on outrepasse
            # le flag `availability=injured` qui peut traîner du squad cache.
            for p in starters:
                if isinstance(p, dict):
                    pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                    _add(pid, team_id, side, True, p.get("position"), force_include=True)
            for p in subs:
                if isinstance(p, dict):
                    pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                    _add(pid, team_id, side, False, p.get("position"), force_include=True)

        # Si pas de lineup confirmée pour ce côté → fallback : on prend les 17 joueurs
        # avec le plus de minutes saison via build_lineup_fallback (top-11 starters
        # + 6 subs présumés). distribute_xg_to_players → _resolve_minutes honore
        # is_starter même si confirmed_by_side[side]=False : starters reçoivent
        # avg_mins_when_starter (~85), subs reçoivent MINUTES_SUB_DEFAULT=25.
        # Évite la dilution xG (17×90=1530 player-min vs réalité 11×85+6×15=1025)
        # qui faisait tomber Salah à 15% au lieu de 25-30%.
        if not any(lp["side"] == side for lp in out):
            for lp in build_lineup_fallback(team_id, side, pool):
                _add(lp["player_id"], team_id, side, lp["is_starter"], lp.get("position"))

    # T011 : ajout des joueurs blessés / suspendus du pool qui n'ont pas été
    # inclus via BSD lineup ou fallback. Ils apparaissent dans la table de
    # prédiction avec is_unavailable=True → checkbox UI décochée par défaut.
    # L'utilisateur peut les réactiver manuellement (ex: rumeur "rétabli last
    # minute") → recalcul live des shares xG via `_recalculate_shares`.
    for pid, p in pool.items():
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            continue
        if pid_int in seen_pids:
            continue
        if not is_player_unavailable(p):
            continue
        tid = p.get("team_id")
        if tid == home_id:
            side_u = "home"
        elif tid == away_id:
            side_u = "away"
        else:
            continue
        seen_pids.add(pid_int)
        out.append({"player_id": pid_int, "team_id": tid, "side": side_u,
                    "is_starter": False, "position": p.get("position"),
                    "is_unavailable": True})
    return out, confirmed_by_side, excluded


# ---------------------------------------------------------------------------
# Pool joueurs
# ---------------------------------------------------------------------------
def assign_team_ids_via_squads(pool: dict, league_team_ids: list[int],
                                cache_path: Path,
                                refresh_squads: bool = False,
                                league_slug: str | None = None) -> int:
    """Pour chaque équipe de la ligue, récupère l'effectif actuel via BSD
    `/players/?team={id}` et assigne `team_id` (résout transferts hiver).
    Aussi : propage `position`, `specific_position`, `availability`, `injury_type`,
    et `manual_position` (override Excel "Buteurs Maison" si trouvé pour la ligue).
    Cache 24h dans `{league}_squads.json` (bypass via `refresh_squads=True`).
    """
    cache: dict[int, list[dict]] = {}
    use_cache = False
    if cache_path.exists() and not refresh_squads:
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
    n_manual_pos = 0  # joueurs ayant reçu un override Excel
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
            squad_positions_detailed = p.get("positions_detailed") or []

            # Manual position override (Excel) — calcul via nom + équipe + ligue
            ct = p.get("current_team")
            team_name_for_match = ct.get("name") if isinstance(ct, dict) else (ct or None)
            manual_pos = lookup_manual_position(
                p.get("name"), team_name_for_match, league_slug,
            )
            # Auto-fallback : si pas d'override Excel et joueur est gardien
            # connu de BSD, force "GK" (l'Excel ne renseigne pas les gardiens).
            if not manual_pos and squad_position == "G":
                manual_pos = "GK"
            if manual_pos:
                n_manual_pos += 1

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
                if squad_positions_detailed:
                    pool[pid]["positions_detailed"] = squad_positions_detailed
                if manual_pos:
                    pool[pid]["manual_position"] = manual_pos
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
                    "positions_detailed": squad_positions_detailed,
                    "manual_position": manual_pos,
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
                    "shots_on_target_total": 0,
                    "key_pass_total": 0,
                    "starts": 0,
                    "starter_minutes_sum": 0,
                    "xg_per_90": 0.0, "xa_per_90": 0.0, "shots_per_90": 0.0,
                    "shots_on_target_per_90": 0.0,
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


def load_pool(slug: str, refresh_squads: bool = False) -> dict:
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
    n_assigned = assign_team_ids_via_squads(pool, sorted(team_ids), cache_path,
                                             refresh_squads=refresh_squads,
                                             league_slug=slug)
    n_with_team = sum(1 for p in pool.values() if p.get("team_id") is not None)
    n_manual = sum(1 for p in pool.values() if p.get("manual_position"))
    log.info("Pool %s : %d joueurs (%d/%d ont team_id, %d assignations via squads, "
             "%d positions Excel)",
             slug, len(pool), n_with_team, len(pool), n_assigned, n_manual)

    # T008 — start_rate par joueur (saison courante) : sert de tri pour
    # build_lineup_fallback (compo probable basée sur l'historique de
    # titularisations) et de base au lineup_confidence par équipe.
    team_match_counts = compute_team_match_counts(raw["events"])
    compute_start_rates(pool, team_match_counts)
    n_regulars = sum(1 for p in pool.values() if p.get("start_rate", 0) >= 0.7)
    log.info("Pool %s : %d \"titulaires réguliers\" (start_rate >= 70%%)",
             slug, n_regulars)

    # Overrides manuels (transferts/prêts non reflétés par BSD)
    from live.transfer_overrides import apply_to_pool as _apply_overrides
    n_overrides = _apply_overrides(pool, slug)
    if n_overrides:
        log.info("Pool %s : %d joueur(s) marqué(s) indisponible(s) via overrides", slug, n_overrides)

    # T002+T003 — Enrichissement avec stats carrière (Understat archive 4 saisons
    # + BSD increment courant). Pas bloquant : si le cache n'existe pas le pool
    # reste utilisable et le moteur retombe sur le shrinkage saison courante.
    try:
        from live.career_stats import load_career_cache, enrich_pool_with_career
        career_cache = load_career_cache()
        if career_cache:
            matched, total = enrich_pool_with_career(pool, career_cache)
            log.info("Pool %s : carrière enrichie pour %d/%d joueurs", slug, matched, total)
        else:
            log.warning("Pool %s : pas de career_stats_cache.json (lance "
                        "`python -m live.career_stats build`)", slug)
    except Exception as e:
        log.warning("Pool %s : enrichissement carrière échoué (%s)", slug, e)

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
def load_existing_log() -> tuple[list[dict], dict[tuple[int, int], int]]:
    """Charge tout le forward_log et indexe par (event_id, player_id) → row index.

    Permet l'upsert : on remplace les lignes pré-kickoff (sans `outcome_scored`)
    par leur nouvelle version, et on protège strictement celles déjà enrichies
    post-match. Évite les blocages de refresh quand les compos officielles
    arrivent tardivement (ex. 1h avant kickoff).
    """
    rows: list[dict] = []
    index: dict[tuple[int, int], int] = {}
    if not FORWARD_LOG.exists():
        return rows, index
    with FORWARD_LOG.open() as f:
        for line in f:
            try:
                d = json.loads(line)
                key = (int(d["event_id"]), int(d["player_id"]))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
            # Si doublon (legacy), on garde la dernière (post-match wins)
            if key in index:
                rows[index[key]] = d
            else:
                index[key] = len(rows)
                rows.append(d)
    return rows, index


def load_seen_keys() -> set[tuple[int, int]]:
    """[DEPRECATED] Conservé pour compat ; préférer `load_existing_log`."""
    _, idx = load_existing_log()
    return set(idx.keys())


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

    # T008 — confiance compo probable (moyenne start_rate des 11 titulaires présumés)
    lineup_conf = compute_lineup_confidence(lineup_players, pool)

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
            "bsd_player_id": resolve_bsd_player_id(pid, pred.get("name"), pred.get("team_id")),
            "player_name": pred["name"],
            "team_id": pred["team_id"],
            "team_side": pred["team_side"],
            # Si lineup non confirmée, is_starter est dénué de sens → on remonte None
            # is_starter n'a de sens que si la compo du SIDE du joueur est confirmée
            "is_starter": pred.get("is_starter") if confirmed_by_side.get(pred["team_side"]) else None,
            # T008 — onze probable basé sur historique titularisations (dispo
            # aussi quand BSD n'a pas confirmé la compo). Permet à l'UI de cocher
            # par défaut uniquement les 11 présumés titulaires.
            # H2 : `is_presumed_starter` ne porte de l'information QUE quand la
            # compo de ce side n'est pas encore confirmée par BSD. Sinon `None`
            # pour éviter toute confusion à la relecture du log (sinon on
            # mélangerait la valeur BSD officielle et le top-11 historique).
            "is_presumed_starter": (
                pred.get("is_starter")
                if not confirmed_by_side.get(pred["team_side"]) else None
            ),
            "start_rate": pool_p.get("start_rate"),
            "is_gk": pred.get("is_gk"),
            "lineup_confirmed": lineup_confirmed,
            "home_lineup_confirmed": home_confirmed,
            "away_lineup_confirmed": away_confirmed,
            "lineup_confidence_home": lineup_conf.get("home"),
            "lineup_confidence_away": lineup_conf.get("away"),
            "position": resolve_detailed_position(pool_p, pred.get("position_used")),
            "availability": pool_p.get("availability") or "available",
            # T011 — flag joueur indispo réinjecté pour affichage UI (décoché
            # par défaut, mais cliquable pour réactivation manuelle).
            "is_unavailable": bool(pred.get("is_unavailable", False)),
            "injury_type": pool_p.get("injury_type") or None,
            "minutes_expected": pred.get("minutes_expected"),
            "xg_team_home": xg_h,
            "xg_team_away": xg_a,
            "lambdas_method": method,
            "xg_player": pred["xg_calibrated"],
            "xa_player": pred["xa_calibrated"],
            "xg_per_90_used": pred.get("xg_per_90_used"),
            "xa_per_90_used": pred.get("xa_per_90_used"),
            # T010 — expected shots & SoT (descriptifs, basés sur minutes_expected
            # et shots_per_90 / shots_on_target_per_90 des stats roulées BSD).
            "expected_shots": pred.get("expected_shots"),
            "expected_shots_on_target": pred.get("expected_shots_on_target"),
            "shots_per_90_used": pred.get("shots_per_90_used"),
            "shots_on_target_per_90_used": pred.get("shots_on_target_per_90_used"),
            # T003 — traçabilité du blend carrière
            "confidence_ratio": pred.get("confidence_ratio", 0.0),
            "career_used": bool(pred.get("career_used", False)),
            "career_minutes": pred.get("career_minutes", 0.0),
            "career_goals": pred.get("career_goals", 0.0),
            "p_model_scorer": pred["p_scorer"],
            "p_model_assist": pred["p_assist"],
            "fair_odd_scorer": pred["odd_scorer"],
            "fair_odd_assist": pred["odd_assist"],
            # T008 — shadow odds : cote-si-titulaire (= cote actuelle pour les
            # titulaires, cote simulée à mins_starter pour les subs présumés).
            # Sert à voir d'un coup d'œil quel sub serait dangereux s'il était
            # finalement titulaire (cas Zirkzee MUFC).
            "p_scorer_if_starter": pred.get("p_scorer_if_starter"),
            "p_assist_if_starter": pred.get("p_assist_if_starter"),
            "fair_odd_scorer_if_starter": pred.get("odd_scorer_if_starter"),
            "fair_odd_assist_if_starter": pred.get("odd_assist_if_starter"),
            # T009 — versionnage pricing : à partir d'avril 2026, fair_odd_scorer
            # / fair_odd_assist sont calculés à 90' théorique (garantie buteur
            # FR Betclic). Permet de segmenter les analyses backtest pré/post.
            "model_version": "t009_90min_theoretical",
            "pricing_mode": "90min_theoretical",
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

    # T011 : ancien path "excluded" supprimé (était dead code après T011 — les
    # blessés sont maintenant réinjectés directement dans `out` avec
    # is_unavailable=True via resolve_match_lineup, et passent par le moteur
    # `distribute_xg_to_players` pour produire une ligne forward log normale
    # avec xg_per_90_used préservé → permet la réactivation manuelle UI).
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
    ap.add_argument("--refresh-squads", action="store_true",
                    help="Force le refetch des squads BSD (bypass cache 24h)")
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
    pools = {slug: load_pool(slug, refresh_squads=args.refresh_squads) for slug in slugs}
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

    # 2.b Construit team_id→name à partir des events upcoming + ré-enrichit
    # les pools career avec ce mapping (résout désambiguation des homonymes
    # type Emerson/Marquinhos/João Pedro). Idempotent : ne fait que ré-écrire
    # career_* sur les joueurs des équipes effectivement en jeu cette semaine.
    team_id_to_name: dict[int, str] = {}
    for ev, _slug in all_events:
        for side in ("home_team_obj", "away_team_obj"):
            obj = ev.get(side) or {}
            tid = obj.get("id")
            if tid is None:
                continue
            tname = ev.get("home_team" if side == "home_team_obj" else "away_team")
            if tname:
                team_id_to_name[int(tid)] = tname
    if team_id_to_name:
        try:
            from live.career_stats import load_career_cache, enrich_pool_with_career
            career_cache = load_career_cache()
            if career_cache:
                for slug, pool in pools.items():
                    enrich_pool_with_career(pool, career_cache, team_id_to_name=team_id_to_name)
                log.info("  Ré-enrichissement carrière avec %d team names (désambiguation)",
                         len(team_id_to_name))
        except Exception as e:
            log.warning("Ré-enrichissement carrière avec team_hint échoué : %s", e)

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

    # Section critique : upsert pré-kickoff + purge des orphelins, sous lock.
    # - Lignes déjà enrichies post-match (outcome_scored != None) → IMMUABLES
    # - Lignes pré-kickoff existantes (même event_id régénéré) :
    #     • si pid dans les nouvelles prédictions → REMPLACÉES
    #     • si pid absent (joueur transféré/blessé entre 2 runs) → SUPPRIMÉES
    # - Lignes d'events non régénérés cette fois → CONSERVÉES intactes
    # - Nouvelles clés → AJOUTÉES
    with log_lock(FORWARD_LOG_LOCK, timeout=30.0):
        rows, index = load_existing_log()

        # Pids "frais" par event_id pour cette run
        fresh_by_event: dict[int, set[int]] = {}
        local_seen: set[tuple[int, int]] = set()
        deduped_candidates: list[dict] = []
        for ln in candidate_lines:
            key = (int(ln["event_id"]), int(ln["player_id"]))
            if key in local_seen:
                continue  # doublon dans le batch
            local_seen.add(key)
            fresh_by_event.setdefault(int(ln["event_id"]), set()).add(int(ln["player_id"]))
            deduped_candidates.append(ln)

        # Purge des orphelins pré-kickoff pour les events régénérés.
        # Garde-fou : si la nouvelle cardinalité d'un event est suspectement basse
        # (run partiel, fetch BSD instable), on N'opère PAS la purge pour cet event
        # afin d'éviter de supprimer des prédictions légitimes du run précédent.
        # Seuil : 10 joueurs minimum (un effectif réel a > 25 actifs).
        MIN_FRESH_PLAYERS_TO_PURGE = 10
        events_safe_to_purge = {
            eid for eid, pids in fresh_by_event.items()
            if len(pids) >= MIN_FRESH_PLAYERS_TO_PURGE
        }
        events_skipped_purge = set(fresh_by_event) - events_safe_to_purge
        if events_skipped_purge:
            log.warning(
                "⚠ Purge orphelins SKIPPÉE pour %d event(s) avec < %d joueurs frais "
                "(suspect run partiel) : %s",
                len(events_skipped_purge), MIN_FRESH_PLAYERS_TO_PURGE,
                sorted(events_skipped_purge),
            )

        n_purged = 0
        kept_rows: list[dict] = []
        for r in rows:
            try:
                eid = int(r.get("event_id"))
                pid = int(r.get("player_id"))
            except (TypeError, ValueError):
                kept_rows.append(r)
                continue
            if eid in events_safe_to_purge \
                    and pid not in fresh_by_event[eid] \
                    and r.get("outcome_scored") is None:
                n_purged += 1
                continue  # orphelin pré-kickoff
            kept_rows.append(r)
        rows = kept_rows
        # Réindexation après purge
        index = {(int(r["event_id"]), int(r["player_id"])): i
                 for i, r in enumerate(rows)
                 if r.get("event_id") is not None and r.get("player_id") is not None}

        n_protected = n_upserted = n_inserted = 0
        for ln in deduped_candidates:
            key = (int(ln["event_id"]), int(ln["player_id"]))
            if key in index:
                existing = rows[index[key]]
                if existing.get("outcome_scored") is not None:
                    n_protected += 1  # post-match : on touche pas
                    continue
                rows[index[key]] = ln  # upsert pré-kickoff
                n_upserted += 1
            else:
                index[key] = len(rows)
                rows.append(ln)
                n_inserted += 1

        if not (n_upserted or n_inserted or n_purged):
            log.info("Forward log inchangé (%d candidates protégées post-match).",
                     n_protected)
            return

        # Réécriture atomique : tmp + rename
        tmp_path = FORWARD_LOG.with_suffix(".jsonl.tmp")
        with tmp_path.open("w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp_path.replace(FORWARD_LOG)
        log.info("✅ Forward log : %d insertions, %d upserts, %d purgés (orphelins), %d protégées (post-match).",
                 n_inserted, n_upserted, n_purged, n_protected)


if __name__ == "__main__":
    main()
