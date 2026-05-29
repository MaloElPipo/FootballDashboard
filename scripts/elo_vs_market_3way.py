"""Audit ELO vs marché Pinnacle sur le 1X2 (3-way) — CDM 2026.

Objectif (demande user) : maintenant que Pinnacle couvre ~100% des matchs de
poule, mesurer a quel point notre modele Elo (sigmoid_v8_1x2, identique a la
prod) est proche ou non du marche sur le 3-way, pour juger notre solidite sur
les paris long terme (outrights / qualifs).

Produit :
  1. Couverture live Pinnacle (TheOddsAPI, bookmaker=pinnacle).
  2. Comparaison par match : proba modele vs marche de-vigge (Buchdahl), TVD,
     accord sur le favori, plus gros ecarts (value potentielle).
  3. Calibration agregee : sur/sous-confiance du modele, biais nul.
  4. Classement Elo implicite marche (moindres carres sur les deltas inverses
     via la MEME sigmoid) vs notre Elo prod -> nations sur/sous-cotees.

Lecture seule : ne modifie aucun fichier prod. Sortie console + JSON + MD.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import requests

REPO = Path(__file__).resolve().parents[1]
DASH = REPO / "artifacts" / "football-dashboard"
sys.path.insert(0, str(DASH))

import wc_simulator as ws  # noqa: E402  (sigmoid_v8_1x2 = modele prod)

PROD_ELO = DASH / "pin_calibrated_elo.json"
OUT_JSON = REPO / "live" / "data" / "elo_vs_market_3way.json"
OUT_MD = REPO / "live" / "data" / "elo_vs_market_3way.md"

PIN_TO_CODE = {
    "France": "FRA", "Spain": "ESP", "Germany": "GER", "England": "ENG",
    "Portugal": "POR", "Netherlands": "NED", "Belgium": "BEL", "Croatia": "CRO",
    "Austria": "AUT", "Switzerland": "SUI", "Norway": "NOR", "Sweden": "SWE",
    "Czech Republic": "CZE", "Czechia": "CZE", "Turkey": "TUR", "Türkiye": "TUR",
    "Scotland": "SCO", "Bosnia and Herzegovina": "BIH",
    "Bosnia & Herzegovina": "BIH", "Argentina": "ARG", "Brazil": "BRA",
    "Colombia": "COL", "Uruguay": "URU", "Ecuador": "ECU", "Paraguay": "PAR",
    "United States": "USA", "USA": "USA", "Mexico": "MEX", "Canada": "CAN",
    "Panama": "PAN", "Curacao": "CUW", "Curaçao": "CUW", "Haiti": "HAI",
    "Japan": "JPN", "South Korea": "KOR", "Korea Republic": "KOR",
    "Iran": "IRN", "Saudi Arabia": "KSA", "Australia": "AUS", "Qatar": "QAT",
    "Iraq": "IRQ", "Jordan": "JOR", "Uzbekistan": "UZB", "Morocco": "MAR",
    "Senegal": "SEN", "Egypt": "EGY", "Algeria": "ALG", "Tunisia": "TUN",
    "Ivory Coast": "CIV", "Ghana": "GHA", "DR Congo": "COD",
    "South Africa": "RSA", "Cape Verde": "CPV", "New Zealand": "NZL",
    "Italy": "ITA", "Denmark": "DEN",
}


def buchdahl_demargin(oh: float, od: float, oa: float) -> tuple[float, float, float]:
    """Retire la marge bookmaker par normalisation proportionnelle (Buchdahl)."""
    raw = np.array([1.0 / oh, 1.0 / od, 1.0 / oa])
    return tuple((raw / raw.sum()).tolist())


def fetch_pinnacle() -> tuple[list[dict], str]:
    key = os.environ.get("ODDS_API_KEY", "")
    if not key:
        return [], "no_key"
    r = requests.get(
        "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/",
        params={"apiKey": key, "regions": "eu", "markets": "h2h",
                "bookmakers": "pinnacle", "oddsFormat": "decimal"}, timeout=30,
    )
    if r.status_code != 200:
        return [], f"http_{r.status_code}"
    out = []
    for pm in r.json():
        h, a = pm.get("home_team"), pm.get("away_team")
        for bk in pm.get("bookmakers", []):
            if bk["key"] != "pinnacle":
                continue
            for mk in bk.get("markets", []):
                if mk["key"] != "h2h":
                    continue
                od = {o["name"]: o["price"] for o in mk["outcomes"]}
                oh, odr, oa = od.get(h), od.get("Draw"), od.get(a)
                if oh and odr and oa:
                    out.append({"home": h, "away": a, "commence": pm.get("commence_time"),
                                "pin_h": oh, "pin_d": odr, "pin_a": oa})
    return out, "live"


def model_1x2(elo_h: float, elo_a: float) -> tuple[float, float, float]:
    """Proba 1X2 du modele prod (phase poule)."""
    delta = elo_h - elo_a
    elo_avg = (elo_h + elo_a) / 2.0
    return ws.sigmoid_v8_1x2(delta, elo_avg=elo_avg, phase="G")


def implied_delta_from_market(ph: float, pd: float, pa: float) -> int:
    """Inverse les probas marche -> delta Elo via la MEME sigmoid (elo_avg=1800).

    Donne le delta Elo que NOTRE modele aurait besoin pour reproduire le marche.
    """
    best_d, best_err = 0, float("inf")
    for delta in range(-800, 801, 2):
        m1, mx, m2 = ws.sigmoid_v8_1x2(delta, elo_avg=1800, phase="G")
        err = (m1 - ph) ** 2 + (mx - pd) ** 2 + (m2 - pa) ** 2
        if err < best_err:
            best_err, best_d = err, delta
    return best_d


def market_implied_elo(matches: list[dict], anchor_elo: dict[str, float]) -> dict[str, float]:
    """Classement Elo implicite marche par moindres carres sur les deltas.

    Pour chaque match : E_home - E_away ≈ implied_delta. Systeme surdetermine
    resolu par lstsq, ancre a la meme moyenne que notre Elo (sur les memes
    nations) pour rendre les niveaux comparables.
    """
    codes = sorted({m["ch"] for m in matches} | {m["ca"] for m in matches})
    idx = {c: i for i, c in enumerate(codes)}
    rows, y = [], []
    for m in matches:
        row = np.zeros(len(codes))
        row[idx[m["ch"]]] = 1.0
        row[idx[m["ca"]]] = -1.0
        rows.append(row)
        y.append(m["implied_delta"])
    # contrainte d'ancrage : moyenne fixee
    anchor_row = np.ones(len(codes))
    rows.append(anchor_row)
    target_mean = np.mean([anchor_elo[c] for c in codes])
    y.append(target_mean * len(codes))
    A = np.array(rows)
    sol, *_ = np.linalg.lstsq(A, np.array(y), rcond=None)
    return {c: float(sol[idx[c]]) for c in codes}


def main() -> int:
    print("[1/4] Fetch Pinnacle live (TheOddsAPI)…")
    raw, src = fetch_pinnacle()
    print(f"      source={src}  matchs avec 1X2 complet={len(raw)}")
    if not raw:
        print("ERREUR : aucune cote Pinnacle. Abandon.")
        return 1

    elo = json.loads(PROD_ELO.read_text())["elo"]

    print("[2/4] Construction dataset (de-vig + modele)…")
    matches, skipped = [], []
    for m in raw:
        ch = PIN_TO_CODE.get(m["home"])
        ca = PIN_TO_CODE.get(m["away"])
        if not ch or not ca:
            skipped.append((m["home"], m["away"], "code_inconnu"))
            continue
        if ch not in elo or ca not in elo:
            skipped.append((m["home"], m["away"], "elo_manquant"))
            continue
        mh, md, ma = buchdahl_demargin(m["pin_h"], m["pin_d"], m["pin_a"])
        eh, ea = elo[ch], elo[ca]
        p1, px, p2 = model_1x2(eh, ea)
        imp = implied_delta_from_market(mh, md, ma)
        tvd = 0.5 * (abs(p1 - mh) + abs(px - md) + abs(p2 - ma))
        matches.append({
            "home": m["home"], "away": m["away"], "ch": ch, "ca": ca,
            "elo_h": eh, "elo_a": ea, "delta_elo": eh - ea,
            "mkt": [mh, md, ma], "model": [p1, px, p2],
            "implied_delta": imp,
            "tvd": tvd,
            "edge_h": p1 - mh, "edge_d": px - md, "edge_a": p2 - ma,
            "fav_model": "H" if p1 >= max(px, p2) else ("A" if p2 >= px else "D"),
            "fav_mkt": "H" if mh >= max(md, ma) else ("A" if ma >= md else "D"),
        })

    n = len(matches)
    print(f"      retenus={n}  ignores={len(skipped)} {skipped if skipped else ''}")

    print("[3/4] Metriques agregees…")
    tvds = np.array([x["tvd"] for x in matches])
    fav_agree = np.mean([x["fav_model"] == x["fav_mkt"] for x in matches])
    # biais directionnel : moyenne signee des proba (modele - marche)
    bias_h = np.mean([x["edge_h"] for x in matches])
    bias_d = np.mean([x["edge_d"] for x in matches])
    bias_a = np.mean([x["edge_a"] for x in matches])
    # sur/sous-confiance sur le favori : proba du favori marche
    fav_gap = []
    for x in matches:
        i = {"H": 0, "D": 1, "A": 2}[x["fav_mkt"]]
        fav_gap.append(x["model"][i] - x["mkt"][i])
    fav_gap = np.array(fav_gap)
    # correlation des proba favori
    mkt_fav = np.array([max(x["mkt"]) for x in matches])
    mdl_fav = np.array([x["model"][np.argmax(x["mkt"])] for x in matches])
    corr = float(np.corrcoef(mkt_fav, mdl_fav)[0, 1])

    print(f"      TVD moyenne={tvds.mean()*100:.2f}%  mediane={np.median(tvds)*100:.2f}%  max={tvds.max()*100:.2f}%")
    print(f"      accord favori={fav_agree*100:.1f}%   corr proba-favori={corr:.3f}")
    print(f"      biais signe (modele-marche) H={bias_h*100:+.2f}% D={bias_d*100:+.2f}% A={bias_a*100:+.2f}%")
    print(f"      gap proba favori (modele-marche)={fav_gap.mean()*100:+.2f}%  (>0 = modele plus tranche)")

    # Elo implicite marche
    print("[4/4] Classement Elo implicite marche (lstsq)…")
    mkt_elo = market_implied_elo(matches, elo)
    diff_rows = []
    for c in sorted(mkt_elo, key=lambda x: -mkt_elo[x]):
        diff_rows.append((c, elo[c], mkt_elo[c], elo[c] - mkt_elo[c]))

    # plus gros ecarts 1X2 (value potentielle) trie par |edge| max sur un outcome
    def max_edge(x):
        return max(abs(x["edge_h"]), abs(x["edge_d"]), abs(x["edge_a"]))
    top_div = sorted(matches, key=max_edge, reverse=True)[:15]

    # ── Console : tableaux clefs ──
    print("\n===== NATIONS : notre Elo vs Elo implicite marche =====")
    print(f"{'NAT':<4}{'Elo_prod':>9}{'Elo_mkt':>9}{'Δ(prod-mkt)':>13}")
    over = sorted(diff_rows, key=lambda r: -r[3])[:8]
    under = sorted(diff_rows, key=lambda r: r[3])[:8]
    print("  -- on les SUR-cote vs marche (Δ>0, on est plus haut) --")
    for c, ep, em, d in over:
        print(f"{c:<4}{ep:>9.0f}{em:>9.0f}{d:>+13.0f}")
    print("  -- on les SOUS-cote vs marche (Δ<0, on est plus bas) --")
    for c, ep, em, d in under:
        print(f"{c:<4}{ep:>9.0f}{em:>9.0f}{d:>+13.0f}")

    print("\n===== TOP 15 ECARTS 1X2 (modele - marche) =====")
    print(f"{'match':<26}{'modele(H/D/A)':>20}{'marche(H/D/A)':>20}{'TVD':>7}")
    for x in top_div:
        mdl = "/".join(f"{p*100:.0f}" for p in x["model"])
        mkt = "/".join(f"{p*100:.0f}" for p in x["mkt"])
        lbl = f"{x['ch']}-{x['ca']}"
        print(f"{lbl:<26}{mdl:>20}{mkt:>20}{x['tvd']*100:>6.1f}%")

    # ── Sauvegardes ──
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "source": src, "n_matches": n, "skipped": skipped,
        "aggregate": {
            "tvd_mean": float(tvds.mean()), "tvd_median": float(np.median(tvds)),
            "tvd_max": float(tvds.max()), "fav_agree": float(fav_agree),
            "corr_fav": corr, "bias_h": float(bias_h), "bias_d": float(bias_d),
            "bias_a": float(bias_a), "fav_gap_mean": float(fav_gap.mean()),
        },
        "matches": matches,
        "market_implied_elo": mkt_elo,
        "elo_diff": [{"code": c, "elo_prod": ep, "elo_mkt": em, "diff": d}
                     for c, ep, em, d in diff_rows],
    }, indent=2, ensure_ascii=False))
    print(f"\n-> JSON {OUT_JSON.relative_to(REPO)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
