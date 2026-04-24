"""
Étapes C+D — Moteur de distribution xG team → joueur + pricing Poisson.
Prend des stats agrégées avant un match donné (leave-one-out temporel).

Fonctions principales:
  - aggregate_player_pool(stats_until_date) -> dict[player_id] -> profile
  - distribute_team_xg(xg_team, lineup, pool) -> dict[player_id] -> xG attendu
  - poisson_anytime(lambda_) -> proba >= 1 occurrence
"""
import math
from collections import defaultdict
from datetime import datetime


# Hyperparamètres calibrables
MINUTES_STARTER_DEFAULT = 78.0   # minutes moyennes attendues pour un titulaire
MINUTES_SUB_DEFAULT = 25.0       # minutes moyennes attendues pour un remplaçant
SHRINKAGE_K = 8.0                # nb "matchs prior" pour shrinkage bayésien
LEAGUE_PRIOR_XG90_OUTFIELD = 0.10  # xG/90 moyen joueur de champ Bundesliga (fallback)
LEAGUE_PRIOR_XA90_OUTFIELD = 0.08  # xA/90 moyen
LEAGUE_PRIOR_XG90_GK = 0.0
LEAGUE_PRIOR_XA90_GK = 0.0


def _safe_float(x, default=0.0):
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_event_date(ev):
    """Retourne datetime ou None."""
    s = ev.get("event_date")
    if not s:
        return None
    try:
        # format ISO avec offset
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_goalkeeper(stat_row):
    """Heuristique: a-t-il fait des saves ? Ou position connue ?"""
    pos = (stat_row.get("position") or "").upper()
    if pos in ("G", "GK", "GOALKEEPER"):
        return True
    saves = _safe_float(stat_row.get("saves"))
    return saves > 0


def aggregate_player_pool(player_stats_by_event, matches_by_id, until_date=None):
    """
    Calcule pour chaque joueur ses stats roulées (toute la saison ou jusqu'à until_date exclu).
    Returns: dict[player_id] -> {
        'name', 'team_id', 'is_gk',
        'minutes_total', 'matches_played', 'starts',
        'xg_total', 'xa_total', 'shots_total', 'key_pass_total',
        'goals_total', 'assists_total',
        'xg_per_90', 'xa_per_90', 'shots_per_90',
        'avg_mins_when_starter',
    }
    """
    agg = defaultdict(lambda: {
        "name": None, "team_id": None, "is_gk": False,
        "minutes_total": 0.0, "matches_played": 0, "starts": 0,
        "xg_total": 0.0, "xa_total": 0.0, "shots_total": 0.0, "key_pass_total": 0.0,
        "goals_total": 0.0, "assists_total": 0.0,
        "starter_minutes_sum": 0.0,
    })

    for eid_str, ev_block in player_stats_by_event.items():
        eid = int(eid_str)
        ev = matches_by_id.get(eid_str) or matches_by_id.get(eid)
        if ev is None:
            continue
        ev_date = parse_event_date(ev)
        if until_date and ev_date and ev_date >= until_date:
            continue  # leave-one-out temporel

        for s in ev_block.get("stats", []):
            p = s.get("player")
            if isinstance(p, dict):
                pid = p.get("id"); pname = p.get("name")
            else:
                pid = p; pname = s.get("player_name")
            if pid is None:
                continue
            mins = _safe_float(s.get("minutes_played"))
            if mins <= 0:
                continue  # n'a pas joué

            a = agg[pid]
            a["name"] = a["name"] or pname
            tid = s.get("team")
            if isinstance(tid, dict): tid = tid.get("id")
            a["team_id"] = a["team_id"] or tid
            a["is_gk"] = a["is_gk"] or is_goalkeeper(s)
            a["minutes_total"] += mins
            a["matches_played"] += 1
            if mins >= 60:
                a["starts"] += 1
                a["starter_minutes_sum"] += mins
            a["xg_total"] += _safe_float(s.get("expected_goals"))
            a["xa_total"] += _safe_float(s.get("expected_assists"))
            a["shots_total"] += _safe_float(s.get("total_shots"))
            a["key_pass_total"] += _safe_float(s.get("key_pass"))
            a["goals_total"] += _safe_float(s.get("goals"))
            a["assists_total"] += _safe_float(s.get("goal_assist"))

    # Calcul derived stats
    for pid, a in agg.items():
        if a["minutes_total"] > 0:
            factor = 90.0 / a["minutes_total"]
            a["xg_per_90"] = a["xg_total"] * factor
            a["xa_per_90"] = a["xa_total"] * factor
            a["shots_per_90"] = a["shots_total"] * factor
        else:
            a["xg_per_90"] = a["xa_per_90"] = a["shots_per_90"] = 0.0
        a["avg_mins_when_starter"] = (
            a["starter_minutes_sum"] / a["starts"] if a["starts"] > 0 else MINUTES_STARTER_DEFAULT
        )
    return dict(agg)


def shrunk_per90(player, metric, league_prior, k=SHRINKAGE_K):
    """Shrinkage bayésien: combine observation joueur avec prior ligue."""
    matches = player.get("matches_played", 0)
    obs = player.get(metric, 0.0)
    if matches == 0:
        return league_prior
    return (matches * obs + k * league_prior) / (matches + k)


def get_lineup_players(event):
    """
    Extrait depuis event['lineups'] la liste des joueurs avec leur statut.
    Returns: list of dicts [{player_id, team_id, is_starter, position?}]
    """
    out = []
    lineups = event.get("lineups") or {}
    if not lineups:
        return out
    for side, key in (("home", "home_team"), ("away", "away_team")):
        side_block = lineups.get(side) if isinstance(lineups, dict) else None
        if not side_block:
            continue
        team_id = (event.get(f"{key}_obj") or {}).get("id") if isinstance(event.get(f"{key}_obj"), dict) else None
        starters = side_block.get("starters") or side_block.get("starting") or []
        subs = side_block.get("substitutes") or side_block.get("subs") or []
        for p in starters:
            if isinstance(p, dict):
                pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                out.append({"player_id": pid, "team_id": team_id, "side": side, "is_starter": True,
                            "position": p.get("position")})
        for p in subs:
            if isinstance(p, dict):
                pid = p.get("player_id") or p.get("id") or (p.get("player") or {}).get("id")
                out.append({"player_id": pid, "team_id": team_id, "side": side, "is_starter": False,
                            "position": p.get("position")})
    return out


def distribute_xg_to_players(xg_home, xg_away, home_team_id, away_team_id, lineup_players, pool):
    """
    Pour chaque joueur de la lineup, calcule son xG_attendu et xA_attendu.
    Normalisation: somme des xG joueurs d'une équipe = xG_team.

    Returns: dict[player_id] -> {
        'team_side', 'name', 'minutes_expected',
        'xg_raw', 'xa_raw', 'xg_calibrated', 'xa_calibrated',
        'p_scorer', 'p_assist', 'odd_scorer', 'odd_assist'
    }
    """
    result = {}

    for side, team_xg, team_id in (("home", xg_home, home_team_id), ("away", xg_away, away_team_id)):
        team_lineup = [lp for lp in lineup_players if lp["side"] == side]
        if not team_lineup or team_xg is None:
            continue

        # 1. xG/xA bruts par joueur (avec shrinkage + minutes attendues)
        raw_xg_per_player = {}
        raw_xa_per_player = {}
        for lp in team_lineup:
            pid = lp["player_id"]
            if pid is None:
                continue
            player = pool.get(pid)
            if player is None:
                # Joueur inconnu → utilise priors ligue
                xg_p90 = LEAGUE_PRIOR_XG90_OUTFIELD
                xa_p90 = LEAGUE_PRIOR_XA90_OUTFIELD
                is_gk = False
                avg_starter_min = MINUTES_STARTER_DEFAULT
            else:
                is_gk = player.get("is_gk", False)
                prior_xg = LEAGUE_PRIOR_XG90_GK if is_gk else LEAGUE_PRIOR_XG90_OUTFIELD
                prior_xa = LEAGUE_PRIOR_XA90_GK if is_gk else LEAGUE_PRIOR_XA90_OUTFIELD
                xg_p90 = shrunk_per90(player, "xg_per_90", prior_xg)
                xa_p90 = shrunk_per90(player, "xa_per_90", prior_xa)
                avg_starter_min = player.get("avg_mins_when_starter", MINUTES_STARTER_DEFAULT)

            mins_exp = avg_starter_min if lp["is_starter"] else MINUTES_SUB_DEFAULT
            raw_xg = xg_p90 * (mins_exp / 90.0)
            raw_xa = xa_p90 * (mins_exp / 90.0)

            raw_xg_per_player[pid] = raw_xg
            raw_xa_per_player[pid] = raw_xa
            result[pid] = {
                "team_side": side, "team_id": team_id,
                "name": (player or {}).get("name", f"id={pid}"),
                "is_starter": lp["is_starter"], "is_gk": is_gk,
                "minutes_expected": mins_exp,
                "xg_per_90_used": xg_p90, "xa_per_90_used": xa_p90,
                "xg_raw": raw_xg, "xa_raw": raw_xa,
            }

        # 2. Normalisation: somme xG joueurs = xG team
        total_raw_xg = sum(raw_xg_per_player.values()) or 1e-9
        total_raw_xa = sum(raw_xa_per_player.values()) or 1e-9
        # xA total ≈ goals - solo_goals ≈ ~0.75 * team_xg (75% des buts ont une passe dec)
        team_xa_target = team_xg * 0.75

        for pid in raw_xg_per_player:
            xg_cal = team_xg * (raw_xg_per_player[pid] / total_raw_xg)
            xa_cal = team_xa_target * (raw_xa_per_player[pid] / total_raw_xa)
            p_scorer = 1.0 - math.exp(-xg_cal)
            p_assist = 1.0 - math.exp(-xa_cal)
            result[pid]["xg_calibrated"] = xg_cal
            result[pid]["xa_calibrated"] = xa_cal
            result[pid]["p_scorer"] = p_scorer
            result[pid]["p_assist"] = p_assist
            result[pid]["odd_scorer"] = (1.0 / p_scorer) if p_scorer > 0 else None
            result[pid]["odd_assist"] = (1.0 / p_assist) if p_assist > 0 else None

    return result


if __name__ == "__main__":
    # Smoke test
    import json
    from pathlib import Path

    DATA = Path(__file__).parent / "data"
    matches = json.loads((DATA / "bundesliga_matches.json").read_text())["events"]
    stats = json.loads((DATA / "bundesliga_player_stats.json").read_text())["by_event"]

    # Pool sur toute la saison
    pool = aggregate_player_pool(stats, matches)
    print(f"Pool joueurs: {len(pool)}")
    # Top scorers/passeurs
    top_xg = sorted(pool.values(), key=lambda p: p.get("xg_total", 0), reverse=True)[:10]
    print("\nTop 10 xG totaux saison:")
    for p in top_xg:
        print(f"  {p['name']:30s} xG={p['xg_total']:.2f} en {p['matches_played']} matchs "
              f"(xG/90={p['xg_per_90']:.3f}, buts={p['goals_total']:.0f})")

    top_xa = sorted(pool.values(), key=lambda p: p.get("xa_total", 0), reverse=True)[:10]
    print("\nTop 10 xA totaux saison:")
    for p in top_xa:
        print(f"  {p['name']:30s} xA={p['xa_total']:.2f} en {p['matches_played']} matchs "
              f"(xA/90={p['xa_per_90']:.3f}, passes_dec={p['assists_total']:.0f})")
