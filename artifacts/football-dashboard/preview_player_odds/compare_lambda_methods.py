"""
Comparaison méthodes de calcul λ_home / λ_away (xG team prématch)

OBJECTIF :
  Comparer la méthode actuelle (Nelder-Mead, g2_engine.lambdas_buchdahl)
  contre la méthode "G2+ adaptée" analytique (formule fermée) sur des
  vrais matchs Bundesliga via The Odds API.

ÉTAPES :
  1. Récupère N matchs Bundesliga à venir (1X2 + BTTS + O/U 2.5)
  2. Pour chaque match, applique les 2 méthodes
  3. Affiche tableau comparatif : valeurs, écart, temps de calcul
  4. Affiche aussi P(0) équipe → utile pour Garantie 2+
"""
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT.parent))
from g2_engine import lambdas_buchdahl, remove_margin_proportional, remove_margin_2way
from scipy.stats import poisson


def reconstruct_market_probas(lh, la, max_g=10):
    """À partir de (λ_h, λ_a) Poisson indépendants, reconstruit
    les probas 1X2, P(U2.5), P(BTTS_no) du marché. Sert à vérifier
    si les λ trouvés sont cohérents avec les cotes saisies."""
    pw = pd_ = pl = pu25 = 0.0
    p0_h = math.exp(-lh)
    p0_a = math.exp(-la)
    for i in range(max_g):
        pi = poisson.pmf(i, lh)
        for j in range(max_g):
            pj = poisson.pmf(j, la)
            p = pi * pj
            if i > j: pw += p
            elif i == j: pd_ += p
            else: pl += p
            if i + j <= 2: pu25 += p
    p_btts_no = p0_h + p0_a - p0_h * p0_a
    return pw, pd_, pl, pu25, p_btts_no

ODDS_API_KEY = os.environ["ODDS_API_KEY"]
SPORT = "soccer_germany_bundesliga"
N_MATCHES = 5


# ============================================================
# MÉTHODE NOUVELLE — formule fermée 1X2 + BTTS + O/U 2.5
# ============================================================
def lambdas_analytical(odds_h, odds_d, odds_a,
                        ou25_under, ou25_over,
                        btts_yes, btts_no):
    """
    Calcule (λ_home, λ_away) en formule fermée.

    Hypothèse : Buts ~ Poisson indépendantes (même hypothèse que ta
    feuille Garantie 2+).

    ÉTAPE 1 — Dévigorisation des 3 marchés (proportionnelle)
        On retire la marge bookmaker pour obtenir les vraies probas.

    ÉTAPE 2 — Résolution de λ_total (= λ_h + λ_a) via Poisson U2.5
        P(U2.5) = e^(-λ_t) * (1 + λ_t + λ_t²/2)
        → bissection 1D sur λ_t (40 itérations, précision ~1e-12)

    ÉTAPE 3 — Résolution analytique de λ_h et λ_a via BTTS
        u = e^(-λ_h), v = e^(-λ_a)
        u·v = e^(-λ_t)               (sortie de l'étape 2)
        u + v - u·v = P(BTTS_no)     (équation BTTS)
        → u + v = P(BTTS_no) + e^(-λ_t)
        → u et v sont les 2 racines d'une quadratique :
              x² - (u+v)·x + u·v = 0

    ÉTAPE 4 — Désambiguation home/away via 1X2
        On utilise les probas 1X2 dévigées : si ph > pa, l'équipe
        home est favorite → λ_h > λ_a → e^(-λ_h) < e^(-λ_a) → u < v
    """
    # ÉTAPE 1 — Dévigorisation
    # 1X2 (3-way) : méthode proportionnelle (la plus standard)
    fair_h, fair_d, fair_a = remove_margin_proportional(odds_h, odds_d, odds_a)
    ph, pd_, pa = 1.0/fair_h, 1.0/fair_d, 1.0/fair_a

    # O/U 2.5 (2-way)
    fair_under, fair_over = remove_margin_2way(ou25_under, ou25_over)
    p_u25 = 1.0 / fair_under

    # BTTS (2-way)
    fair_btts_yes, fair_btts_no = remove_margin_2way(btts_yes, btts_no)
    p_btts_no = 1.0 / fair_btts_no

    # ÉTAPE 2 — λ_total via bissection
    # P(U2.5 buts) = P(0)+P(1)+P(2) = e^(-λ)*(1 + λ + λ²/2)
    # Cette fonction est strictement décroissante en λ → bissection OK
    lo_t, hi_t = 0.05, 7.0
    for _ in range(40):
        mid = (lo_t + hi_t) / 2
        p_calc = math.exp(-mid) * (1 + mid + mid*mid/2)
        if p_calc > p_u25:
            lo_t = mid    # λ trop petit → on monte
        else:
            hi_t = mid    # λ trop grand → on descend
    lambda_total = (lo_t + hi_t) / 2

    # ÉTAPE 3 — Quadratique pour u et v
    # u·v = e^(-λ_total) (= P(0-0) sous Poisson indépendantes)
    p00 = math.exp(-lambda_total)
    # u + v = P(BTTS_no) + p00
    s = p_btts_no + p00
    # x² - s·x + p00 = 0  →  discriminant = s² - 4·p00
    disc = s*s - 4*p00
    if disc < 0:
        # Cas pathologique : BTTS et O/U 2.5 incohérents.
        # On force au point de tangence (u = v = s/2)
        disc = 0
    sqrt_disc = math.sqrt(disc)
    u_small = (s - sqrt_disc) / 2   # plus petite racine → équipe forte
    u_large = (s + sqrt_disc) / 2   # plus grande racine → équipe faible

    # Filet de sécurité numérique (probabilités dans [0,1])
    u_small = max(min(u_small, 0.999), 1e-6)
    u_large = max(min(u_large, 0.999), 1e-6)

    # ÉTAPE 4 — Désambiguation via 1X2
    # Équipe favorite (ph > pa) → λ plus grand → e^(-λ) plus petit
    if ph >= pa:
        lambda_home = -math.log(u_small)
        lambda_away = -math.log(u_large)
    else:
        lambda_home = -math.log(u_large)
        lambda_away = -math.log(u_small)

    return lambda_home, lambda_away, {
        "p_h_devig": ph, "p_d_devig": pd_, "p_a_devig": pa,
        "p_u25_devig": p_u25, "p_btts_no_devig": p_btts_no,
        "lambda_total": lambda_total, "p00": p00,
        "discriminant": disc,
    }


# ============================================================
# Récupération matchs Bundesliga via The Odds API
# ============================================================
def fetch_matches():
    """
    L'endpoint /odds ne supporte pas btts pour soccer.
    Il faut passer par /events/{id}/odds (per-event), un appel par match.
    Coûte N+1 credits (1 pour la liste, 1 par event analysé).
    """
    url_list = (f"https://api.the-odds-api.com/v4/sports/{SPORT}/events"
                f"?apiKey={ODDS_API_KEY}")
    with urllib.request.urlopen(url_list, timeout=15) as r:
        events = json.loads(r.read())
    print(f"  {len(events)} events Bundesliga listés. Fetch détail pour les {N_MATCHES} prochains...")

    full = []
    for ev in events[:N_MATCHES]:
        url_ev = (f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{ev['id']}/odds"
                  f"?regions=eu&markets=h2h,totals,btts"
                  f"&oddsFormat=decimal&apiKey={ODDS_API_KEY}")
        try:
            with urllib.request.urlopen(url_ev, timeout=15) as r:
                full.append(json.loads(r.read()))
        except urllib.error.HTTPError as e:
            print(f"  ERR {ev['id']}: {e.code}")
    return full


def extract_consensus_odds(match):
    """
    Pour chaque marché, prend la MÉDIANE des cotes proposées par les
    bookmakers (robuste aux outliers). Si pas assez de books → None.
    """
    home, away = match["home_team"], match["away_team"]
    h2h, totals_25, btts = [], [], []
    for bk in match.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk["key"] == "h2h":
                d = {o["name"]: o["price"] for o in mk["outcomes"]}
                if home in d and away in d and "Draw" in d:
                    h2h.append((d[home], d["Draw"], d[away]))
            elif mk["key"] == "totals":
                # On veut le 2.5 pile
                u25 = next((o["price"] for o in mk["outcomes"]
                            if o["name"] == "Under" and abs(o.get("point",0)-2.5) < 0.01), None)
                o25 = next((o["price"] for o in mk["outcomes"]
                            if o["name"] == "Over" and abs(o.get("point",0)-2.5) < 0.01), None)
                if u25 and o25:
                    totals_25.append((u25, o25))
            elif mk["key"] == "btts":
                d = {o["name"]: o["price"] for o in mk["outcomes"]}
                if "Yes" in d and "No" in d:
                    btts.append((d["Yes"], d["No"]))

    def median(xs): xs = sorted(xs); return xs[len(xs)//2]
    if not h2h or not totals_25 or not btts:
        return None
    h2h_med = (median([x[0] for x in h2h]),
               median([x[1] for x in h2h]),
               median([x[2] for x in h2h]))
    tot_med = (median([x[0] for x in totals_25]),
               median([x[1] for x in totals_25]))
    btts_med = (median([x[0] for x in btts]),
                median([x[1] for x in btts]))
    return {
        "home": home, "away": away,
        "kickoff": match["commence_time"],
        "h2h": h2h_med, "totals_25": tot_med, "btts": btts_med,
        "n_books": {"h2h": len(h2h), "totals": len(totals_25), "btts": len(btts)},
    }


def main():
    print("="*78)
    print("COMPARAISON: Nelder-Mead actuel  vs  Formule fermée analytique")
    print("="*78)
    print("Source: The Odds API — Bundesliga prochains matchs")
    print("Méthode prix: médiane des bookmakers (robuste outliers)")

    matches = fetch_matches()
    print(f"\n{len(matches)} matchs Bundesliga retournés par l'API")

    extracted = []
    for m in matches:
        x = extract_consensus_odds(m)
        if x: extracted.append(x)
    print(f"{len(extracted)} matchs avec les 3 marchés (1X2 + O/U 2.5 + BTTS)")

    extracted = extracted[:N_MATCHES]
    print(f"On en analyse {len(extracted)}")

    print()
    print(f"{'Match':<45} {'1X2':>17} {'O/U 2.5':>11} {'BTTS':>11}")
    print("-"*88)
    for x in extracted:
        h, d, a = x["h2h"]
        u25, o25 = x["totals_25"]
        by, bn = x["btts"]
        label = f"{x['home'][:18]} vs {x['away'][:18]}"
        print(f"{label:<45} {h:>5.2f}/{d:>4.2f}/{a:>5.2f} {u25:>4.2f}/{o25:>4.2f} {by:>4.2f}/{bn:>4.2f}")

    print("\n" + "="*78)
    print(f"{'Match':<35} {'NM λ_h/λ_a':>13} {'AN λ_h/λ_a':>13} {'Δ_h':>7} {'Δ_a':>7}")
    print("-"*88)

    t_nm = t_an = 0.0
    deltas_h, deltas_a = [], []
    details = []

    for x in extracted:
        h, d, a = x["h2h"]
        u25, o25 = x["totals_25"]
        by, bn = x["btts"]

        # Méthode actuelle (Nelder-Mead) — appel SANS correct scores
        t0 = time.perf_counter()
        nm_h, nm_a, nm_meth = lambdas_buchdahl(
            h, d, a,
            ou25_under=u25, ou25_over=o25,
            btts_yes=by, btts_no=bn,
        )
        t_nm += time.perf_counter() - t0

        # Méthode nouvelle (analytique fermée)
        t0 = time.perf_counter()
        an_h, an_a, an_dbg = lambdas_analytical(
            h, d, a, u25, o25, by, bn,
        )
        t_an += time.perf_counter() - t0

        d_h = an_h - nm_h
        d_a = an_a - nm_a
        deltas_h.append(d_h); deltas_a.append(d_a)
        label = f"{x['home'][:14]} vs {x['away'][:14]}"
        print(f"{label:<35} {nm_h:>5.2f}/{nm_a:>5.2f}    {an_h:>5.2f}/{an_a:>5.2f}    {d_h:>+5.2f}  {d_a:>+5.2f}")
        details.append((x, nm_h, nm_a, an_h, an_a, an_dbg))

    n = len(extracted)
    print("-"*88)
    print(f"\nTemps total: Nelder-Mead = {t_nm*1000:.0f} ms  |  Analytique = {t_an*1000:.0f} ms")
    print(f"Speedup: {t_nm/t_an:.0f}× plus rapide")
    print(f"\nÉcart moyen   λ_home: {sum(deltas_h)/n:+.4f}  |  λ_away: {sum(deltas_a)/n:+.4f}")
    print(f"Écart max abs λ_home: {max(abs(x) for x in deltas_h):.4f}  |  λ_away: {max(abs(x) for x in deltas_a):.4f}")

    # ===== Test de cohérence : reproduit-on les cotes du marché ? =====
    print("\n" + "="*78)
    print("TEST DE COHÉRENCE : reproduit-on les cotes 1X2/U2.5/BTTS du marché ?")
    print("="*78)
    print(f"{'Match':<28} {'P(home)':>26} {'P(U2.5)':>20} {'P(BTTS_no)':>20}")
    print(f"{'':<28} {'mkt    NM    AN':>26} {'mkt    NM    AN':>20} {'mkt    NM    AN':>20}")
    print("-"*98)
    for x, nmh, nma, anh, ana, dbg in details:
        nm_pw, _, _, nm_u25, nm_btts_no = reconstruct_market_probas(nmh, nma)
        an_pw, _, _, an_u25, an_btts_no = reconstruct_market_probas(anh, ana)
        label = f"{x['home'][:12]} vs {x['away'][:12]}"
        print(f"{label:<28} "
              f"{dbg['p_h_devig']:.3f} {nm_pw:.3f} {an_pw:.3f}   "
              f"{dbg['p_u25_devig']:.3f} {nm_u25:.3f} {an_u25:.3f}   "
              f"{dbg['p_btts_no_devig']:.3f} {nm_btts_no:.3f} {an_btts_no:.3f}")
    print("\n→ Plus 'NM/AN' est proche de 'mkt', mieux la méthode reproduit la cote.")
    print("→ AN respecte exactement U2.5 et BTTS_no (par construction).")
    print("→ AN peut s'écarter sur P(home) car le 1X2 ne sert qu'à désambiguer u/v.")

    # Détail premier match — pédagogique
    print("\n" + "="*78)
    x, nmh, nma, anh, ana, dbg = details[0]
    print(f"DÉTAIL ÉTAPES (match: {x['home']} vs {x['away']})")
    print("="*78)
    print(f"Cotes brutes (médianes bookmakers):")
    print(f"  1X2       : {x['h2h'][0]} / {x['h2h'][1]} / {x['h2h'][2]}")
    print(f"  O/U 2.5   : Under {x['totals_25'][0]} / Over {x['totals_25'][1]}")
    print(f"  BTTS      : Yes {x['btts'][0]} / No {x['btts'][1]}")
    print(f"\nÉtape 1 - Dévigorisation:")
    print(f"  P(home win) = {dbg['p_h_devig']:.4f}")
    print(f"  P(draw)     = {dbg['p_d_devig']:.4f}")
    print(f"  P(away win) = {dbg['p_a_devig']:.4f}   (somme = {dbg['p_h_devig']+dbg['p_d_devig']+dbg['p_a_devig']:.4f})")
    print(f"  P(under 2.5) = {dbg['p_u25_devig']:.4f}")
    print(f"  P(BTTS_no)   = {dbg['p_btts_no_devig']:.4f}")
    print(f"\nÉtape 2 - λ_total via bissection sur Poisson U2.5:")
    print(f"  λ_total = {dbg['lambda_total']:.4f}")
    print(f"  → P(0-0) = e^(-λ_total) = {dbg['p00']:.4f}")
    print(f"\nÉtape 3 - Quadratique BTTS:")
    print(f"  u·v = P(0-0) = {dbg['p00']:.4f}")
    print(f"  u+v = P(BTTS_no) + P(0-0) = {dbg['p_btts_no_devig']:.4f} + {dbg['p00']:.4f} = {dbg['p_btts_no_devig']+dbg['p00']:.4f}")
    print(f"  Discriminant = (u+v)² - 4·u·v = {dbg['discriminant']:.6f}")
    print(f"\nÉtape 4 - Désambiguation 1X2:")
    print(f"  ph={dbg['p_h_devig']:.3f} vs pa={dbg['p_a_devig']:.3f} → home {'favorite' if dbg['p_h_devig']>=dbg['p_a_devig'] else 'outsider'}")
    print(f"\nRésultat:")
    print(f"  λ_home = {anh:.4f}   (Nelder-Mead: {nmh:.4f}, écart {anh-nmh:+.4f})")
    print(f"  λ_away = {ana:.4f}   (Nelder-Mead: {nma:.4f}, écart {ana-nma:+.4f})")
    print(f"  P(0 home) = e^(-λ_home) = {math.exp(-anh):.4f}  → utilisable direct dans Garantie 2+")
    print(f"  P(0 away) = e^(-λ_away) = {math.exp(-ana):.4f}  → utilisable direct dans Garantie 2+")


if __name__ == "__main__":
    main()
