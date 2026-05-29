"""Prototype (read-only) : impact de l'Option B sur les P(qualif) R32 CDM 2026.

Compare, par Monte-Carlo de la phase de poules, deux modeles de RESULTAT :
  - ACTUEL : issue W/N/D tiree de 2 Poisson Elo independants (= prod).
  - OPTION B : issue tiree du 1X2 marche Pinnacle de-vigge quand le match est
               couvert (69/72), fallback sigmoid_v8_1x2 calibree sinon.

Le goal-average de depart (gf/ga) utilise les MEMES lambdas Elo dans les deux
modeles -> on isole proprement l'effet du modele de resultat sur la qualif.
La logique de classement (_rank_group, FIFA art.13) et de selection des 8
meilleurs 3emes (_pick_best_thirds) est importee telle quelle depuis la prod.

Qualif R32 = top 2 de poule OU faire partie des 8 meilleurs 3emes.
Sortie : console + live/data/proto_qualif_optionB.json. Prod NON modifiee.
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "artifacts" / "football-dashboard"))

import wc_simulator as ws  # noqa: E402
from elo_engine import compute_all_nations_elo  # noqa: E402
from wc_simulator import (  # noqa: E402
    WC2026_GROUPS, GROUP_MATCHES, _rank_group, _pick_best_thirds,
)
from proto_group_points import (  # noqa: E402
    wdl_poisson_elo, wdl_sigmoid, build_market_map, wdl_market,
)

OUT_JSON = REPO / "live" / "data" / "proto_qualif_optionB.json"
N_SIMS = 20000


def precompute(elo: dict, mkt: dict):
    """Pour chaque match de poule : probas W/N/D (actuel & B) + lambdas gf/ga."""
    pre = {}
    cov = 0
    for grp, teams in WC2026_GROUPS.items():
        for md, pairings in GROUP_MATCHES.items():
            for ih, ia in pairings:
                h, a = teams[ih], teams[ia]
                eh, ea = elo.get(h, 1500), elo.get(a, 1500)
                cur = wdl_poisson_elo(eh, ea)
                (b, origin) = wdl_market(h, a, eh, ea, mkt)
                xh, xa = ws.derive_lambdas_from_elo(eh, ea)
                pre[(grp, md, ih, ia)] = {
                    "h": h, "a": a, "cur": cur, "B": b, "xh": xh, "xa": xa,
                }
                if origin == "market":
                    cov += 1
    return pre, cov


def run_model(pre: dict, elo: dict, model: str, n: int, seed: int):
    """Monte-Carlo phase de poules ; renvoie comptes qualif/1er/2e/3e-qualifie."""
    rng = random.Random(seed)
    rnd = rng.random
    cnt = defaultdict(lambda: {"q": 0, "p1": 0, "p2": 0, "p3q": 0})

    for _ in range(n):
        group_results = {}
        for grp, teams in WC2026_GROUPS.items():
            standings = {c: {"pts": 0, "gf": 0.0, "ga": 0.0,
                             "w": 0, "d": 0, "l": 0} for c in teams}
            h2h = defaultdict(lambda: defaultdict(
                lambda: {"pts": 0, "gf": 0.0, "ga": 0.0}))
            for md, pairings in GROUP_MATCHES.items():
                for ih, ia in pairings:
                    m = pre[(grp, md, ih, ia)]
                    h, a, xh, xa = m["h"], m["a"], m["xh"], m["xa"]
                    pw, pd, _pl = m[model]
                    standings[h]["gf"] += xh
                    standings[h]["ga"] += xa
                    standings[a]["gf"] += xa
                    standings[a]["ga"] += xh
                    h2h[h][a]["gf"] += xh
                    h2h[h][a]["ga"] += xa
                    h2h[a][h]["gf"] += xa
                    h2h[a][h]["ga"] += xh
                    u = rnd()
                    if u < pw:
                        standings[h]["pts"] += 3
                        standings[h]["w"] += 1
                        standings[a]["l"] += 1
                        h2h[h][a]["pts"] += 3
                    elif u < pw + pd:
                        standings[h]["pts"] += 1
                        standings[a]["pts"] += 1
                        standings[h]["d"] += 1
                        standings[a]["d"] += 1
                        h2h[h][a]["pts"] += 1
                        h2h[a][h]["pts"] += 1
                    else:
                        standings[a]["pts"] += 3
                        standings[a]["w"] += 1
                        standings[h]["l"] += 1
                        h2h[a][h]["pts"] += 3
            group_results[grp] = _rank_group(standings, h2h_log=h2h, elo_map=elo)

        for grp, ranked in group_results.items():
            cnt[ranked[0][0]]["p1"] += 1
            cnt[ranked[0][0]]["q"] += 1
            cnt[ranked[1][0]]["p2"] += 1
            cnt[ranked[1][0]]["q"] += 1
        best = _pick_best_thirds(group_results, elo_map=elo, n=8)
        for _grp, code, _s in best:
            cnt[code]["p3q"] += 1
            cnt[code]["q"] += 1
    return cnt


def main() -> int:
    print("Resolution Elo prod…")
    elo = {r["code"]: r["elo"] for r in compute_all_nations_elo()}
    print("Fetch marche Pinnacle…")
    mkt, src, _ = build_market_map()
    pre, cov = precompute(elo, mkt)
    print(f"  source={src}  couverture marche={cov}/72 matchs\n")

    print(f"Monte-Carlo {N_SIMS} sims × 2 modeles…")
    cur = run_model(pre, elo, "cur", N_SIMS, seed=12345)
    optb = run_model(pre, elo, "B", N_SIMS, seed=12345)

    rows = []
    for grp, teams in WC2026_GROUPS.items():
        for c in teams:
            qc = cur[c]["q"] / N_SIMS
            qb = optb[c]["q"] / N_SIMS
            rows.append({
                "code": c, "grp": grp, "elo": elo.get(c, 1500),
                "q_cur": qc, "q_B": qb, "delta": qb - qc,
                "p1_B": optb[c]["p1"] / N_SIMS,
                "p2_B": optb[c]["p2"] / N_SIMS,
                "p3q_B": optb[c]["p3q"] / N_SIMS,
            })
    rows.sort(key=lambda r: -r["q_B"])

    print(f"\n{'NAT':<4}{'grp':>4}{'Elo':>6}{'Qual.ACT':>10}{'Qual.B':>9}{'delta':>8}"
          f"{'1er.B':>8}{'2e.B':>7}{'3eQ.B':>7}")
    print("-" * 63)
    for r in rows:
        print(f"{r['code']:<4}{r['grp']:>4}{r['elo']:>6.0f}"
              f"{r['q_cur']*100:>9.1f}%{r['q_B']*100:>8.1f}%{r['delta']*100:>+7.1f}%"
              f"{r['p1_B']*100:>7.1f}%{r['p2_B']*100:>6.1f}%{r['p3q_B']*100:>6.1f}%")

    movers = sorted(rows, key=lambda r: -abs(r["delta"]))[:12]
    print("\nPlus gros mouvements P(qualif) Option B vs actuel :")
    for r in movers:
        print(f"  {r['code']:<4} {r['delta']*100:+5.1f}%   "
              f"({r['q_cur']*100:.1f}% -> {r['q_B']*100:.1f}%)")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "n_sims": N_SIMS, "market_source": src, "market_coverage": [cov, 72],
        "teams": rows,
    }, indent=2, ensure_ascii=False))
    print(f"\n-> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
