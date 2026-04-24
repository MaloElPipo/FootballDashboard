"""
T001 — Construit les inputs PRÉ-MATCH pour le backtest réaliste:
  - xG team prédits depuis odds 1X2 + Over/Under 2.5 Pinnacle (via g2_engine.lambdas_buchdahl)
  - Minutes attendues par joueur basées sur son match précédent
  - Squad probable : joueurs ayant joué au moins 1 des 5 derniers matchs

Sources:
  - data/footballdata_bundesliga_2526.csv : odds Pinnacle (PSH/PSD/PSA, P>2.5/P<2.5)
  - data/bundesliga_matches.json : nos events BSD
  - data/bundesliga_player_stats.json : stats par match

Output: data/realistic_inputs.json
"""
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import math
from g2_engine import remove_margin_proportional, remove_margin_2way  # noqa: E402

# Approche analytique rapide (instantanée vs ~1.4s pour Nelder-Mead):
#   1. Total xG résolu par bissection sur Poisson U2.5
#   2. Split home/away via supremacy depuis 1X2 (heuristique calibrée)
def lambdas_buchdahl(odds_h, odds_d, odds_a, ou25_under=None, ou25_over=None):
    fair_h, fair_d, fair_a = remove_margin_proportional(odds_h, odds_d, odds_a)
    ph, _pd, pa = 1.0 / fair_h, 1.0 / fair_d, 1.0 / fair_a

    # 1) Total xG via Poisson(U2.5) = e^-λ * (1+λ+λ²/2)
    has_ou = ou25_under and ou25_over and ou25_under > 1.0 and ou25_over > 1.0
    if has_ou:
        fu, fo = remove_margin_2way(ou25_under, ou25_over)
        p_u25 = 1.0 / fu
        lo_t, hi_t = 0.5, 7.0
        for _ in range(40):
            mid = (lo_t + hi_t) / 2
            p_calc = math.exp(-mid) * (1 + mid + mid * mid / 2)
            if p_calc > p_u25:
                lo_t = mid
            else:
                hi_t = mid
        total_xg = (lo_t + hi_t) / 2
        method = "bisect+supremacy"
    else:
        # Heuristique sans O/U: défaut Bundesliga ~3.0 buts moyens
        total_xg = 3.0
        method = "default+supremacy"

    # 2) Split home/away via supremacy (ph - pa)
    # Calibré empiriquement: ratio home ≈ 0.5 + supremacy * 0.55
    supremacy = ph - pa
    home_share = max(0.20, min(0.80, 0.5 + supremacy * 0.55))
    lt = total_xg * home_share
    lo_v = total_xg * (1 - home_share)
    return lt, lo_v, method


# Mapping noms équipes Football-Data → noms BSD
TEAM_NAME_MAP = {
    "Bayern Munich": "FC Bayern München",
    "Dortmund": "Borussia Dortmund",
    "RB Leipzig": "RB Leipzig",
    "Leverkusen": "Bayer 04 Leverkusen",
    "Ein Frankfurt": "Eintracht Frankfurt",
    "Stuttgart": "VfB Stuttgart",
    "Wolfsburg": "VfL Wolfsburg",
    "Freiburg": "SC Freiburg",
    "Hoffenheim": "TSG Hoffenheim",
    "Werder Bremen": "SV Werder Bremen",
    "M'gladbach": "Borussia M'gladbach",
    "Mainz": "1. FSV Mainz 05",
    "Augsburg": "FC Augsburg",
    "Heidenheim": "1. FC Heidenheim",
    "St Pauli": "FC St. Pauli",
    "Union Berlin": "1. FC Union Berlin",
    "FC Koln": "1. FC Köln",
    "Hamburg": "Hamburger SV",
}


def load_footballdata_odds():
    """Parse CSV → dict[(date, home_bsd_name, away_bsd_name)] -> odds dict."""
    odds_by_match = {}
    csv_path = DATA / "footballdata_bundesliga_2526.csv"
    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                # Date format: DD/MM/YYYY
                date = datetime.strptime(row["Date"], "%d/%m/%Y").date()
            except ValueError:
                continue
            home_fd = row["HomeTeam"].strip()
            away_fd = row["AwayTeam"].strip()
            home_bsd = TEAM_NAME_MAP.get(home_fd, home_fd)
            away_bsd = TEAM_NAME_MAP.get(away_fd, away_fd)
            def _f(k):
                v = row.get(k)
                if v is None or not str(v).strip():
                    return None
                try: return float(v)
                except ValueError: return None
            # Pinnacle si dispo (closing référence) sinon Bet365 sinon moyenne
            psh = _f("PSH") or _f("B365H") or _f("AvgH")
            psd = _f("PSD") or _f("B365D") or _f("AvgD")
            psa = _f("PSA") or _f("B365A") or _f("AvgA")
            p_over25 = _f("P>2.5") or _f("B365>2.5") or _f("Avg>2.5")
            p_under25 = _f("P<2.5") or _f("B365<2.5") or _f("Avg<2.5")
            odds = {
                "psh": psh, "psd": psd, "psa": psa,
                "p_over25": p_over25, "p_under25": p_under25,
                "source": "pinnacle" if _f("PSH") else ("b365" if _f("B365H") else "avg"),
            }
            odds_by_match[(date, home_bsd, away_bsd)] = odds
    return odds_by_match


def parse_iso_date(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def main():
    print("=" * 70)
    print("T001 — Construction inputs réalistes pré-match")
    print("=" * 70)

    matches = json.loads((DATA / "bundesliga_matches.json").read_text())["events"]
    stats_by_event = json.loads((DATA / "bundesliga_player_stats.json").read_text())["by_event"]

    print("\n[1] Chargement odds Football-Data.co.uk...")
    fd_odds = load_footballdata_odds()
    print(f"  {len(fd_odds)} matchs avec odds")

    # [2] Tri matchs chronologique
    sorted_events = []
    for eid, ev in matches.items():
        d = parse_iso_date(ev.get("event_date"))
        if d is None: continue
        sorted_events.append((d, int(eid), ev))
    sorted_events.sort()

    # [3] Match BSD events ↔ FD odds
    print("\n[2] Matching events BSD ↔ odds Football-Data...")
    matched = 0
    unmatched = []
    for d, eid, ev in sorted_events:
        key = (d, ev.get("home_team"), ev.get("away_team"))
        if key in fd_odds:
            matched += 1
        else:
            unmatched.append((d, ev.get("home_team"), ev.get("away_team")))
    print(f"  Matched: {matched}/{len(sorted_events)}")
    if unmatched[:5]:
        print("  Échantillon non matchés (les 5 premiers):")
        for u in unmatched[:5]:
            print(f"    {u[0]} {u[1]} vs {u[2]}")

    # [4] Calcul xG team prédits + minutes attendues + squad probable
    print("\n[3] Calcul xG team prédits + minutes attendues...")

    # Index: pour chaque équipe, ses matchs ordonnés (date, eid)
    team_matches = defaultdict(list)  # team_name → [(date, eid)]
    for d, eid, ev in sorted_events:
        for tname in (ev.get("home_team"), ev.get("away_team")):
            if tname:
                team_matches[tname].append((d, eid))
    for tname in team_matches:
        team_matches[tname].sort()

    # Pré-calcul: set des player_ids identifiés comme gardien (saves > 0
    # quelque part dans la saison, ou position = "G"/"GK"). Le check position
    # seul échoue à 100% sur la donnée BSD (testé empiriquement).
    gk_ids = set()
    for ev_stats in stats_by_event.values():
        for s in ev_stats.get("stats", []):
            p = s.get("player")
            pid = p.get("id") if isinstance(p, dict) else p
            if pid is None:
                continue
            try:
                saves = float(s.get("saves") or 0)
            except (TypeError, ValueError):
                saves = 0
            pos = (s.get("position") or "").upper() if not isinstance(s.get("position"), dict) else ""
            if saves > 0 or pos in ("G", "GK"):
                gk_ids.add(pid)
    print(f"  Gardiens identifiés: {len(gk_ids)}")

    # Helper: extract player_id, name, team, minutes from a stat row
    def player_info(s, home_name, away_name):
        p = s.get("player")
        if isinstance(p, dict):
            pid, pname = p.get("id"), p.get("name")
            team_name = p.get("team")
        else:
            return None
        if pid is None: return None
        return {
            "player_id": pid, "name": pname, "team": team_name,
            "minutes": float(s.get("minutes_played") or 0),
            "is_gk": pid in gk_ids,
        }

    realistic = {}
    n_with_xg = 0
    for d, eid, ev in sorted_events:
        key = (d, ev.get("home_team"), ev.get("away_team"))
        odds = fd_odds.get(key)
        if not odds or odds["psh"] is None or odds["psd"] is None or odds["psa"] is None:
            continue

        # xG team prédits via g2_engine (Buchdahl + OU 2.5 si dispo)
        try:
            lt, lo, method = lambdas_buchdahl(
                odds["psh"], odds["psd"], odds["psa"],
                ou25_under=odds.get("p_under25"),
                ou25_over=odds.get("p_over25"),
            )
        except Exception as e:
            continue
        n_with_xg += 1

        # Squad probable + minutes attendues, pour chaque équipe
        squad_predictions = {}
        for side, tname in (("home", ev.get("home_team")), ("away", ev.get("away_team"))):
            # Récupérer 5 derniers matchs de l'équipe AVANT d
            past = [(pd, peid) for pd, peid in team_matches[tname] if pd < d][-5:]
            # Tous joueurs ayant joué au moins 1 match parmi ces 5 → squad probable
            squad = {}  # pid → {name, last_minutes, last_was_starter, is_gk, n_matches}
            for pd, peid in past:
                ev_stats = stats_by_event.get(str(peid), {}).get("stats", [])
                for s in ev_stats:
                    info = player_info(s, ev.get("home_team"), ev.get("away_team"))
                    if info is None or info["team"] != tname: continue
                    if info["minutes"] <= 0: continue  # n'a pas joué
                    pid = info["player_id"]
                    if pid not in squad:
                        squad[pid] = {
                            "name": info["name"], "is_gk": info["is_gk"],
                            "last_minutes": info["minutes"],
                            "last_match_date": pd.isoformat(),
                            "n_appearances_last5": 1,
                        }
                    else:
                        # Mise à jour avec match plus récent
                        if pd.isoformat() > squad[pid]["last_match_date"]:
                            squad[pid]["last_minutes"] = info["minutes"]
                            squad[pid]["last_match_date"] = pd.isoformat()
                        squad[pid]["n_appearances_last5"] += 1

            # Estimation minutes attendues
            for pid, p in squad.items():
                if p["last_minutes"] >= 60:
                    p["minutes_expected"] = 78.0
                    p["status"] = "starter"
                elif p["last_minutes"] > 0:
                    p["minutes_expected"] = 25.0
                    p["status"] = "sub"
                else:
                    p["minutes_expected"] = 0.0
                    p["status"] = "unused"
            squad_predictions[side] = squad

        realistic[str(eid)] = {
            "event_id": eid,
            "date": d.isoformat(),
            "home_team": ev.get("home_team"),
            "away_team": ev.get("away_team"),
            "home_team_id": (ev.get("home_team_obj") or {}).get("id"),
            "away_team_id": (ev.get("away_team_obj") or {}).get("id"),
            "odds": odds,
            "xg_home_predicted": round(lt, 4),
            "xg_away_predicted": round(lo, 4),
            "xg_calc_method": method,
            "actual_home_xg": ev.get("actual_home_xg"),
            "actual_away_xg": ev.get("actual_away_xg"),
            "squad_home": squad_predictions["home"],
            "squad_away": squad_predictions["away"],
        }

    print(f"  Matchs avec xG prédits + squads: {n_with_xg}")

    out = DATA / "realistic_inputs.json"
    out.write_text(json.dumps(realistic, ensure_ascii=False, indent=2))
    print(f"\n✅ Sauvegardé: {out} ({out.stat().st_size/1024/1024:.1f} MB)")

    # Sanity check
    sample_eid = next(iter(realistic))
    s = realistic[sample_eid]
    print(f"\n--- Sanity check (event {sample_eid}) ---")
    print(f"  Match: {s['home_team']} vs {s['away_team']} ({s['date']})")
    print(f"  Odds Pinnacle 1X2: {s['odds']['psh']}/{s['odds']['psd']}/{s['odds']['psa']}")
    print(f"  Odds Pinnacle O/U 2.5: {s['odds']['p_over25']}/{s['odds']['p_under25']}")
    print(f"  xG prédits: {s['xg_home_predicted']} / {s['xg_away_predicted']}")
    print(f"  xG réels:   {s['actual_home_xg']} / {s['actual_away_xg']}")
    print(f"  Squad home: {len(s['squad_home'])} joueurs (starters={sum(1 for p in s['squad_home'].values() if p['status']=='starter')})")
    print(f"  Squad away: {len(s['squad_away'])} joueurs (starters={sum(1 for p in s['squad_away'].values() if p['status']=='starter')})")

    # Mesurer écart prédit vs réel pour les xG team
    diffs_h = []
    diffs_a = []
    for ev in realistic.values():
        if ev.get("actual_home_xg") is not None:
            diffs_h.append(ev["xg_home_predicted"] - ev["actual_home_xg"])
        if ev.get("actual_away_xg") is not None:
            diffs_a.append(ev["xg_away_predicted"] - ev["actual_away_xg"])
    if diffs_h:
        import statistics
        mean_err_h = statistics.mean(diffs_h)
        mae_h = statistics.mean(abs(d) for d in diffs_h)
        rmse_h = (sum(d*d for d in diffs_h)/len(diffs_h)) ** 0.5
        print(f"\n📊 Qualité xG team prédits (depuis odds) vs xG réels:")
        print(f"   HOME: bias={mean_err_h:+.3f}, MAE={mae_h:.3f}, RMSE={rmse_h:.3f}")
        mean_err_a = statistics.mean(diffs_a)
        mae_a = statistics.mean(abs(d) for d in diffs_a)
        rmse_a = (sum(d*d for d in diffs_a)/len(diffs_a)) ** 0.5
        print(f"   AWAY: bias={mean_err_a:+.3f}, MAE={mae_a:.3f}, RMSE={rmse_a:.3f}")


if __name__ == "__main__":
    main()
