"""
T001 — Backtest RÉALISTE Bundesliga 2025/26 (sans data leakage).

Différences vs 4_backtest.py:
  - xG team = PRÉDITS depuis odds (pas réels)
  - Minutes = ATTENDUES (78' starter / 25' sub) pas réelles
  - Inclut TOUT joueur du squad probable, pas juste ceux ayant joué
    (un "starter prévu" qui finalement n'a pas joué = goals=0)

Métriques: Brier / LogLoss / AUC + calibration + ROI simulé.
Baselines: uniform (par joueur du squad), global_rate.
"""
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))
from importlib import import_module
_m = import_module("3_model")
aggregate_player_pool = _m.aggregate_player_pool
shrunk_per90 = _m.shrunk_per90
parse_event_date = _m.parse_event_date
LP_XG = _m.LEAGUE_PRIOR_XG90_OUTFIELD
LP_XA = _m.LEAGUE_PRIOR_XA90_OUTFIELD

EPS = 1e-9
EPS_PROB = 1e-6


def _safe(x, d=0.0):
    if x is None: return d
    try: return float(x)
    except (TypeError, ValueError): return d


def predict_realistic(realistic_event, pool, actual_player_results):
    """
    Pour un event, prédit p_scorer/p_assist pour TOUT joueur du squad probable.
    actual_player_results: dict[player_id] -> {goals, assists, minutes_actual}
    """
    xg_h = realistic_event["xg_home_predicted"]
    xg_a = realistic_event["xg_away_predicted"]
    rows = []

    for side, squad_key, team_xg in (("home", "squad_home", xg_h),
                                      ("away", "squad_away", xg_a)):
        squad = realistic_event[squad_key]
        if not squad or team_xg <= 0:
            continue
        # On exclut les "unused" (mins=0 dernier match) — comme un bookmaker
        # qui ne propose pas un joueur clairement absent. Mais on garde "starter"
        # et "sub" même s'ils ne joueront pas finalement.
        eligible = {pid: p for pid, p in squad.items() if p["status"] in ("starter", "sub")}
        if not eligible:
            continue

        # 1) xG/xA bruts par joueur
        raws_xg, raws_xa = {}, {}
        n_eligible = len(eligible)
        for pid_str, p in eligible.items():
            pid = int(pid_str)
            pdata = pool.get(pid)
            is_gk = p.get("is_gk", False)
            prior_xg = 0.0 if is_gk else LP_XG
            prior_xa = 0.0 if is_gk else LP_XA
            if pdata is None:
                xg_p90 = prior_xg
                xa_p90 = prior_xa
            else:
                xg_p90 = shrunk_per90(pdata, "xg_per_90", prior_xg)
                xa_p90 = shrunk_per90(pdata, "xa_per_90", prior_xa)
            mins_exp = p["minutes_expected"]
            raws_xg[pid] = xg_p90 * (mins_exp / 90.0)
            raws_xa[pid] = xa_p90 * (mins_exp / 90.0)

        # 2) Normalisation: somme xG eligibles = xG team prédit
        sum_xg = sum(raws_xg.values()) or EPS
        sum_xa = sum(raws_xa.values()) or EPS
        # Ratio assist/goal calibré empiriquement Bundesliga 25/26 = 0.707
        team_xa_target = team_xg * 0.707

        # 3) Baseline uniform: xG team / N éligibles
        bx = team_xg / n_eligible
        ba = team_xa_target / n_eligible
        p_scorer_unif = 1.0 - math.exp(-bx)
        p_assist_unif = 1.0 - math.exp(-ba)

        # 4) Pricing
        for pid_str, p in eligible.items():
            pid = int(pid_str)
            xg_cal = team_xg * (raws_xg[pid] / sum_xg)
            xa_cal = team_xa_target * (raws_xa[pid] / sum_xa)
            p_scorer = 1.0 - math.exp(-xg_cal)
            p_assist = 1.0 - math.exp(-xa_cal)

            actual = actual_player_results.get(pid, {"goals": 0, "assists": 0, "mins": 0})
            rows.append({
                "event_id": realistic_event["event_id"],
                "date": realistic_event["date"],
                "side": side,
                "player_id": pid,
                "name": p["name"],
                "is_gk": p.get("is_gk", False),
                "status_predicted": p["status"],
                "minutes_expected": p["minutes_expected"],
                "minutes_actual": actual["mins"],
                "team_xg": team_xg,
                "n_pool": (pool.get(pid) or {}).get("matches_played", 0),
                "xg_predicted": xg_cal,
                "xa_predicted": xa_cal,
                "p_scorer_model": p_scorer,
                "p_assist_model": p_assist,
                "p_scorer_uniform": p_scorer_unif,
                "p_assist_uniform": p_assist_unif,
                "scored": 1 if actual["goals"] > 0 else 0,
                "assisted": 1 if actual["assists"] > 0 else 0,
            })
    return rows


def get_actual_results_for_event(stats_event):
    """Construit dict[player_id] -> goals/assists/minutes pour un event."""
    out = {}
    for s in stats_event.get("stats", []):
        p = s.get("player")
        if isinstance(p, dict):
            pid = p.get("id")
        else:
            pid = p
        if pid is None: continue
        out[pid] = {
            "goals": _safe(s.get("goals")),
            "assists": _safe(s.get("goal_assist")),
            "mins": _safe(s.get("minutes_played")),
        }
    return out


def metric_brier(rows, pkey, ykey):
    if not rows: return None
    return sum((r[ykey] - r[pkey]) ** 2 for r in rows) / len(rows)


def metric_logloss(rows, pkey, ykey):
    if not rows: return None
    s = 0.0
    for r in rows:
        p = max(min(r[pkey], 1 - EPS_PROB), EPS_PROB)
        s += -(r[ykey] * math.log(p) + (1 - r[ykey]) * math.log(1 - p))
    return s / len(rows)


def metric_auc(rows, pkey, ykey):
    pos = [r[pkey] for r in rows if r[ykey] == 1]
    neg = [r[pkey] for r in rows if r[ykey] == 0]
    if not pos or not neg: return None
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n: wins += 1
            elif p == n: ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def calibration(rows, pkey, ykey, n_bins=10):
    bins = [[] for _ in range(n_bins)]
    for r in rows:
        b = min(int(r[pkey] * n_bins), n_bins - 1)
        bins[b].append(r[ykey])
    out = []
    for i, b in enumerate(bins):
        if not b: continue
        out.append({"bin": f"[{i*10}-{(i+1)*10}%)", "n": len(b),
                    "predicted": (i + 0.5) / n_bins, "observed": sum(b) / len(b)})
    return out


def main():
    print("=" * 70)
    print("T001 — Backtest RÉALISTE Bundesliga 2025/26")
    print("=" * 70)
    print("(xG prédits depuis odds + minutes attendues + non-participants inclus)")

    matches = json.loads((DATA / "bundesliga_matches.json").read_text())["events"]
    stats = json.loads((DATA / "bundesliga_player_stats.json").read_text())["by_event"]
    realistic = json.loads((DATA / "realistic_inputs.json").read_text())
    print(f"\nEvents avec inputs réalistes: {len(realistic)}")

    # Tri chronologique
    sorted_evs = sorted(realistic.values(), key=lambda x: x["date"])

    # Cache pool par date
    pool_cache = {}
    all_rows = []
    for i, ev in enumerate(sorted_evs):
        d_key = ev["date"]
        if d_key not in pool_cache:
            cutoff = datetime.fromisoformat(d_key).date()
            # parse_event_date attend datetime, pas date
            cutoff_dt = datetime.combine(cutoff, datetime.min.time())
            from datetime import timezone
            cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)
            pool_cache[d_key] = aggregate_player_pool(stats, matches, until_date=cutoff_dt)
        pool = pool_cache[d_key]

        actual = get_actual_results_for_event(stats.get(str(ev["event_id"]), {}))
        rows = predict_realistic(ev, pool, actual)
        all_rows.extend(rows)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(sorted_evs)} events ({len(all_rows)} prédictions)")

    print(f"\nTotal prédictions: {len(all_rows)}")

    # Filtre cold-start
    eval_rows = [r for r in all_rows if r["n_pool"] >= 3]
    print(f"Après filtre n_pool>=3: {len(eval_rows)}")

    n_scored = sum(r["scored"] for r in eval_rows)
    n_assist = sum(r["assisted"] for r in eval_rows)
    n_played = sum(1 for r in eval_rows if r["minutes_actual"] > 0)
    n_unused = sum(1 for r in eval_rows if r["minutes_actual"] == 0)
    print(f"\nBase rates:")
    print(f"  Joueurs ayant joué: {n_played}/{len(eval_rows)} ({n_played/len(eval_rows):.1%})")
    print(f"  Joueurs prévus mais finalement non joués: {n_unused}/{len(eval_rows)} ({n_unused/len(eval_rows):.1%})")
    print(f"  Buteurs: {n_scored}/{len(eval_rows)} = {n_scored/len(eval_rows):.3%}")
    print(f"  Passeurs: {n_assist}/{len(eval_rows)} = {n_assist/len(eval_rows):.3%}")

    base_s = n_scored / len(eval_rows)
    base_a = n_assist / len(eval_rows)
    for r in eval_rows:
        r["p_scorer_global"] = base_s
        r["p_assist_global"] = base_a

    print("\n" + "=" * 70)
    print("RÉSULTATS — ANYTIME GOALSCORER (réaliste, no leak)")
    print("=" * 70)
    print(f"{'Métrique':18s} {'Modèle':>12s} {'Uniform':>12s} {'GlobalRate':>12s}")
    for name, fn in (("Brier (↓)", metric_brier), ("LogLoss (↓)", metric_logloss), ("AUC (↑)", metric_auc)):
        m = fn(eval_rows, "p_scorer_model", "scored")
        u = fn(eval_rows, "p_scorer_uniform", "scored")
        g = fn(eval_rows, "p_scorer_global", "scored")
        fmt = lambda x: f"{x:.4f}" if x is not None else "  N/A "
        print(f"  {name:16s} {fmt(m):>12s} {fmt(u):>12s} {fmt(g):>12s}")

    print("\n" + "=" * 70)
    print("RÉSULTATS — ANYTIME ASSIST (réaliste, no leak)")
    print("=" * 70)
    print(f"{'Métrique':18s} {'Modèle':>12s} {'Uniform':>12s} {'GlobalRate':>12s}")
    for name, fn in (("Brier (↓)", metric_brier), ("LogLoss (↓)", metric_logloss), ("AUC (↑)", metric_auc)):
        m = fn(eval_rows, "p_assist_model", "assisted")
        u = fn(eval_rows, "p_assist_uniform", "assisted")
        g = fn(eval_rows, "p_assist_global", "assisted")
        fmt = lambda x: f"{x:.4f}" if x is not None else "  N/A "
        print(f"  {name:16s} {fmt(m):>12s} {fmt(u):>12s} {fmt(g):>12s}")

    print("\n--- Calibration ANYTIME SCORER (Modèle) ---")
    for r in calibration(eval_rows, "p_scorer_model", "scored"):
        print(f"  {r['bin']:13s} n={r['n']:>5d}  pred={r['predicted']:>5.1%}  obs={r['observed']:>6.1%}")

    print("\n--- Calibration ANYTIME ASSIST (Modèle) ---")
    for r in calibration(eval_rows, "p_assist_model", "assisted"):
        print(f"  {r['bin']:13s} n={r['n']:>5d}  pred={r['predicted']:>5.1%}  obs={r['observed']:>6.1%}")

    # ROI simulé (vs odds bookmaker = fair_odd × 1.05 marge)
    print("\n=== ROI SIMULÉ ANYTIME SCORER (avec marge bookmaker 8% standard) ===")
    print(f"{'Seuil p':>10s} {'n picks':>10s} {'win':>10s} {'odd_book':>10s} {'ROI':>10s}")
    for thr in [0.10, 0.15, 0.20, 0.25, 0.30, 0.40]:
        picks = [r for r in eval_rows if r["p_scorer_model"] > thr]
        if not picks: continue
        wins = sum(r["scored"] for r in picks)
        # Simulation: odd_bookmaker = 1 / (p_scorer_model * 1.08) (vig 8%)
        # Profit = wins * mean(odd_book) - len(picks)
        avg_odd = sum(1.0 / (r["p_scorer_model"] * 1.08) for r in picks) / len(picks)
        roi = (sum(1.0 / (r["p_scorer_model"] * 1.08) if r["scored"] else 0 for r in picks) - len(picks)) / len(picks)
        print(f"  p>{thr:.0%}{'':>4s} {len(picks):>10d} {wins:>10d} {avg_odd:>10.2f} {roi:>+9.1%}")

    print("\n=== ROI SIMULÉ ANYTIME ASSIST (avec marge bookmaker 8%) ===")
    print(f"{'Seuil p':>10s} {'n picks':>10s} {'win':>10s} {'odd_book':>10s} {'ROI':>10s}")
    for thr in [0.10, 0.15, 0.20, 0.25, 0.30]:
        picks = [r for r in eval_rows if r["p_assist_model"] > thr]
        if not picks: continue
        wins = sum(r["assisted"] for r in picks)
        avg_odd = sum(1.0 / (r["p_assist_model"] * 1.08) for r in picks) / len(picks)
        roi = (sum(1.0 / (r["p_assist_model"] * 1.08) if r["assisted"] else 0 for r in picks) - len(picks)) / len(picks)
        print(f"  p>{thr:.0%}{'':>4s} {len(picks):>10d} {wins:>10d} {avg_odd:>10.2f} {roi:>+9.1%}")

    out = DATA / "backtest_realistic_results.json"
    out.write_text(json.dumps(all_rows, ensure_ascii=False))
    print(f"\n✅ Sauvegardé: {out}")


if __name__ == "__main__":
    main()
