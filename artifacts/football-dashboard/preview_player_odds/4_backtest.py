"""
Étape E — Backtest saison entière Bundesliga 2025/26.

Méthodologie:
  Pour chaque match j à la date d_j:
    1. Aggregate pool joueurs avec stats AVANT d_j (leave-one-out temporel)
    2. Pour chaque joueur ayant réellement joué (depuis player_stats[j]):
       - Calcule xG_attendu = xG/90_pool * (mins_réelles / 90) puis normalise pour
         que somme = xG_team_réel
       - Idem xA_attendu (target = 0.75 * xG_team)
       - p_scorer = 1 - exp(-xG_attendu)
       - p_assist = 1 - exp(-xA_attendu)
    3. Compare avec ce qui s'est passé (goals, goal_assist).

Métriques:
  - Brier score = mean((y - p)^2)         [plus bas = meilleur]
  - Log-loss = -mean(y*log(p) + (1-y)*log(1-p))
  - AUC (capacité à classer)
  - Calibration par bin (réalisé vs prédit)

Baselines comparés:
  - "global_rate"  : taux moyen ligue (constant pour tout joueur)
  - "uniform_team" : xG_team / 11 (tout joueur même proba)
  - "model"        : notre modèle (distribution avec stats individuelles + shrinkage)
"""
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from importlib import import_module
_m = import_module("3_model")
aggregate_player_pool = _m.aggregate_player_pool
shrunk_per90 = _m.shrunk_per90
parse_event_date = _m.parse_event_date
LEAGUE_PRIOR_XG90_OUTFIELD = _m.LEAGUE_PRIOR_XG90_OUTFIELD
LEAGUE_PRIOR_XA90_OUTFIELD = _m.LEAGUE_PRIOR_XA90_OUTFIELD
# Les anciennes constantes GK ont été remplacées par POSITION_PRIORS_XG90/XA90["GK"]
# (refonte R001). On ré-expose ici sous l'ancien nom pour préserver l'API du backtest.
LEAGUE_PRIOR_XG90_GK = _m.POSITION_PRIORS_XG90["GK"]
LEAGUE_PRIOR_XA90_GK = _m.POSITION_PRIORS_XA90["GK"]
_safe = _m._safe_float
is_goalkeeper = _m.is_goalkeeper

DATA = Path(__file__).parent / "data"
EPS = 1e-9
EPS_PROB = 1e-6  # pour log-loss


def get_player_id_team(s, home_name=None, home_id=None, away_name=None, away_id=None):
    p = s.get("player")
    if isinstance(p, dict):
        pid, name = p.get("id"), p.get("name")
        team_name = p.get("team")
    else:
        pid, name = p, s.get("player_name")
        team_name = None
    # team est un STRING dans player.team → matcher avec home/away du match
    if team_name == home_name:
        tid = home_id
    elif team_name == away_name:
        tid = away_id
    else:
        tid = None
    return pid, name, tid


def predict_match(event, event_stats, pool, home_team_id, away_team_id):
    """
    Pour un event donné, prédit p_scorer/p_assist pour chaque joueur ayant joué.
    Utilise xG_team réels du match comme contrainte de calibration.
    Returns: list of dicts ready for evaluation.
    """
    xg_home = _safe(event.get("actual_home_xg"), default=None)
    xg_away = _safe(event.get("actual_away_xg"), default=None)
    if xg_home is None or xg_away is None:
        return []

    home_name = event.get("home_team")
    away_name = event.get("away_team")

    # Joueurs ayant joué, regroupés par équipe
    by_team = defaultdict(list)
    for s in event_stats:
        pid, pname, tid = get_player_id_team(s, home_name, home_team_id, away_name, away_team_id)
        if pid is None or tid is None:
            continue
        mins = _safe(s.get("minutes_played"))
        if mins <= 0:
            continue
        by_team[tid].append({
            "pid": pid, "name": pname, "team_id": tid, "minutes": mins,
            "goals_actual": _safe(s.get("goals")),
            "assists_actual": _safe(s.get("goal_assist")),
            "is_gk_match": is_goalkeeper(s),
        })

    rows = []
    for tid, players in by_team.items():
        team_xg = xg_home if tid == home_team_id else (xg_away if tid == away_team_id else None)
        if team_xg is None or team_xg <= 0:
            continue
        team_xa_target = team_xg * 0.75

        # Calcul xG bruts par joueur
        raws_xg, raws_xa = {}, {}
        baselines_uniform_xg = team_xg / max(len(players), 1)
        for pl in players:
            pid = pl["pid"]
            pdata = pool.get(pid)
            is_gk = pl["is_gk_match"] or (pdata or {}).get("is_gk", False)
            prior_xg = LEAGUE_PRIOR_XG90_GK if is_gk else LEAGUE_PRIOR_XG90_OUTFIELD
            prior_xa = LEAGUE_PRIOR_XA90_GK if is_gk else LEAGUE_PRIOR_XA90_OUTFIELD

            if pdata is None:
                # Cold-start: priors purs
                xg_p90 = prior_xg
                xa_p90 = prior_xa
            else:
                xg_p90 = shrunk_per90(pdata, "xg_per_90", prior_xg)
                xa_p90 = shrunk_per90(pdata, "xa_per_90", prior_xa)
            raws_xg[pid] = xg_p90 * (pl["minutes"] / 90.0)
            raws_xa[pid] = xa_p90 * (pl["minutes"] / 90.0)
            pl["xg_p90_used"] = xg_p90
            pl["xa_p90_used"] = xa_p90

        sum_raw_xg = sum(raws_xg.values()) or EPS
        sum_raw_xa = sum(raws_xa.values()) or EPS

        for pl in players:
            pid = pl["pid"]
            xg_cal = team_xg * (raws_xg[pid] / sum_raw_xg)
            xa_cal = team_xa_target * (raws_xa[pid] / sum_raw_xa)
            p_scorer = 1.0 - math.exp(-xg_cal)
            p_assist = 1.0 - math.exp(-xa_cal)

            # Baselines
            p_scorer_uniform = 1.0 - math.exp(-baselines_uniform_xg)
            p_assist_uniform = 1.0 - math.exp(-(team_xa_target / max(len(players), 1)))

            rows.append({
                "event_id": event.get("id"),
                "event_date": event.get("event_date"),
                "team_id": pl["team_id"],
                "player_id": pid,
                "player_name": pl["name"],
                "is_gk": pl["is_gk_match"],
                "minutes": pl["minutes"],
                "team_xg": team_xg,
                "team_xa_target": team_xa_target,
                "xg_p90_used": pl["xg_p90_used"],
                "xa_p90_used": pl["xa_p90_used"],
                "xg_predicted": xg_cal,
                "xa_predicted": xa_cal,
                "p_scorer_model": p_scorer,
                "p_assist_model": p_assist,
                "p_scorer_uniform": p_scorer_uniform,
                "p_assist_uniform": p_assist_uniform,
                "scored_actual": 1 if pl["goals_actual"] > 0 else 0,
                "assisted_actual": 1 if pl["assists_actual"] > 0 else 0,
                "goals_actual": pl["goals_actual"],
                "assists_actual": pl["assists_actual"],
                "n_matches_in_pool": (pool.get(pid) or {}).get("matches_played", 0),
            })

    return rows


def metric_brier(rows, p_key, y_key):
    if not rows: return None
    return sum((r[y_key] - r[p_key]) ** 2 for r in rows) / len(rows)


def metric_logloss(rows, p_key, y_key):
    if not rows: return None
    s = 0.0
    for r in rows:
        p = max(min(r[p_key], 1 - EPS_PROB), EPS_PROB)
        y = r[y_key]
        s += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return s / len(rows)


def metric_auc(rows, p_key, y_key):
    """AUC ROC simple."""
    pos = [r[p_key] for r in rows if r[y_key] == 1]
    neg = [r[p_key] for r in rows if r[y_key] == 0]
    if not pos or not neg: return None
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n: wins += 1
            elif p == n: ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def calibration_table(rows, p_key, y_key, n_bins=10):
    bins = [[] for _ in range(n_bins)]
    for r in rows:
        b = min(int(r[p_key] * n_bins), n_bins - 1)
        bins[b].append(r[y_key])
    out = []
    for i, b in enumerate(bins):
        if not b: continue
        out.append({
            "bin": f"[{i*10}-{(i+1)*10}%)",
            "n": len(b),
            "predicted_avg": (i + 0.5) / n_bins,
            "observed_rate": sum(b) / len(b),
        })
    return out


def main():
    print("=" * 70)
    print("Étape E — Backtest Bundesliga 2025/26")
    print("=" * 70)

    matches = json.loads((DATA / "bundesliga_matches.json").read_text())["events"]
    stats_by_event = json.loads((DATA / "bundesliga_player_stats.json").read_text())["by_event"]
    print(f"\nMatchs: {len(matches)}, lignes stats: {sum(len(s.get('stats', [])) for s in stats_by_event.values())}")

    # Trier matchs chronologiquement
    sorted_events = []
    for eid, ev in matches.items():
        d = parse_event_date(ev)
        if d is None: continue
        sorted_events.append((d, eid, ev))
    sorted_events.sort()
    print(f"Range dates: {sorted_events[0][0].date()} → {sorted_events[-1][0].date()}")

    # Backtest avec re-aggregation par "fenêtre" pour limiter coût.
    # Stratégie: re-aggrege le pool toutes les N=10 matchs (≈ 1 journée)
    # → chaque match est prédit avec un pool ≤ 10 matchs trop récent (négligeable sur 270)
    #
    # Pour rigueur max: re-aggrege match par match (270 fois).
    # Ici on opte pour précision: par date unique (≈ ~30-40 dates).
    print("\nAggregations par date unique...")
    dates_uniq = sorted(set(d.date() for d, _, _ in sorted_events))
    print(f"  {len(dates_uniq)} dates uniques")

    all_rows = []
    pool_cache = {}  # cache pool par cutoff date
    for i, (d, eid, ev) in enumerate(sorted_events):
        cutoff = d
        cutoff_key = cutoff.date().isoformat()
        if cutoff_key not in pool_cache:
            pool_cache[cutoff_key] = aggregate_player_pool(stats_by_event, matches, until_date=cutoff)
        pool = pool_cache[cutoff_key]

        ev_stats = stats_by_event.get(str(eid), {}).get("stats", [])
        if not ev_stats: continue

        home_id = (ev.get("home_team_obj") or {}).get("id") if isinstance(ev.get("home_team_obj"), dict) else None
        away_id = (ev.get("away_team_obj") or {}).get("id") if isinstance(ev.get("away_team_obj"), dict) else None
        if home_id is None or away_id is None: continue

        rows = predict_match(ev, ev_stats, pool, home_id, away_id)
        all_rows.extend(rows)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(sorted_events)} matchs traités ({len(all_rows)} lignes)")

    print(f"\nTotal prédictions: {len(all_rows)}")

    # Filtrer cold-start (joueurs avec <3 matchs) pour éval principale
    rows_eval = [r for r in all_rows if r["n_matches_in_pool"] >= 3]
    print(f"Après filtre n_pool>=3: {len(rows_eval)} (sur {len(all_rows)})")

    # Stats ground truth
    n_scorers = sum(r["scored_actual"] for r in rows_eval)
    n_assisters = sum(r["assisted_actual"] for r in rows_eval)
    print(f"Base rates: scored {n_scorers}/{len(rows_eval)} = {n_scorers/len(rows_eval):.3%}, "
          f"assisted {n_assisters}/{len(rows_eval)} = {n_assisters/len(rows_eval):.3%}")

    # Baseline 'global_rate': constante = base_rate ligue
    base_scorer = n_scorers / len(rows_eval)
    base_assist = n_assisters / len(rows_eval)
    for r in rows_eval:
        r["p_scorer_global"] = base_scorer
        r["p_assist_global"] = base_assist

    print("\n" + "=" * 70)
    print("RÉSULTATS — ANYTIME GOALSCORER")
    print("=" * 70)
    print(f"{'Métrique':20s} {'Modèle':>12s} {'Uniform':>12s} {'GlobalRate':>12s}")
    for name, fn in (("Brier (↓)", metric_brier), ("LogLoss (↓)", metric_logloss), ("AUC (↑)", metric_auc)):
        m = fn(rows_eval, "p_scorer_model", "scored_actual")
        u = fn(rows_eval, "p_scorer_uniform", "scored_actual")
        g = fn(rows_eval, "p_scorer_global", "scored_actual")
        def fmt(x): return f"{x:.4f}" if x is not None else "  N/A "
        print(f"  {name:18s} {fmt(m):>12s} {fmt(u):>12s} {fmt(g):>12s}")

    print("\n" + "=" * 70)
    print("RÉSULTATS — ANYTIME ASSIST")
    print("=" * 70)
    print(f"{'Métrique':20s} {'Modèle':>12s} {'Uniform':>12s} {'GlobalRate':>12s}")
    for name, fn in (("Brier (↓)", metric_brier), ("LogLoss (↓)", metric_logloss), ("AUC (↑)", metric_auc)):
        m = fn(rows_eval, "p_assist_model", "assisted_actual")
        u = fn(rows_eval, "p_assist_uniform", "assisted_actual")
        g = fn(rows_eval, "p_assist_global", "assisted_actual")
        def fmt(x): return f"{x:.4f}" if x is not None else "  N/A "
        print(f"  {name:18s} {fmt(m):>12s} {fmt(u):>12s} {fmt(g):>12s}")

    # Calibration model (top marché)
    print("\n--- Calibration ANYTIME SCORER (Modèle) ---")
    print(f"{'Bin':15s} {'n':>5s} {'Prédit moy':>12s} {'Réalisé':>10s}")
    for r in calibration_table(rows_eval, "p_scorer_model", "scored_actual"):
        print(f"  {r['bin']:13s} {r['n']:>5d} {r['predicted_avg']:>11.1%} {r['observed_rate']:>10.1%}")

    print("\n--- Calibration ANYTIME ASSIST (Modèle) ---")
    print(f"{'Bin':15s} {'n':>5s} {'Prédit moy':>12s} {'Réalisé':>10s}")
    for r in calibration_table(rows_eval, "p_assist_model", "assisted_actual"):
        print(f"  {r['bin']:13s} {r['n']:>5d} {r['predicted_avg']:>11.1%} {r['observed_rate']:>10.1%}")

    # Sauvegarde rows
    out_path = DATA / "backtest_results.json"
    out_path.write_text(json.dumps(all_rows, ensure_ascii=False))
    print(f"\n✅ Détail sauvegardé: {out_path} ({len(all_rows)} lignes)")


if __name__ == "__main__":
    main()
