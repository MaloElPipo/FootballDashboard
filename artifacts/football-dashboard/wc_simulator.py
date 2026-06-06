import math
import random
import numpy as np
from collections import defaultdict
from elo_engine import compute_all_nations_elo, fetch_elorating_base
from nations_data import get_nation_by_code

WC2026_GROUPS = {
    "A": ["MEX", "RSA", "KOR", "CZE"],
    "B": ["CAN", "BIH", "QAT", "SUI"],
    "C": ["BRA", "MAR", "HAI", "SCO"],
    "D": ["USA", "PAR", "AUS", "TUR"],
    "E": ["GER", "CUW", "CIV", "ECU"],
    "F": ["NED", "JPN", "SWE", "TUN"],
    "G": ["BEL", "EGY", "IRN", "NZL"],
    "H": ["ESP", "CPV", "KSA", "URU"],
    "I": ["FRA", "SEN", "IRQ", "NOR"],
    "J": ["ARG", "ALG", "AUT", "JOR"],
    "K": ["POR", "COD", "UZB", "COL"],
    "L": ["ENG", "CRO", "GHA", "PAN"],
}

GROUP_MATCHES = {
    "MD1": [(0, 1), (2, 3)],
    "MD2": [(0, 2), (3, 1)],
    "MD3": [(3, 0), (1, 2)],
}

# --- Modèle de résultat des matchs de poule (FLAG ROLLBACK) -----------------
# "market"  (DÉFAUT) : l'issue W/N/D qui attribue les points est tirée du 1X2
#                      marché Pinnacle de-vigé (params["market_1x2"]) quand le
#                      match est couvert, sinon fallback sigmoïde calibrée
#                      sigmoid_v8_1x2. Corrige la compression des favoris/qualif
#                      (2 Poisson Elo indépendants sur-produisaient les nuls) et
#                      capte l'avantage hôte présent dans les cotes.
# "legacy"            : ancien modèle = 2 Poisson Elo indépendants
#                      (simulate_match_goals). Pour REVENIR EN ARRIÈRE, remettre
#                      simplement cette constante à "legacy".
GROUP_OUTCOME_MODEL = "market"

R32_BRACKET = [
    {"match": 73, "home": ("2", "A"), "away": ("2", "B")},
    {"match": 74, "home": ("1", "E"), "away": ("3rd", "A/B/C/D/F")},
    {"match": 75, "home": ("1", "F"), "away": ("2", "C")},
    {"match": 76, "home": ("1", "C"), "away": ("2", "F")},
    {"match": 77, "home": ("1", "I"), "away": ("3rd", "C/D/F/G/H")},
    {"match": 78, "home": ("2", "E"), "away": ("2", "I")},
    {"match": 79, "home": ("1", "A"), "away": ("3rd", "C/E/F/H/I")},
    {"match": 80, "home": ("1", "L"), "away": ("3rd", "E/H/I/J/K")},
    {"match": 81, "home": ("1", "D"), "away": ("3rd", "B/E/F/I/J")},
    {"match": 82, "home": ("1", "G"), "away": ("3rd", "A/E/H/I/J")},
    {"match": 83, "home": ("2", "K"), "away": ("2", "L")},
    {"match": 84, "home": ("1", "H"), "away": ("2", "J")},
    {"match": 85, "home": ("1", "B"), "away": ("3rd", "E/F/G/I/J")},
    {"match": 86, "home": ("1", "J"), "away": ("2", "H")},
    {"match": 87, "home": ("1", "K"), "away": ("3rd", "D/E/I/J/L")},
    {"match": 88, "home": ("2", "D"), "away": ("2", "G")},
]

R16_PAIRINGS = [
    (74, 77), (73, 75), (83, 84), (81, 82),
    (76, 78), (79, 80), (86, 88), (85, 87),
]

QF_PAIRINGS = [
    (0, 1), (2, 3), (4, 5), (6, 7),
]

SF_PAIRINGS = [(0, 1), (2, 3)]

HOST_NATIONS = {"USA", "MEX", "CAN"}

V7_SCALE = 441.952
V7_DRAW_BASE = 24.09
V7_D_HALF = 463.648
V7_POWER = 3.56
V7_QUALITY = 0.035

V8_DRAW_BOOST_CLOSE = 4.312
V8_DRAW_BOOST_MID = 2.555
V8_DRAW_BOOST_KO = 3.37
V8_DRAW_BOOST_MAX = 36.049
V8_FAV_BOOST_GROUP = -2.446
V8_FAV_BOOST_KO = 2.746
V8_FAV_DELTA_THRESHOLD = 380.332


def sigmoid_v6_1x2(delta_elo, params=None, elo_avg=None):
    if params is None:
        params = (V7_SCALE, V7_DRAW_BASE, V7_D_HALF, V7_POWER, V7_QUALITY)
    if len(params) == 4:
        scale, draw_base, d_half, power = params
        quality = V7_QUALITY
    else:
        scale, draw_base, d_half, power, quality = params
    d_half = max(d_half, 1.0)
    draw_adj = draw_base
    if elo_avg is not None:
        draw_adj = draw_base + quality * (elo_avg - 1800) / 100
        draw_adj = max(draw_adj, 5.0)
    draw = draw_adj / (1.0 + (abs(delta_elo) / d_half) ** power)
    draw = max(draw, 0.5)
    sig = 1.0 / (1.0 + 10.0 ** (-delta_elo / scale))
    p1 = (100.0 - draw) * sig
    p2 = (100.0 - draw) * (1.0 - sig)
    p1 = float(np.clip(p1, 0.5, 99.0))
    p2 = float(np.clip(p2, 0.5, 99.0))
    draw = float(np.clip(draw, 0.5, 99.0))
    total = p1 + draw + p2
    return p1 / total, draw / total, p2 / total


def sigmoid_v8_1x2(delta_elo, elo_avg=None, phase="G"):
    p1, px, p2 = sigmoid_v6_1x2(delta_elo, elo_avg=elo_avg)

    abs_d = abs(delta_elo)
    draw_boost = 0.0
    if abs_d < 100:
        draw_boost += V8_DRAW_BOOST_CLOSE / 100.0
    elif abs_d < 200:
        draw_boost += V8_DRAW_BOOST_MID / 100.0

    if phase == "K":
        draw_boost += V8_DRAW_BOOST_KO / 100.0

    draw_boost = min(draw_boost, V8_DRAW_BOOST_MAX / 100.0)

    fav_boost = 0.0
    if abs_d >= V8_FAV_DELTA_THRESHOLD:
        if phase == "K":
            fav_boost = V8_FAV_BOOST_KO / 100.0
        else:
            fav_boost = V8_FAV_BOOST_GROUP / 100.0

    net_draw = draw_boost - fav_boost * 0.7
    net_draw = max(net_draw, 0.0)

    px_new = px + net_draw
    surplus_h_a = net_draw
    if p1 + p2 > 0:
        p1_new = p1 - surplus_h_a * (p1 / (p1 + p2))
        p2_new = p2 - surplus_h_a * (p2 / (p1 + p2))
    else:
        p1_new = p1
        p2_new = p2

    if fav_boost > 0:
        if delta_elo >= 0:
            p1_new += fav_boost
            px_new -= fav_boost * 0.7
            p2_new -= fav_boost * 0.3
        else:
            p2_new += fav_boost
            px_new -= fav_boost * 0.7
            p1_new -= fav_boost * 0.3

    p1_new = max(p1_new, 0.005)
    p2_new = max(p2_new, 0.005)
    px_new = max(px_new, 0.005)
    total = p1_new + px_new + p2_new
    return p1_new / total, px_new / total, p2_new / total


def _build_elo_map(forced_weight=None, pin_weight=None):
    elo_base = fetch_elorating_base()
    all_elo = compute_all_nations_elo(elorating_base=elo_base, forced_weight=forced_weight, pin_weight=pin_weight)
    return {r["code"]: r["elo"] for r in all_elo}


def simulate_match_1x2(elo_h, elo_a, home_code=None, away_code=None, phase="G"):
    delta = elo_h - elo_a
    elo_avg = (elo_h + elo_a) / 2
    ph, pd, pa = sigmoid_v8_1x2(delta, elo_avg=elo_avg, phase=phase)
    r = random.random()
    if r < ph:
        return "H"
    elif r < ph + pd:
        return "D"
    else:
        return "A"


def derive_lambdas_from_elo(elo_h, elo_a):
    """Calcule (λ_home, λ_away) déterministes depuis l'Elo (sans tirage).

    Utilisé comme fallback quand les cotes bookmakers ne sont pas disponibles
    pour un match (ex : Pinnacle ne couvre pas le match). Identique à la
    formule interne de `simulate_match_goals` mais expose les paramètres au
    lieu de tirer un Poisson.
    """
    delta = elo_h - elo_a
    base = 1.25
    factor = delta / 600.0
    lambda_h = base * math.exp(factor * 0.5)
    lambda_a = base * math.exp(-factor * 0.5)
    lambda_h = max(0.3, min(lambda_h, 4.0))
    lambda_a = max(0.3, min(lambda_a, 4.0))
    return lambda_h, lambda_a


def most_likely_score(lambda_h, lambda_a, max_goals=8):
    """Renvoie (h*, a*) avec la probabilité conjointe Poisson maximale.

    Modèle Poisson indépendant : P(H=i, A=j) = pmf(i, λh) × pmf(j, λa).
    Recherche exhaustive sur la grille [0, max_goals]². Avec max_goals=8 et
    λ ≤ 4 (cap Elo), la masse cumulée hors grille est < 0.001 → score modal
    capturé avec certitude.
    """
    best = (0, 0)
    best_p = -1.0
    exp_lh = math.exp(-lambda_h)
    exp_la = math.exp(-lambda_a)
    fact_i = 1.0
    for i in range(max_goals + 1):
        if i > 0:
            fact_i *= i
        p_i = exp_lh * (lambda_h ** i) / fact_i
        fact_j = 1.0
        for j in range(max_goals + 1):
            if j > 0:
                fact_j *= j
            p_j = exp_la * (lambda_a ** j) / fact_j
            p = p_i * p_j
            if p > best_p:
                best_p = p
                best = (i, j)
    return best


def simulate_match_goals(elo_h, elo_a, home_code=None, away_code=None):
    lambda_h, lambda_a = derive_lambdas_from_elo(elo_h, elo_a)

    def poisson_sample(lam):
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= random.random()
            if p < L:
                return k - 1

    return poisson_sample(lambda_h), poisson_sample(lambda_a)


def _poisson_sample(lam):
    """Tirage Poisson(lam) (méthode de Knuth), cohérent avec le sampler interne
    de simulate_match_goals. Retourne un entier >= 0."""
    if lam <= 0:
        return 0
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while True:
        k += 1
        p *= random.random()
        if p < L:
            return k - 1


def _bucket_goals(counts, n_sims):
    """Convertit un compteur {buts: occurrences} en distribution (%) bucketisée
    0,1,2,3,4,5+ buts marqués sur les 3 matchs de poule."""
    out = {str(k): counts.get(k, 0) / n_sims * 100 for k in range(5)}
    out["5+"] = sum(v for k, v in counts.items() if k >= 5) / n_sims * 100
    return out


def simulate_knockout_match(elo_h, elo_a, home_code=None, away_code=None):
    gh, ga = simulate_match_goals(elo_h, elo_a, home_code, away_code)
    if gh != ga:
        return ("H", gh, ga) if gh > ga else ("A", gh, ga)
    delta = elo_h - elo_a
    pk = max(0.15, min(0.85, 0.5 + delta / 1200.0))
    if random.random() < pk:
        return ("H", gh + 1, ga)
    else:
        return ("A", gh, ga + 1)


def _h2h_metrics_subset(code, codes_in_tie, h2h_log):
    """Calcule (pts, diff, gf) H2H d'une équipe sur un sous-ensemble donné."""
    h2h_pts = 0
    h2h_gf = 0
    h2h_ga = 0
    opp_dict = h2h_log.get(code, {})
    for opp in codes_in_tie:
        if opp == code:
            continue
        rec = opp_dict.get(opp)
        if not rec:
            continue
        h2h_pts += rec.get("pts", 0)
        h2h_gf += rec.get("gf", 0)
        h2h_ga += rec.get("ga", 0)
    return h2h_pts, h2h_gf - h2h_ga, h2h_gf


def _rank_tied_subgroup(tied, h2h_log, elo_map):
    """Départage récursivement un sous-groupe d'équipes ex æquo (FIFA art. 13).

    Implémente la règle stricte du règlement : "If, after having applied criteria
    a) to c) above, teams still have an equal ranking, criteria a) to c) above
    are applied to the matches between the remaining teams only."

    1. Calcule (pts H2H, diff H2H, buts H2H) sur le sous-groupe courant.
    2. Trie par ce triplet décroissant.
    3. Re-groupe par triplet H2H identique :
        - Sous-sous-groupe singleton → ordre figé.
        - Sous-sous-groupe strictement plus petit que `tied` → récursion
          (re-application du step 1 sur les matchs entre seulement ces équipes).
        - Sous-sous-groupe = `tied` (pas de progrès) → fallback step 2 (d/e)
          puis step 3 Elo (proxy ranking FIFA).
    """
    if len(tied) <= 1:
        return list(tied)

    codes_in_tie = frozenset(c for c, _ in tied)

    def h2h_key(item):
        code = item[0]
        m = _h2h_metrics_subset(code, codes_in_tie, h2h_log)
        return (-m[0], -m[1], -m[2])

    tied_sorted = sorted(tied, key=h2h_key)

    from itertools import groupby
    result = []
    for _key, sub_iter in groupby(tied_sorted, key=h2h_key):
        sub = list(sub_iter)
        if len(sub) == 1:
            result.extend(sub)
        elif len(sub) < len(tied):
            result.extend(_rank_tied_subgroup(sub, h2h_log, elo_map))
        else:
            sub_sorted = sorted(sub, key=lambda x: (
                -(x[1]["gf"] - x[1]["ga"]),
                -x[1]["gf"],
                -float(elo_map.get(x[0], 1500.0)),
            ))
            result.extend(sub_sorted)
    return result


def _rank_group(standings, h2h_log=None, elo_map=None):
    """Classe les équipes d'une poule selon FIFA WC 2026 Regulations art. 13.

    Etapes officielles appliquées dans l'ordre :
        Step 1 (a/b/c)  : pts H2H, diff de buts H2H, buts marqués H2H, calculés
                          uniquement sur les matchs entre les équipes encore
                          ex æquo. Récursion stricte sur sous-sous-groupes.
        Step 2 (d/e)    : diff de buts globale, buts marqués globaux (appliqués
                          uniquement quand le step 1 ne fait plus progresser).
        Step 2 (f)      : score conduite (cartons) — OMIS (cartons non modélisés
                          en Monte-Carlo, l'Elo le remplace comme dernier
                          critère sportif).
        Step 3 (g/h)    : ranking FIFA récent puis précédent — REMPLACÉ par
                          l'Elo pré-tournoi (proxy ranking FIFA, cohérent avec
                          _pick_best_thirds).
    """
    h2h_log = h2h_log or {}
    elo_map = elo_map or {}

    items = list(standings.items())
    items.sort(key=lambda x: -x[1]["pts"])

    from itertools import groupby
    final_order = []
    for _pts, group_iter in groupby(items, key=lambda x: x[1]["pts"]):
        tied = list(group_iter)
        if len(tied) == 1:
            final_order.extend(tied)
        else:
            final_order.extend(_rank_tied_subgroup(tied, h2h_log, elo_map))

    return final_order


def _pick_best_thirds(group_results, elo_map=None, n=8, sim_seed=None):
    """Sélectionne les meilleurs `n` troisièmes des poules (CDM 2026 = 8 sur 12).

    Règle de départage adaptée du règlement FIFA, avec adaptations Monte-Carlo :
        1. Plus grand nombre de points
        2. Meilleure différence de buts
        3. Plus grand nombre de buts marqués
        4. Position au ranking pré-tournoi (PROXY = Elo, plus fort gagne)
           — équivalent fonctionnel du critère FIFA "position au classement
           mondial FIFA". Le critère officiel "fair-play" (cartons) est OMIS
           car la simulation Monte-Carlo ne modélise pas les cartons : l'Elo
           le remplace pragmatiquement (modèle, NON conforme strict FIFA).
        5. Tirage au sort
           — `sim_seed=None` (défaut) : RNG vrai aléatoire (entropie OS), donc
             chaque simulation Monte-Carlo a un tirage différent → pas de biais.
           — `sim_seed=int` : reproductible (utile en debug/tests), une seed
             différente par sim doit être passée par la boucle Monte-Carlo
             pour préserver la diversité du tirage.
    """
    import random

    elo_map = elo_map or {}
    thirds = []
    for grp_letter, ranked in group_results.items():
        if len(ranked) >= 3:
            code = ranked[2][0]
            s = ranked[2][1]
            thirds.append((grp_letter, code, s))

    rng = random.Random(sim_seed) if sim_seed is not None else random.Random()
    draw_tokens = {code: rng.random() for _, code, _ in thirds}

    def sort_key(item):
        grp, code, s = item
        return (
            -s["pts"],
            -(s["gf"] - s["ga"]),
            -s["gf"],
            -float(elo_map.get(code, 1500.0)),
            draw_tokens[code],
        )
    thirds.sort(key=sort_key)
    return thirds[:n]


THIRD_PLACE_SLOTS = [
    {"match": 74, "allowed": "A/B/C/D/F"},
    {"match": 77, "allowed": "C/D/F/G/H"},
    {"match": 79, "allowed": "C/E/F/H/I"},
    {"match": 80, "allowed": "E/H/I/J/K"},
    {"match": 81, "allowed": "B/E/F/I/J"},
    {"match": 82, "allowed": "A/E/H/I/J"},
    {"match": 85, "allowed": "E/F/G/I/J"},
    {"match": 87, "allowed": "D/E/I/J/L"},
]


def _assign_thirds_to_slots(qualified_thirds):
    third_by_group = {t[0]: t[1] for t in qualified_thirds}
    qualifying_groups = sorted(third_by_group.keys())
    slots = THIRD_PLACE_SLOTS
    n = len(slots)

    def backtrack(idx, assignment):
        if idx == n:
            return dict(assignment)
        slot = slots[idx]
        allowed = slot["allowed"].split("/")
        for grp in allowed:
            if grp in qualifying_groups and grp not in [a[1] for a in assignment]:
                if grp in third_by_group:
                    assignment.append((slot["match"], grp))
                    result = backtrack(idx + 1, assignment)
                    if result is not None:
                        return result
                    assignment.pop()
        return None

    result = backtrack(0, [])
    if result is None:
        result = {}
        used = set()
        for slot in slots:
            allowed = slot["allowed"].split("/")
            for grp in allowed:
                if grp in third_by_group and grp not in used:
                    result[slot["match"]] = grp
                    used.add(grp)
                    break

    assignment = {}
    for match_num, grp in result.items():
        assignment[match_num] = third_by_group[grp]
    return assignment


def _update_elo_from_results(base_elo, results, k=40.0):
    """Recalcule l'Elo des nations à partir d'une liste de résultats de poule.

    `results` : liste de (home_code, away_code, outcome) avec outcome ∈ {H,D,A}.
    Mise à jour Elo logistique standard (échelle 400), facteur K = `k`, terrain
    neutre (pas d'avantage hôte : matchs de poule CDM essentiellement neutres).
    Retourne une NOUVELLE map (l'originale n'est pas modifiée).
    """
    new = dict(base_elo)
    for h, a, outcome in results:
        eh = new.get(h, 1500.0)
        ea = new.get(a, 1500.0)
        exp_h = 1.0 / (1.0 + 10.0 ** ((ea - eh) / 400.0))
        if outcome == "H":
            s_h = 1.0
        elif outcome == "D":
            s_h = 0.5
        else:
            s_h = 0.0
        new[h] = eh + k * (s_h - exp_h)
        new[a] = ea + k * ((1.0 - s_h) - (1.0 - exp_h))
    return new


def simulate_tournament(elo_map, params=None):
    tracker = defaultdict(lambda: {
        "group_pos": 0, "group_pts": 0, "group_goals_scored": 0,
        "r32": False, "r16": False, "qf": False,
        "sf": False, "final": False, "winner": False,
        "bronze": False, "runner_up": False,
        "opponents": {},
    })

    expected_scores = {}
    market_1x2 = {}
    elo_recalc = False
    recalc_k = 40.0
    return_bracket = False
    locked_results = {}
    if params:
        expected_scores = params.get("expected_scores") or {}
        market_1x2 = params.get("market_1x2") or {}
        elo_recalc = bool(params.get("elo_recalc"))
        recalc_k = float(params.get("recalc_k", 40.0))
        return_bracket = bool(params.get("_return_bracket"))
        locked_results = params.get("locked_results") or {}

    group_results = {}
    group_match_results = []

    for grp_letter, teams in WC2026_GROUPS.items():
        standings = {}
        h2h_log = defaultdict(lambda: defaultdict(lambda: {"pts": 0, "gf": 0, "ga": 0}))
        for code in teams:
            standings[code] = {"pts": 0, "gf": 0, "ga": 0, "w": 0, "d": 0, "l": 0}

        for md_name, pairings in GROUP_MATCHES.items():
            for i_h, i_a in pairings:
                h_code = teams[i_h]
                a_code = teams[i_a]
                elo_h = elo_map.get(h_code, 1500)
                elo_a = elo_map.get(a_code, 1500)

                # Issue stochastique du match (W/N/D → pts). Voir GROUP_OUTCOME_MODEL
                # (flag rollback en tête de fichier).
                if GROUP_OUTCOME_MODEL == "legacy":
                    gh, ga = simulate_match_goals(elo_h, elo_a, h_code, a_code)
                    outcome = "H" if gh > ga else ("D" if gh == ga else "A")
                else:
                    mk = market_1x2.get((h_code, a_code))
                    if mk is not None:
                        pw, pdraw, pl = mk
                    else:
                        mk_rev = market_1x2.get((a_code, h_code))
                        if mk_rev is not None:
                            # Entrée orientée (away, home) côté marché : on inverse.
                            p_a, pdraw, p_h = mk_rev
                            pw, pl = p_h, p_a
                        else:
                            pw, pdraw, pl = sigmoid_v8_1x2(
                                elo_h - elo_a,
                                elo_avg=(elo_h + elo_a) / 2.0,
                                phase="G",
                            )
                    # Garde-fou : renormaliser (somme=1) pour qu'une éventuelle
                    # entrée marché malformée ne laisse pas de masse résiduelle
                    # absorbée implicitement par la victoire extérieure (biais).
                    _s = pw + pdraw + pl
                    if _s > 0:
                        pw, pdraw, pl = pw / _s, pdraw / _s, pl / _s
                    u = random.random()
                    outcome = "H" if u < pw else ("D" if u < pw + pdraw else "A")

                # Buts pour départage : on utilise les lambdas continues (xG
                # attendu) plutôt que le score modal entier. C'est aussi
                # stable (constant sur toutes les sims du même match) mais
                # bien plus précis pour le goal average affiché. Source :
                # cotes bookmakers si disponibles, sinon fallback λ Elo.
                if (h_code, a_code) in expected_scores:
                    xh, xa = expected_scores[(h_code, a_code)]
                else:
                    xh, xa = derive_lambdas_from_elo(elo_h, elo_a)

                standings[h_code]["gf"] += xh
                standings[h_code]["ga"] += xa
                standings[a_code]["gf"] += xa
                standings[a_code]["ga"] += xh

                # Buts marqués entiers (Poisson), cumulés sur les 3 matchs de
                # poule, pour les tableaux récap par nation. Indépendant du
                # départage continu ci-dessus et de l'issue 1X2 tirée plus haut.
                tracker[h_code]["group_goals_scored"] += _poisson_sample(xh)
                tracker[a_code]["group_goals_scored"] += _poisson_sample(xa)

                h2h_log[h_code][a_code]["gf"] += xh
                h2h_log[h_code][a_code]["ga"] += xa
                h2h_log[a_code][h_code]["gf"] += xa
                h2h_log[a_code][h_code]["ga"] += xh

                # Verrouillage live : si le vrai résultat de ce match de poule
                # est connu (CDM en cours), il écrase l'issue simulée.
                lg = locked_results.get("group") if locked_results else None
                if lg:
                    lk = lg.get((h_code, a_code))
                    if lk is None:
                        rev = lg.get((a_code, h_code))
                        if rev is not None:
                            lk = {"H": "A", "A": "H", "D": "D"}[rev]
                    if lk in ("H", "D", "A"):
                        outcome = lk

                if outcome == "H":
                    standings[h_code]["pts"] += 3
                    standings[h_code]["w"] += 1
                    standings[a_code]["l"] += 1
                    h2h_log[h_code][a_code]["pts"] += 3
                elif outcome == "D":
                    standings[h_code]["pts"] += 1
                    standings[a_code]["pts"] += 1
                    standings[h_code]["d"] += 1
                    standings[a_code]["d"] += 1
                    h2h_log[h_code][a_code]["pts"] += 1
                    h2h_log[a_code][h_code]["pts"] += 1
                else:
                    standings[a_code]["pts"] += 3
                    standings[a_code]["w"] += 1
                    standings[h_code]["l"] += 1
                    h2h_log[a_code][h_code]["pts"] += 3

                if elo_recalc:
                    group_match_results.append((h_code, a_code, outcome))

        ranked = _rank_group(standings, h2h_log=h2h_log, elo_map=elo_map)
        group_results[grp_letter] = ranked

        for pos, (code, s) in enumerate(ranked):
            tracker[code]["group_pos"] = pos + 1
            tracker[code]["group_pts"] = s["pts"]
            tracker[code]["group_gf"] = s["gf"]
            tracker[code]["group_ga"] = s["ga"]

    sim_seed = (params or {}).get("sim_seed") if params else None
    best_thirds = _pick_best_thirds(group_results, elo_map=elo_map, n=8, sim_seed=sim_seed)
    qualified_thirds_map = {t[1]: t[0] for t in best_thirds}

    for grp_letter, ranked in group_results.items():
        if len(ranked) >= 1:
            tracker[ranked[0][0]]["r32"] = True
        if len(ranked) >= 2:
            tracker[ranked[1][0]]["r32"] = True
    for t in best_thirds:
        tracker[t[1]]["r32"] = True

    group_winners = {}
    group_runners = {}
    for grp_letter, ranked in group_results.items():
        group_winners[grp_letter] = ranked[0][0]
        group_runners[grp_letter] = ranked[1][0]

    third_assignments = _assign_thirds_to_slots(best_thirds)

    # Recalcul Elo post-poules (optionnel) : sert UNIQUEMENT à piloter les tours
    # à élimination directe. Les départages de poule ci-dessus restent fondés
    # sur l'Elo pré-tournoi (proxy ranking FIFA), inchangés.
    if elo_recalc:
        ko_elo = _update_elo_from_results(elo_map, group_match_results, k=recalc_k)
    else:
        ko_elo = elo_map

    # Verrouillage live des matchs KO : un vrai vainqueur connu écrase la sim.
    lko = locked_results.get("ko") if locked_results else None

    def _ko_winner(h_code, a_code):
        elo_h = ko_elo.get(h_code, 1500)
        elo_a = ko_elo.get(a_code, 1500)
        result, _, _ = simulate_knockout_match(elo_h, elo_a, h_code, a_code)
        winner = h_code if result == "H" else a_code
        if lko and h_code != "UNK" and a_code != "UNK":
            lw = lko.get(frozenset((h_code, a_code)))
            if lw in (h_code, a_code):
                winner = lw
        return winner

    bracket = {"r32": {}, "r16": [], "qf": [], "sf": [],
               "final": None, "bronze": None, "elo_after": {}}

    r32_results = {}
    for slot in R32_BRACKET:
        mn = slot["match"]
        h_type, h_grp = slot["home"]
        a_type, a_grp = slot["away"]

        if h_type == "1":
            h_code = group_winners[h_grp]
        elif h_type == "2":
            h_code = group_runners[h_grp]
        elif h_type == "3rd":
            h_code = third_assignments.get(mn, "UNK")
        else:
            h_code = group_winners.get(h_grp, "UNK")

        if a_type == "1":
            a_code = group_winners[a_grp]
        elif a_type == "2":
            a_code = group_runners[a_grp]
        elif a_type == "3rd":
            a_code = third_assignments.get(mn, "UNK")
        else:
            a_code = group_winners.get(a_grp, "UNK")

        if h_code is None:
            h_code = "UNK"
        if a_code is None:
            a_code = "UNK"

        tracker[h_code]["opponents"]["r32"] = a_code
        tracker[a_code]["opponents"]["r32"] = h_code

        winner = _ko_winner(h_code, a_code)
        r32_results[mn] = winner
        bracket["r32"][mn] = (h_code, a_code, winner)

    r16_winners = []
    for m1, m2 in R16_PAIRINGS:
        h_code = r32_results[m1]
        a_code = r32_results[m2]
        tracker[h_code]["r16"] = True
        tracker[a_code]["r16"] = True
        tracker[h_code]["opponents"]["r16"] = a_code
        tracker[a_code]["opponents"]["r16"] = h_code
        winner = _ko_winner(h_code, a_code)
        r16_winners.append(winner)
        bracket["r16"].append((h_code, a_code, winner))

    qf_winners = []
    for i, (m1, m2) in enumerate(QF_PAIRINGS):
        h_code = r16_winners[m1]
        a_code = r16_winners[m2]
        tracker[h_code]["qf"] = True
        tracker[a_code]["qf"] = True
        tracker[h_code]["opponents"]["qf"] = a_code
        tracker[a_code]["opponents"]["qf"] = h_code
        winner = _ko_winner(h_code, a_code)
        qf_winners.append(winner)
        bracket["qf"].append((h_code, a_code, winner))

    sf_winners = []
    sf_losers = []
    for m1, m2 in SF_PAIRINGS:
        h_code = qf_winners[m1]
        a_code = qf_winners[m2]
        tracker[h_code]["sf"] = True
        tracker[a_code]["sf"] = True
        tracker[h_code]["opponents"]["sf"] = a_code
        tracker[a_code]["opponents"]["sf"] = h_code
        winner = _ko_winner(h_code, a_code)
        loser = a_code if winner == h_code else h_code
        sf_winners.append(winner)
        sf_losers.append(loser)
        bracket["sf"].append((h_code, a_code, winner))

    if len(sf_losers) == 2:
        b_h = sf_losers[0]
        b_a = sf_losers[1]
        tracker[b_h]["opponents"]["bronze"] = b_a
        tracker[b_a]["opponents"]["bronze"] = b_h
        bronze = _ko_winner(b_h, b_a)
        tracker[bronze]["bronze"] = True
        bracket["bronze"] = (b_h, b_a, bronze)

    f_h = sf_winners[0]
    f_a = sf_winners[1]
    tracker[f_h]["final"] = True
    tracker[f_a]["final"] = True
    tracker[f_h]["opponents"]["final"] = f_a
    tracker[f_a]["opponents"]["final"] = f_h
    champion = _ko_winner(f_h, f_a)
    runner_up = f_a if champion == f_h else f_h
    tracker[champion]["winner"] = True
    tracker[runner_up]["runner_up"] = True
    bracket["final"] = (f_h, f_a, champion)

    if return_bracket:
        for code in elo_map:
            bracket["elo_after"][code] = ko_elo.get(code, elo_map.get(code, 1500))
        return dict(tracker), bracket
    return dict(tracker)


def run_simulation(n_sims=10000, params=None):
    elo_map = _build_elo_map()

    agg = defaultdict(lambda: {
        "group_pts_total": 0,
        "group_gf_total": 0.0,
        "group_ga_total": 0.0,
        "group_pos_counts": defaultdict(int),
        "group_pts_counts": defaultdict(int),
        "group_goals_counts": defaultdict(int),
        "r32": 0, "r16": 0, "qf": 0, "sf": 0, "final": 0, "winner": 0,
        "runner_up": 0, "bronze": 0,
        "opponents": {"r32": defaultdict(int), "r16": defaultdict(int),
                       "qf": defaultdict(int), "sf": defaultdict(int),
                       "final": defaultdict(int), "bronze": defaultdict(int)},
    })

    for _ in range(n_sims):
        result = simulate_tournament(elo_map, params)
        for code, data in result.items():
            a = agg[code]
            a["group_pts_total"] += data["group_pts"]
            a["group_gf_total"] += data.get("group_gf", 0)
            a["group_ga_total"] += data.get("group_ga", 0)
            a["group_pos_counts"][data["group_pos"]] += 1
            a["group_pts_counts"][data["group_pts"]] += 1
            a["group_goals_counts"][data.get("group_goals_scored", 0)] += 1
            for stage in ["r32", "r16", "qf", "sf", "final", "winner", "runner_up", "bronze"]:
                if data.get(stage):
                    a[stage] += 1
            for stage, opp_code in data.get("opponents", {}).items():
                if opp_code and opp_code != "UNK":
                    if stage not in a["opponents"]:
                        a["opponents"][stage] = defaultdict(int)
                    a["opponents"][stage][opp_code] += 1

    output = []
    for code, a in agg.items():
        nation = get_nation_by_code(code)
        if not nation:
            continue
        grp = None
        for g, teams in WC2026_GROUPS.items():
            if code in teams:
                grp = g
                break

        opp_pcts = {}
        for stage in ["r32", "r16", "qf", "sf", "final", "bronze"]:
            stage_opps = {}
            for opp, cnt in a["opponents"].get(stage, {}).items():
                stage_opps[opp] = cnt / n_sims * 100
            opp_pcts[stage] = stage_opps

        elim_group = (1 - a["r32"] / n_sims) * 100
        elim_r32 = (a["r32"] - a["r16"]) / n_sims * 100
        elim_r16 = (a["r16"] - a["qf"]) / n_sims * 100
        elim_qf = (a["qf"] - a["sf"]) / n_sims * 100
        elim_sf = (a["sf"] - a["final"]) / n_sims * 100
        elim_final = (a["final"] - a["winner"]) / n_sims * 100

        p_winner = a["winner"] / n_sims * 100
        p_runner_up = a["runner_up"] / n_sims * 100
        p_bronze = a["bronze"] / n_sims * 100
        p_podium = p_winner + p_runner_up + p_bronze

        output.append({
            "code": code,
            "name": nation["name"],
            "fr": nation["fr"],
            "group": grp,
            "elo": elo_map.get(code, 1500),
            "avg_pts": a["group_pts_total"] / n_sims,
            "avg_gf": a["group_gf_total"] / n_sims,
            "avg_ga": a["group_ga_total"] / n_sims,
            "avg_gd": (a["group_gf_total"] - a["group_ga_total"]) / n_sims,
            "p_1st": a["group_pos_counts"].get(1, 0) / n_sims * 100,
            "p_2nd": a["group_pos_counts"].get(2, 0) / n_sims * 100,
            "p_3rd": a["group_pos_counts"].get(3, 0) / n_sims * 100,
            "p_4th": a["group_pos_counts"].get(4, 0) / n_sims * 100,
            "pts_dist": {p: a["group_pts_counts"].get(p, 0) / n_sims * 100
                         for p in (0, 1, 2, 3, 4, 5, 6, 7, 9)},
            "goals_dist": _bucket_goals(a["group_goals_counts"], n_sims),
            "p_r32": a["r32"] / n_sims * 100,
            "p_r16": a["r16"] / n_sims * 100,
            "p_qf": a["qf"] / n_sims * 100,
            "p_sf": a["sf"] / n_sims * 100,
            "p_final": a["final"] / n_sims * 100,
            "p_winner": p_winner,
            "p_runner_up": p_runner_up,
            "p_bronze": p_bronze,
            "p_podium": p_podium,
            "opponents": opp_pcts,
            "elim_group": elim_group,
            "elim_r32": elim_r32,
            "elim_r16": elim_r16,
            "elim_qf": elim_qf,
            "elim_sf": elim_sf,
            "elim_final": elim_final,
        })

    output.sort(key=lambda x: -x["p_winner"])
    return output


def get_group_predictions(elo_map=None, params=None):
    if elo_map is None:
        elo_map = _build_elo_map()
    results = {}
    for grp_letter, teams in WC2026_GROUPS.items():
        matches = []
        for md_name, pairings in GROUP_MATCHES.items():
            for i_h, i_a in pairings:
                h_code = teams[i_h]
                a_code = teams[i_a]
                elo_h = elo_map.get(h_code, 1500)
                elo_a = elo_map.get(a_code, 1500)
                delta = elo_h - elo_a
                ea = (elo_h + elo_a) / 2
                ph, pd, pa = sigmoid_v8_1x2(delta, elo_avg=ea, phase="G")
                nation_h = get_nation_by_code(h_code)
                nation_a = get_nation_by_code(a_code)
                matches.append({
                    "md": md_name,
                    "home_code": h_code,
                    "away_code": a_code,
                    "home_fr": nation_h["fr"] if nation_h else h_code,
                    "away_fr": nation_a["fr"] if nation_a else a_code,
                    "elo_h": elo_h,
                    "elo_a": elo_a,
                    "delta": delta,
                    "p_home": ph * 100,
                    "p_draw": pd * 100,
                    "p_away": pa * 100,
                    "odds_home": 1 / ph if ph > 0.01 else 99,
                    "odds_draw": 1 / pd if pd > 0.01 else 99,
                    "odds_away": 1 / pa if pa > 0.01 else 99,
                })
        results[grp_letter] = matches
    return results


def _modal(counter):
    """Retourne la clé la plus fréquente d'un dict {clé: compte}."""
    if not counter:
        return "UNK"
    return max(counter.items(), key=lambda kv: kv[1])[0]


def simulate_bracket_mc(n_sims=2000, params=None, elo_recalc=True, recalc_k=40.0):
    """Bracket Monte-Carlo COHÉRENT avec la simulation globale.

    Méthode (arbre CONNECTÉ) :
      - Les 32 emplacements du 1er tour à élimination directe (R32) sont remplis
        par l'occupant le plus fréquent (modal) sur `n_sims` simulations.
      - Les tours suivants (8es → finale) ne sont PAS reconstruits par occupant
        modal indépendant (cela donnerait un arbre disjoint : une équipe affichée
        en finale sans être affichée gagnante de sa demie). On fait AVANCER le
        vainqueur projeté de chaque duel reconstitué, ce qui garantit un arbre
        cohérent et lisible.
      - La cote de qualification de chaque duel est dérivée des FRÉQUENCES
        EMPIRIQUES de la même simulation (P(A se qualifie | A affronte B)
        observée), avec repli analytique (Sigmoid V8 phase K sur l'Elo
        post-poules moyen) quand l'appariement est trop rare pour une estimation
        fiable.

    Si `elo_recalc=True`, l'Elo de chaque nation est recalculé après le 1er tour
    À L'INTÉRIEUR de chaque simulation (MAJ logistique, facteur K `recalc_k`, sur
    les résultats de poule de cette simulation) ; ce sont ces Elo post-poules qui
    pilotent les tours à élimination directe.

    `params` accepte aussi `market_1x2`, `expected_scores` et `locked_results`
    (résultats réels figés) comme `simulate_tournament`.

    Retourne un dict prêt pour l'affichage : structure du bracket par tour,
    cotes par duel (source "mc" ou "elo"), et Elo moyen avant/après 1er tour.
    """
    elo_map = _build_elo_map()
    sim_params = dict(params or {})
    sim_params["elo_recalc"] = elo_recalc
    sim_params["recalc_k"] = recalc_k
    sim_params["_return_bracket"] = True

    stages = ("r32", "r16", "qf", "sf", "final", "bronze")
    occ_home = defaultdict(lambda: defaultdict(int))
    occ_away = defaultdict(lambda: defaultdict(int))
    h2h = {st: defaultdict(lambda: defaultdict(int)) for st in stages}
    elo_after_sum = defaultdict(float)

    for _ in range(n_sims):
        _, br = simulate_tournament(elo_map, sim_params)
        # R32 : occupants modaux par emplacement (base de l'arbre).
        for mn, (h, a, w) in br["r32"].items():
            occ_home[("r32", mn)][h] += 1
            occ_away[("r32", mn)][a] += 1
            if h != "UNK" and a != "UNK" and h != a:
                h2h["r32"][frozenset((h, a))][w] += 1
        # Tours suivants : on n'a besoin que des fréquences H2H empiriques par
        # paire (les occupants sont déterminés par les vainqueurs des duels
        # reconstitués pour garder un arbre CONNECTÉ — voir docstring).
        for st in ("r16", "qf", "sf"):
            for (h, a, w) in br[st]:
                if h != "UNK" and a != "UNK" and h != a:
                    h2h[st][frozenset((h, a))][w] += 1
        for st in ("final", "bronze"):
            tup = br[st]
            if tup:
                h, a, w = tup
                if h != "UNK" and a != "UNK" and h != a:
                    h2h[st][frozenset((h, a))][w] += 1
        for code, e in br["elo_after"].items():
            elo_after_sum[code] += e

    mean_elo_after = {c: elo_after_sum[c] / n_sims for c in elo_after_sum} if n_sims else {}
    min_pair = max(20, int(0.01 * n_sims))

    def _tie(stage, h, a):
        rec = h2h[stage].get(frozenset((h, a))) if (h != a and h != "UNK" and a != "UNK") else None
        if rec:
            wh = rec.get(h, 0)
            wa = rec.get(a, 0)
            tot = wh + wa
            if tot >= min_pair:
                ph = wh / tot
                return {"home": h, "away": a, "ph": ph, "pa": 1.0 - ph,
                        "winner": h if ph >= 0.5 else a, "src": "mc", "samples": tot}
        eh = mean_elo_after.get(h, elo_map.get(h, 1500))
        ea = mean_elo_after.get(a, elo_map.get(a, 1500))
        p_h, p_dr, p_a = sigmoid_v8_1x2(eh - ea, elo_avg=(eh + ea) / 2.0, phase="K")
        denom = p_h + p_a
        ph = (p_h + p_dr * (p_h / denom)) if denom > 0 else 0.5
        return {"home": h, "away": a, "ph": ph, "pa": 1.0 - ph,
                "winner": h if ph >= 0.5 else a, "src": "elo", "samples": 0}

    r32 = {}
    for slot in R32_BRACKET:
        mn = slot["match"]
        r32[mn] = _tie("r32", _modal(occ_home[("r32", mn)]), _modal(occ_away[("r32", mn)]))

    r16 = [_tie("r16", r32[m1]["winner"], r32[m2]["winner"]) for (m1, m2) in R16_PAIRINGS]
    qf = [_tie("qf", r16[i1]["winner"], r16[i2]["winner"]) for (i1, i2) in QF_PAIRINGS]
    sf = [_tie("sf", qf[i1]["winner"], qf[i2]["winner"]) for (i1, i2) in SF_PAIRINGS]
    final = _tie("final", sf[0]["winner"], sf[1]["winner"])

    def _loser(m):
        return m["away"] if m["winner"] == m["home"] else m["home"]

    bronze = _tie("bronze", _loser(sf[0]), _loser(sf[1]))

    return {
        "r32": r32,
        "r16": r16,
        "qf": qf,
        "sf": sf,
        "final": final,
        "bronze": bronze,
        "elo_before": {c: elo_map.get(c, 1500) for c in elo_map},
        "elo_after": mean_elo_after,
        "n_sims": n_sims,
        "recalc_k": recalc_k,
        "elo_recalc": elo_recalc,
    }
