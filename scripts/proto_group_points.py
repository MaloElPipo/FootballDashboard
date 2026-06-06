"""Prototype (read-only) : points attendus en poule CDM 2026 sous 3 modeles.

Diagnostic : le calcul actuel des points tire le resultat via deux Poisson
INDEPENDANTS sur des lambdas Elo (simulate_match_goals), ce qui sur-produit les
nuls et ecrase les favoris -> presque aucune equipe ne depasse 6 pts attendus.

Ce script compare, sans toucher la prod, les points attendus (E[pts] = lineaire
dans les probas W/N/D, pas besoin de Monte-Carlo) sous :
  - ACTUEL : Poisson-Elo independant (= modele de points en prod aujourd'hui).
  - OPTION A : sigmoid_v8_1x2 calibree (coherente avec le 1X2 affiche).
  - OPTION B : 1X2 marche Pinnacle de-vigge quand le match est couvert,
               fallback OPTION A sinon. Inclut implicitement l'avantage hote.

Sortie : console (tableau trie) + live/data/proto_group_points.json.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "artifacts" / "football-dashboard"))

import wc_simulator as ws  # noqa: E402
from elo_engine import compute_all_nations_elo  # noqa: E402
from wc_simulator import WC2026_GROUPS, GROUP_MATCHES  # noqa: E402
from elo_vs_market_3way import (  # noqa: E402
    fetch_pinnacle, buchdahl_demargin, PIN_TO_CODE,
)

OUT_JSON = REPO / "live" / "data" / "proto_group_points.json"


def wdl_poisson_elo(elo_h: float, elo_a: float, mx: int = 12) -> tuple[float, float, float]:
    """W/N/D analytiques du modele ACTUEL : 2 Poisson independants (lambdas Elo)."""
    lh, la = ws.derive_lambdas_from_elo(elo_h, elo_a)
    eh, ea = math.exp(-lh), math.exp(-la)
    ph = [eh * lh ** i / math.factorial(i) for i in range(mx)]
    pa = [ea * la ** j / math.factorial(j) for j in range(mx)]
    pw = pd = pl = 0.0
    for i in range(mx):
        for j in range(mx):
            p = ph[i] * pa[j]
            if i > j:
                pw += p
            elif i == j:
                pd += p
            else:
                pl += p
    # Renormalisation : la masse tronquee (~0.18% au-dela de mx) ne doit pas
    # etre attribuee implicitement aux victoires exterieures (biais away).
    tot = pw + pd + pl
    return pw / tot, pd / tot, pl / tot


def wdl_sigmoid(elo_h: float, elo_a: float) -> tuple[float, float, float]:
    """W/N/D OPTION A : sigmoid_v8_1x2 calibree (phase poule)."""
    delta = elo_h - elo_a
    elo_avg = (elo_h + elo_a) / 2.0
    return ws.sigmoid_v8_1x2(delta, elo_avg=elo_avg, phase="G")


def build_market_map() -> tuple[dict, str, int]:
    """dict[(code_h, code_a)] -> (p_h, p_d, p_a) de-vigge, oriente comme Pinnacle."""
    raw, src = fetch_pinnacle()
    mkt = {}
    for m in raw:
        ch = PIN_TO_CODE.get(m["home"])
        ca = PIN_TO_CODE.get(m["away"])
        if not ch or not ca:
            continue
        mh, md, ma = buchdahl_demargin(m["pin_h"], m["pin_d"], m["pin_a"])
        mkt[(ch, ca)] = (mh, md, ma)
    return mkt, src, len(raw)


def wdl_market(h: str, a: str, elo_h: float, elo_a: float, mkt: dict):
    """W/N/D OPTION B : marche si dispo (toute orientation), sinon fallback A."""
    if (h, a) in mkt:
        return mkt[(h, a)], "market"
    if (a, h) in mkt:
        ph, pd, pa = mkt[(a, h)]  # oriente (a=home_pin) -> on inverse
        return (pa, pd, ph), "market"
    return wdl_sigmoid(elo_h, elo_a), "fallback_A"


def main() -> int:
    print("Resolution Elo prod…")
    elo = {r["code"]: r["elo"] for r in compute_all_nations_elo()}
    print(f"  {len(elo)} nations")

    print("Fetch marche Pinnacle…")
    mkt, src, n_raw = build_market_map()
    print(f"  source={src}  matchs marche={len(mkt)}")

    teams_xpts = {}  # code -> {cur, A, B}
    cov_market = cov_total = 0
    for grp, teams in WC2026_GROUPS.items():
        for c in teams:
            teams_xpts[c] = {"grp": grp, "elo": elo.get(c, 1500),
                             "cur": 0.0, "A": 0.0, "B": 0.0}
        for _md, pairings in GROUP_MATCHES.items():
            for ih, ia in pairings:
                h, a = teams[ih], teams[ia]
                eh, ea = elo.get(h, 1500), elo.get(a, 1500)
                # ACTUEL
                pw, pd, pl = wdl_poisson_elo(eh, ea)
                teams_xpts[h]["cur"] += 3 * pw + pd
                teams_xpts[a]["cur"] += 3 * pl + pd
                # OPTION A
                aw, ad, al = wdl_sigmoid(eh, ea)
                teams_xpts[h]["A"] += 3 * aw + ad
                teams_xpts[a]["A"] += 3 * al + ad
                # OPTION B
                (bw, bd, bl), origin = wdl_market(h, a, eh, ea, mkt)
                teams_xpts[h]["B"] += 3 * bw + bd
                teams_xpts[a]["B"] += 3 * bl + bd
                cov_total += 1
                if origin == "market":
                    cov_market += 1

    rows = sorted(teams_xpts.items(), key=lambda kv: -kv[1]["B"])
    print(f"\nCouverture marche OPTION B : {cov_market}/{cov_total} matchs de poule\n")
    print(f"{'NAT':<4}{'grp':>4}{'Elo':>6}{'ACTUEL':>9}{'OPT-A':>9}{'OPT-B':>9}{'B-act':>8}")
    print("-" * 49)
    for c, d in rows:
        print(f"{c:<4}{d['grp']:>4}{d['elo']:>6.0f}"
              f"{d['cur']:>9.2f}{d['A']:>9.2f}{d['B']:>9.2f}{d['B']-d['cur']:>+8.2f}")

    def n_over(key):
        return sum(1 for _, d in rows if d[key] > 6)
    print(f"\nEquipes > 6 pts attendus :  ACTUEL={n_over('cur')}  "
          f"OPT-A={n_over('A')}  OPT-B={n_over('B')}  (sur {len(rows)})")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "market_source": src, "market_coverage": [cov_market, cov_total],
        "n_over_6": {"current": n_over("cur"), "A": n_over("A"), "B": n_over("B")},
        "teams": [{"code": c, **d} for c, d in rows],
    }, indent=2, ensure_ascii=False))
    print(f"\n-> {OUT_JSON.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
