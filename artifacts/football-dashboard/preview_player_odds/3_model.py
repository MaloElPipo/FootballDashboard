"""
Étapes C+D — Moteur de distribution xG team → joueur + pricing Poisson.
Prend des stats agrégées avant un match donné (leave-one-out temporel).

Fonctions principales:
  - aggregate_player_pool(stats_until_date) -> dict[player_id] -> profile
  - distribute_team_xg(xg_team, lineup, pool) -> dict[player_id] -> xG attendu
  - poisson_anytime(lambda_) -> proba >= 1 occurrence
"""
import math
from collections import Counter, defaultdict
from datetime import datetime


# Hyperparamètres calibrables
MINUTES_DEFAULT_NO_LINEUP = 90.0   # tous les joueurs reçoivent 90 min tant que la compo n'est pas confirmée
MINUTES_FLOOR_WHEN_STARTER = 80.0  # si un titulaire confirmé a avg_mins < 60 → on force 80
MINUTES_FLOOR_THRESHOLD = 60.0     # seuil sous lequel on applique le floor
MINUTES_STARTER_DEFAULT = 78.0     # backstop si avg_mins inconnu
MINUTES_SUB_DEFAULT = 25.0         # remplaçant confirmé
SHRINKAGE_K = 8.0                  # nb "matchs prior" pour shrinkage bayésien

# === Carrière (T003) ========================================================
# Confidence ratio: pondération du signal carrière (Understat archive 4 saisons)
# vs saison courante shrunken. cr=1 quand career_minutes >= CAREER_FULL_TRUST_MINUTES.
CAREER_FULL_TRUST_MINUTES = 15000.0  # ~4.5 saisons pleines de titulaire
CAREER_MIN_USABLE_MINUTES = 1500.0   # < 0.5 saison → on ignore le signal carrière

# === Calibration anti-Poisson (méthode "Buteurs Maison 4.1") ================
# La formule Poisson p = 1 - exp(-x) sur-estime systématiquement la proba marquer
# pour les joueurs à faible xG (= cotes brutes hautes). Calibration empirique :
#     cote_finale = cote_brute × (1 - min((cote_brute - 1)/100, 0.75))
# Effets : cotes ~2.0 → ~1% ajusté ; cotes ~10 → −9% ; cotes >75 → −75% (cap).
ANTI_POISSON_SHRINK_CAP = 0.75     # plafond du shrink (compresse les outsiders extrêmes)
ANTI_POISSON_SHRINK_DIVISOR = 100.0


def apply_anti_poisson_calibration(odd_brut: float | None) -> float | None:
    """Compression anti-overestimation des cotes scorer/assist issues de Poisson.

    Pour cote brute B, retourne B × (1 - min((B-1)/100, 0.75)).
    Reproduit la formule de l'Excel "Buteurs Maison 4.1" (HomeTeam!I2)."""
    if odd_brut is None:
        return None
    try:
        b = float(odd_brut)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(b) or b <= 1.0:
        return b
    shrink = min((b - 1.0) / ANTI_POISSON_SHRINK_DIVISOR, ANTI_POISSON_SHRINK_CAP)
    if shrink < 0:
        shrink = 0.0
    return b * (1.0 - shrink)

# === PRIORS BAYÉSIENS PAR POSTE (xG/90 et xA/90) ============================
# Lus dans l'ordre : specific_position (ST, CAM, RB...), puis position générique
# (F/M/D/G), puis fallback ligue.
# Calibration : moyennes empiriques Top 5 européens (xG/90 par rôle).
POSITION_PRIORS_XG90: dict[str, float] = {
    # Spécifiques fins
    "GK": 0.00,
    "CB": 0.05,
    "LB": 0.08, "RB": 0.08, "WB": 0.08, "LWB": 0.08, "RWB": 0.08,
    "CDM": 0.07, "DM": 0.07,
    "CM": 0.10, "MC": 0.10,
    "LM": 0.18, "RM": 0.18,
    "CAM": 0.20, "AM": 0.20,
    "LW": 0.30, "RW": 0.30,
    "SS": 0.35, "CF": 0.40,
    "ST": 0.45,
    # Specific_position BSD (codes 3 lettres, plus larges) — moyennes par catégorie
    "DEF": 0.06,
    "MID": 0.13,
    "FWD": 0.35,
    # Génériques (fallback BSD `position` si specific_position absente)
    "G": 0.00,
    "D": 0.06,
    "M": 0.13,
    "F": 0.35,
}

POSITION_PRIORS_XA90: dict[str, float] = {
    "GK": 0.01,
    "CB": 0.03,
    "LB": 0.07, "RB": 0.07, "WB": 0.07, "LWB": 0.07, "RWB": 0.07,
    "CDM": 0.07, "DM": 0.07,
    "CM": 0.10, "MC": 0.10,
    "LM": 0.15, "RM": 0.15,
    "CAM": 0.18, "AM": 0.18,
    "LW": 0.20, "RW": 0.20,
    "SS": 0.15, "CF": 0.12,
    "ST": 0.10,
    "DEF": 0.05,
    "MID": 0.11,
    "FWD": 0.13,
    "G": 0.01,
    "D": 0.05,
    "M": 0.11,
    "F": 0.13,
}

# Fallback ligue si aucune position connue
LEAGUE_PRIOR_XG90_OUTFIELD = 0.10
LEAGUE_PRIOR_XA90_OUTFIELD = 0.08


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


def _normalize_position(pos: str | None) -> str | None:
    """Normalise un code position (uppercase, retire espaces, '/' premier élément)."""
    if not pos:
        return None
    p = str(pos).upper().strip().split("/")[0].strip()
    return p or None


def position_prior(player: dict, fallback_xg: float = LEAGUE_PRIOR_XG90_OUTFIELD,
                   fallback_xa: float = LEAGUE_PRIOR_XA90_OUTFIELD) -> tuple[float, float]:
    """Retourne (prior_xg_p90, prior_xa_p90) pour un joueur.

    Lecture en cascade :
      1) `specific_position` (ST, CAM, RB, etc.)
      2) `position` générique (F/M/D/G)
      3) heuristique `is_gk`
      4) fallback ligue (paramètres)
    """
    if not isinstance(player, dict):
        return fallback_xg, fallback_xa

    spec = _normalize_position(player.get("specific_position"))
    if spec and spec in POSITION_PRIORS_XG90:
        return POSITION_PRIORS_XG90[spec], POSITION_PRIORS_XA90[spec]

    gen = _normalize_position(player.get("position"))
    if gen and gen in POSITION_PRIORS_XG90:
        return POSITION_PRIORS_XG90[gen], POSITION_PRIORS_XA90[gen]

    if player.get("is_gk"):
        return POSITION_PRIORS_XG90["GK"], POSITION_PRIORS_XA90["GK"]

    return fallback_xg, fallback_xa


def aggregate_player_pool(player_stats_by_event, matches_by_id, until_date=None,
                          prev_player_stats_by_event=None, prev_matches_by_id=None,
                          alpha_prev=0.5):
    """Calcule pour chaque joueur ses stats roulées (saison N).

    Si `prev_player_stats_by_event` est fourni, pondère les stats de la saison N-1
    par `alpha_prev` (0.5-0.7 selon la transition de championnat) et les agrège
    avec les stats N. Le poids effectif d'un match N-1 = 1 × alpha_prev(pid).

    `alpha_prev` peut être :
      - un float (poids uniforme appliqué à tous les joueurs N-1) ;
      - un Callable[[int], float] (alpha par player_id, ex. 0.7 si même équipe
        N et N-1, 0.6 si transfert intra-Top5, 0.5 sinon).

    Retourne dict[player_id] -> profil avec : name, team_id, is_gk,
    minutes_total, matches_played, starts, xg_total, xa_total, shots_total,
    key_pass_total, goals_total, assists_total, xg_per_90, xa_per_90,
    shots_per_90, avg_mins_when_starter, position, specific_position,
    matches_played_curr, matches_played_prev.
    """
    agg = defaultdict(lambda: {
        "name": None, "team_id": None, "is_gk": False,
        "minutes_total": 0.0, "matches_played": 0, "starts": 0,
        "xg_total": 0.0, "xa_total": 0.0, "shots_total": 0.0, "key_pass_total": 0.0,
        "shots_on_target_total": 0.0,
        "goals_total": 0.0, "assists_total": 0.0,
        "starter_minutes_sum": 0.0,
        "matches_played_curr": 0, "matches_played_prev": 0,
        "_pos_counts": Counter(), "_spec_pos_counts": Counter(),
    })

    def _ingest(stats_by_event, matches_lookup, weight_fn, is_current: bool):
        """`weight_fn` : callable(pid)→float renvoyant le poids pour ce joueur."""
        if not stats_by_event:
            return
        for eid_str, ev_block in stats_by_event.items():
            try:
                eid_int = int(eid_str)
            except (TypeError, ValueError):
                eid_int = eid_str
            ev = matches_lookup.get(str(eid_str)) or matches_lookup.get(eid_int)
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
                    continue

                weight = float(weight_fn(pid))
                if weight <= 0:
                    continue

                a = agg[pid]
                a["name"] = a["name"] or pname
                tid = s.get("team")
                if isinstance(tid, dict): tid = tid.get("id")
                if is_current:  # team_id : on garde celui de la saison courante uniquement
                    a["team_id"] = a["team_id"] or tid
                else:
                    # Mémorise team_id N-1 (pour calcul alpha post-hoc)
                    a.setdefault("team_id_prev", tid)
                a["is_gk"] = a["is_gk"] or is_goalkeeper(s)

                a["minutes_total"] += mins * weight
                a["matches_played"] += 1 * weight
                if mins >= 60:
                    a["starts"] += 1 * weight
                    a["starter_minutes_sum"] += mins * weight
                a["xg_total"] += _safe_float(s.get("expected_goals")) * weight
                a["xa_total"] += _safe_float(s.get("expected_assists")) * weight
                a["shots_total"] += _safe_float(s.get("total_shots")) * weight
                a["shots_on_target_total"] += _safe_float(s.get("shots_on_target")) * weight
                a["key_pass_total"] += _safe_float(s.get("key_pass")) * weight
                a["goals_total"] += _safe_float(s.get("goals")) * weight
                a["assists_total"] += _safe_float(s.get("goal_assist")) * weight

                if is_current:
                    a["matches_played_curr"] += 1
                else:
                    a["matches_played_prev"] += 1

                pos_norm = _normalize_position(s.get("position"))
                if pos_norm:
                    a["_pos_counts"][pos_norm] += 1

    _ingest(player_stats_by_event, matches_by_id,
            weight_fn=lambda pid: 1.0, is_current=True)
    if prev_player_stats_by_event is not None:
        if callable(alpha_prev):
            wfn = alpha_prev
        else:
            _alpha = float(alpha_prev)
            wfn = lambda pid, _a=_alpha: _a
        _ingest(prev_player_stats_by_event, prev_matches_by_id or {},
                weight_fn=wfn, is_current=False)

    # Calcul derived stats + position majoritaire
    for pid, a in agg.items():
        if a["minutes_total"] > 0:
            factor = 90.0 / a["minutes_total"]
            a["xg_per_90"] = a["xg_total"] * factor
            a["xa_per_90"] = a["xa_total"] * factor
            a["shots_per_90"] = a["shots_total"] * factor
            a["shots_on_target_per_90"] = a["shots_on_target_total"] * factor
            # T007 — passage moteur 100% buts (Excel "Buteurs Maison 4.1") :
            # on expose aussi goals_per_90 / assists_per_90 saison courante,
            # qui remplacent xg_per_90 dans le blend de career_blended_xg_per_90.
            a["goals_per_90"] = a["goals_total"] * factor
            a["assists_per_90"] = a["assists_total"] * factor
        else:
            a["xg_per_90"] = a["xa_per_90"] = a["shots_per_90"] = 0.0
            a["shots_on_target_per_90"] = 0.0
            a["goals_per_90"] = a["assists_per_90"] = 0.0
        a["avg_mins_when_starter"] = (
            a["starter_minutes_sum"] / a["starts"] if a["starts"] > 0 else MINUTES_STARTER_DEFAULT
        )
        # Position majoritaire observée : mode des positions vues dans les player-stats
        pos_counts = a.pop("_pos_counts", Counter())
        a.pop("_spec_pos_counts", None)
        if pos_counts:
            a["position_observed"] = pos_counts.most_common(1)[0][0]
            a["position_history"] = dict(pos_counts.most_common(5))
        # arrondi des compteurs flottants
        a["matches_played"] = round(a["matches_played"], 2)
        a["starts"] = round(a["starts"], 2)
    return dict(agg)


def shrunk_per90(player, metric, league_prior, k=SHRINKAGE_K):
    """Shrinkage bayésien: combine observation joueur avec prior position-aware.

    Poids de l'observation = `minutes_total / 90` (nb d'équivalents-matchs
    complets) plutôt que `matches_played` brut. Évite que des cameos
    (ex. 3 entrées de 10 min avec un tir chacun) ne pèsent autant que 3
    matchs complets — bug observé sur les jeunes type Trey Nyoni / Rio
    Ngumoha qui sortaient avec g90 ≈ 0.5 (= prior FWD) au lieu de g90
    ≈ 0.13 (= prior MID shrunken).

    Fallback `matches_played` si `minutes_total` absent (rétro-compat).
    `league_prior` est utilisé tel quel — l'appelant doit le calculer via
    `position_prior(player)` pour bénéficier du prior par poste.
    """
    minutes = float(player.get("minutes_total", 0) or 0)
    if minutes > 0:
        weight = minutes / 90.0
    else:
        # Rétro-compat : si pas de minutes_total, retombe sur matches
        weight = float(player.get("matches_played", 0) or 0)
    obs = player.get(metric, 0.0)
    if weight <= 0:
        return league_prior
    return (weight * obs + k * league_prior) / (weight + k)


def career_confidence_ratio(player: dict) -> float:
    """Retourne cr = min(career_minutes / CAREER_FULL_TRUST_MINUTES, 1.0).

    Renvoie 0.0 si player n'a pas (assez de) minutes carrière.
    """
    if not isinstance(player, dict):
        return 0.0
    cm = float(player.get("career_minutes", 0.0) or 0.0)
    if cm < CAREER_MIN_USABLE_MINUTES:
        return 0.0
    return min(cm / CAREER_FULL_TRUST_MINUTES, 1.0)


def career_g90(player: dict) -> float | None:
    """Buts par 90 carrière (Understat archive + BSD increment courant).
    Renvoie None si pas assez de minutes carrière (< CAREER_MIN_USABLE_MINUTES)."""
    if not isinstance(player, dict):
        return None
    cm = float(player.get("career_minutes", 0.0) or 0.0)
    if cm < CAREER_MIN_USABLE_MINUTES:
        return None
    cg = float(player.get("career_goals", 0.0) or 0.0)
    return cg * 90.0 / cm


def career_blended_xg_per_90(player: dict, prior_xg: float) -> tuple[float, float, bool]:
    """Calcule le g90 (buts par 90) utilisé pour le pricing buteur.

    T007 — Moteur 100% buts (Excel "Buteurs Maison 4.1") : on n'utilise plus
    aucun signal xG ni en carrière ni en saison courante. Tout est buts marqués.

    Formule :
      cr = min(career_minutes / 15000, 1.0)
      g90_career   = career_goals × 90 / career_minutes
      g90_curr_shrunk = (poids_min × goals_per_90 + K × prior_pos) / (poids_min + K)
        où poids_min = minutes_total / 90 (équivalents-matchs complets)
      g90_used = cr × g90_career + (1 - cr) × g90_curr_shrunk

    Si career_minutes < CAREER_MIN_USABLE_MINUTES → cr=0, fallback sur le seul
    signal saison courante (déjà 100% buts).

    Le `prior_xg` reçu en argument reste un prior position-aware calibré sur
    population xG/90 — ok comme prior bayésien car en moyenne population
    goals_per_90 ≈ xg_per_90 (xG est non-biaisé). Les vrais buteurs qui
    sur-performent (Salah, Watkins) sont captés via `g90_career` (buts réels).

    Returns: (g90_used, confidence_ratio, career_used)
    """
    p = player or {}
    # Calcule goals_per_90 à la volée si absent (rétro-compat avec pools
    # existants qui n'ont pas le champ). Goals_total et minutes_total sont
    # toujours présents.
    if "goals_per_90" not in p:
        mins = float(p.get("minutes_total", 0) or 0)
        goals = float(p.get("goals_total", 0) or 0)
        p = {**p, "goals_per_90": (goals * 90.0 / mins) if mins > 0 else 0.0}
    g90_curr_shrunk = shrunk_per90(p, "goals_per_90", prior_xg)
    cr = career_confidence_ratio(p)
    if cr <= 0.0:
        return g90_curr_shrunk, 0.0, False
    g90_carr = career_g90(player or {})
    if g90_carr is None:
        return g90_curr_shrunk, 0.0, False
    g90_used = cr * g90_carr + (1.0 - cr) * g90_curr_shrunk
    return g90_used, cr, True


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


def _resolve_minutes(lp: dict, player: dict | None, lineup_confirmed: bool) -> float:
    """Détermine les minutes attendues d'un joueur selon que la compo est confirmée.

    - Compo confirmée + titulaire → avg_mins_when_starter, floor 80 si <60
    - Compo confirmée + remplaçant → MINUTES_SUB_DEFAULT
    - Compo NON confirmée :
        - le caller fournit une présomption (top-11 par minutes_total) via
          `is_starter` du fallback. On l'utilise pour assigner :
            * is_starter=True → avg_mins_when_starter (ou STARTER_DEFAULT)
            * is_starter=False → MINUTES_SUB_DEFAULT
        - Avant : tout le monde recevait 90 → DILUTION massive (17 joueurs ×
          90 = 1530 player-min vs réalité 11×85 + 6×15 = 1025). Conséquence :
          la part xG des stars (Salah, Haaland) tombait à ~15% au lieu de ~30%.
    """
    is_starter = lp.get("is_starter")
    if not is_starter:
        # Compo confirmée OU fallback : un non-titulaire reste un sub
        return MINUTES_SUB_DEFAULT

    avg = (player or {}).get("avg_mins_when_starter") or MINUTES_STARTER_DEFAULT
    if avg < MINUTES_FLOOR_THRESHOLD:
        return MINUTES_FLOOR_WHEN_STARTER
    return float(avg)


def distribute_xg_to_players(xg_home, xg_away, home_team_id, away_team_id, lineup_players, pool,
                             lineup_confirmed: bool | dict = False):
    """
    Pour chaque joueur de la lineup, calcule son xG_attendu et xA_attendu.
    Normalisation: somme des xG joueurs d'une équipe = xG_team.

    Args:
        lineup_confirmed: si True, applique avg_mins_when_starter pour titulaires
            (floor 80) et MINUTES_SUB_DEFAULT pour subs. Si False, force 90 partout.
            Peut aussi être un dict {"home": bool, "away": bool} pour piloter chaque
            côté indépendamment (utile quand BSD n'a publié qu'une seule des 2 compos).

    Returns: dict[player_id] -> {
        'team_side', 'name', 'minutes_expected',
        'xg_raw', 'xa_raw', 'xg_calibrated', 'xa_calibrated',
        'p_scorer', 'p_assist', 'odd_scorer', 'odd_assist',
        'is_starter', 'is_gk', 'position_used', 'xg_per_90_used', 'xa_per_90_used'
    }
    """
    result = {}

    # Normalise lineup_confirmed → dict par side
    if isinstance(lineup_confirmed, dict):
        confirmed_by_side = {"home": bool(lineup_confirmed.get("home", False)),
                              "away": bool(lineup_confirmed.get("away", False))}
    else:
        b = bool(lineup_confirmed)
        confirmed_by_side = {"home": b, "away": b}

    for side, team_xg, team_id in (("home", xg_home, home_team_id), ("away", xg_away, away_team_id)):
        team_lineup = [lp for lp in lineup_players if lp["side"] == side]
        if not team_lineup or team_xg is None:
            continue
        side_confirmed = confirmed_by_side[side]

        # 1. xG/xA bruts par joueur (avec shrinkage position-aware + minutes attendues)
        # `raw_*_per_player`            = avec minutes ACTUELLES (titu→85, sub→25)
        # `raw_*_starter_per_player`    = "et si ce joueur jouait à mins_starter" (shadow)
        # Le shadow sert à exposer fair_odd_scorer_if_starter pour les subs présumés.
        raw_xg_per_player = {}
        raw_xa_per_player = {}
        raw_xg_starter_per_player = {}
        raw_xa_starter_per_player = {}
        # Pour la conversion 90' théorique des cotes (garantie buteur FR : la cote
        # bookmaker valide même si le joueur entre en cours de match → on price
        # à 90' théorique pour rester comparable). On garde mins_expected/mins_starter
        # pour la normalisation de team_xg, mais on remonte une proba "P(scorer | 90')".
        mins_exp_by_pid: dict[int, float] = {}
        mins_starter_shadow_by_pid: dict[int, float] = {}
        for lp in team_lineup:
            pid = lp["player_id"]
            if pid is None:
                continue
            player = pool.get(pid)

            # Prior position-aware. Cascade :
            #   1) lp.position si code FIN (ST/RW/AM/CB/...) — lineup BSD officielle.
            #   2) player.manual_position (T012 — override Excel "Buteurs Maison")
            #      prime sur lp.position quand celle-ci est grossière (MID/DEF/FWD).
            #   3) lp.position grossière si pas d'override Excel.
            #   4) sinon player brut (specific_position/position via position_prior).
            COARSE = {"MID", "DEF", "FWD", "GK", "M", "D", "F", "G"}
            lp_pos = lp.get("position")
            lp_pos_norm = (lp_pos or "").upper().strip() if lp_pos else ""
            manual_pos = (player or {}).get("manual_position")
            if lp_pos_norm and lp_pos_norm not in COARSE:
                pos_for_prior = lp_pos
                prior_player = {"specific_position": lp_pos, "position": lp_pos,
                                "is_gk": (player or {}).get("is_gk", False)}
            elif manual_pos:
                pos_for_prior = manual_pos
                prior_player = {"specific_position": manual_pos, "position": manual_pos,
                                "is_gk": (player or {}).get("is_gk", False)}
            elif lp_pos:
                pos_for_prior = lp_pos
                prior_player = {"specific_position": lp_pos, "position": lp_pos,
                                "is_gk": (player or {}).get("is_gk", False)}
            else:
                pos_for_prior = None
                prior_player = player or {}
            prior_xg, prior_xa = position_prior(prior_player)

            if player is None:
                xg_p90 = prior_xg
                xa_p90 = prior_xa
                is_gk = (pos_for_prior or "").upper() in ("GK", "G")
                cr = 0.0
                career_used = False
            else:
                is_gk = player.get("is_gk", False)
                # T003 — xG: blend carrière (Understat) ↔ saison courante shrunken.
                # cr = min(career_minutes/15000, 1) ; quand 0 → comportement legacy.
                xg_p90, cr, career_used = career_blended_xg_per_90(player, prior_xg)
                # xA reste sur le shrinkage actuel (pas de signal carrière passeurs)
                xa_p90 = shrunk_per90(player, "xa_per_90", prior_xa)

            # T011 — joueur blessé / suspendu réinjecté pour affichage UI :
            # mins_exp = mins_starter_shadow (≈ 85) pour permettre à
            # `_recalculate_shares` de produire des cotes valables si l'user
            # le réactive manuellement (rumeur "rétabli"), MAIS raw_xg/xa = 0
            # → exclu de la normalisation team xG (pas de dilution des autres).
            is_unav = bool(lp.get("is_unavailable"))

            # Minutes "comme si titulaire" (sert au shadow odds des subs présumés
            # ET au mins_expected des blessés réinjectés T011).
            mins_starter_shadow = ((player or {}).get("avg_mins_when_starter")
                                   or MINUTES_STARTER_DEFAULT)
            if mins_starter_shadow < MINUTES_FLOOR_THRESHOLD:
                mins_starter_shadow = MINUTES_FLOOR_WHEN_STARTER

            if is_unav:
                mins_exp = mins_starter_shadow
                raw_xg = 0.0
                raw_xa = 0.0
            else:
                mins_exp = _resolve_minutes(lp, player, side_confirmed)
                raw_xg = xg_p90 * (mins_exp / 90.0)
                raw_xa = xa_p90 * (mins_exp / 90.0)

            raw_xg_per_player[pid] = raw_xg
            raw_xa_per_player[pid] = raw_xa
            raw_xg_starter_per_player[pid] = xg_p90 * (mins_starter_shadow / 90.0)
            raw_xa_starter_per_player[pid] = xa_p90 * (mins_starter_shadow / 90.0)
            mins_exp_by_pid[pid] = mins_exp
            mins_starter_shadow_by_pid[pid] = mins_starter_shadow

            # T010 — expected shots & expected shots on target (descriptif).
            # On utilise minutes_expected (et non 90' théorique) car ce sont des
            # stats descriptives "à quoi s'attendre dans CE match", pas des
            # cotes de pari. Pour un sub à 25min, son xShots reflète bien sa
            # contribution attendue au volume de tirs sur ses minutes prévues.
            shots_p90 = (player or {}).get("shots_per_90") or 0.0
            sot_p90 = (player or {}).get("shots_on_target_per_90") or 0.0
            expected_shots = float(shots_p90) * mins_exp / 90.0
            expected_shots_on_target = float(sot_p90) * mins_exp / 90.0

            # Note (T007) : `xg_per_90_used` ci-dessous porte sémantiquement un
            # **g90 buts** (pas un xG/90) depuis la bascule moteur 100% buts.
            # Nom conservé pour rétro-compat avec le forward_log et l'UI.
            result[pid] = {
                "team_side": side, "team_id": team_id,
                "name": (player or {}).get("name", f"id={pid}"),
                "is_starter": lp["is_starter"], "is_gk": is_gk,
                "is_unavailable": is_unav,
                "minutes_expected": mins_exp,
                "position_used": pos_for_prior or (player or {}).get("specific_position")
                                 or (player or {}).get("position"),
                "xg_per_90_used": xg_p90, "xa_per_90_used": xa_p90,
                "xg_raw": raw_xg, "xa_raw": raw_xa,
                "shots_per_90_used": float(shots_p90),
                "shots_on_target_per_90_used": float(sot_p90),
                "expected_shots": expected_shots,
                "expected_shots_on_target": expected_shots_on_target,
                "confidence_ratio": cr,
                "career_used": career_used,
                "career_minutes": (player or {}).get("career_minutes", 0.0),
                "career_goals":   (player or {}).get("career_goals", 0.0),
            }

        # 2. Normalisation: somme xG joueurs = xG team
        total_raw_xg = sum(raw_xg_per_player.values()) or 1e-9
        total_raw_xa = sum(raw_xa_per_player.values()) or 1e-9
        # xA total ≈ goals - solo_goals ≈ ~0.75 * team_xg (75% des buts ont une passe dec)
        team_xa_target = team_xg * 0.75

        def _odds_from_xg_xa(xg_v: float, xa_v: float):
            """Retourne (p_s, p_a, odd_s, odd_a, odd_s_brut, odd_a_brut)."""
            ps_b = 1.0 - math.exp(-xg_v)
            pa_b = 1.0 - math.exp(-xa_v)
            os_b = (1.0 / ps_b) if ps_b > 0 else None
            oa_b = (1.0 / pa_b) if pa_b > 0 else None
            os_c = apply_anti_poisson_calibration(os_b)
            oa_c = apply_anti_poisson_calibration(oa_b)
            ps_c = (1.0 / os_c) if (os_c and os_c > 0) else 0.0
            pa_c = (1.0 / oa_c) if (oa_c and oa_c > 0) else 0.0
            return ps_c, pa_c, os_c, oa_c, os_b, oa_b

        for pid in raw_xg_per_player:
            xg_cal = team_xg * (raw_xg_per_player[pid] / total_raw_xg)
            xa_cal = team_xa_target * (raw_xa_per_player[pid] / total_raw_xa)

            # === Conversion 90' théorique pour le calcul des cotes ===
            # `xg_cal` reste l'xG attendu sur les minutes prévues (titu→85, sub→25)
            # → utilisé pour le contrôle "sum joueurs ≈ team_xg".
            # MAIS la cote remontée à l'UI est calculée à 90' théorique pour
            # correspondre à la garantie buteur FR (Betclic & co valident le bet
            # même si le joueur entre en cours de match). Mathématiquement :
            #   xg_for_90 = xg_cal × 90 / mins_expected
            # Pour un sub à 25min, ça inflate l'xG d'un facteur 3.6 → cote
            # divisée par ~3 → comparable à la cote bookmaker "any-time".
            mins_norm = max(mins_exp_by_pid[pid], 1.0)
            xg_for_90 = xg_cal * 90.0 / mins_norm
            xa_for_90 = xa_cal * 90.0 / mins_norm
            p_scorer, p_assist, odd_scorer, odd_assist, odd_scorer_brut, odd_assist_brut = \
                _odds_from_xg_xa(xg_for_90, xa_for_90)
            result[pid]["xg_calibrated"] = xg_cal
            result[pid]["xa_calibrated"] = xa_cal
            # T009 : exposés pour audit / debug — l'xG ramené à 90' qui sert au calcul cote.
            result[pid]["xg_for_90"] = xg_for_90
            result[pid]["xa_for_90"] = xa_for_90
            result[pid]["p_scorer"] = p_scorer
            result[pid]["p_assist"] = p_assist
            result[pid]["odd_scorer"] = odd_scorer
            result[pid]["odd_assist"] = odd_assist
            result[pid]["odd_scorer_brut"] = odd_scorer_brut
            result[pid]["odd_assist_brut"] = odd_assist_brut

            # === Shadow odds : "et si CE joueur jouait à mins_starter ?" ===
            # Pour les titulaires actuels, shadow = actuel (rien à simuler).
            # Pour les subs présumés, on simule sa "promotion" : son raw passe
            # de raw_actual à raw_starter ; les autres restent inchangés ;
            # on renormalise sur la team_xg cible. Sa share grossit, les autres
            # se diluent légèrement (mais ne sont pas exposées dans le shadow).
            # Conversion 90' théorique appliquée également au shadow (avec
            # mins_starter_shadow qui vaut typiquement 80-87, donc facteur ~1.05-1.13).
            # T011 : pour les blessés/suspendus, on neutralise le shadow (sémantique
            # "il est indispo, ça n'a pas de sens de le simuler titulaire" — l'user
            # peut toujours le réactiver via la checkbox UI pour recalcul live).
            if result[pid].get("is_unavailable"):
                xg_cal_sh, xa_cal_sh = 0.0, 0.0
                p_s_sh, p_a_sh = 0.0, 0.0
                os_sh, oa_sh = None, None
            elif result[pid]["is_starter"]:
                xg_cal_sh, xa_cal_sh = xg_cal, xa_cal
                p_s_sh, p_a_sh = p_scorer, p_assist
                os_sh, oa_sh = odd_scorer, odd_assist
            else:
                delta_xg = raw_xg_starter_per_player[pid] - raw_xg_per_player[pid]
                delta_xa = raw_xa_starter_per_player[pid] - raw_xa_per_player[pid]
                new_total_xg = total_raw_xg + delta_xg
                new_total_xa = total_raw_xa + delta_xa
                xg_cal_sh = team_xg * (raw_xg_starter_per_player[pid] / new_total_xg) \
                    if new_total_xg > 0 else 0.0
                xa_cal_sh = team_xa_target * (raw_xa_starter_per_player[pid] / new_total_xa) \
                    if new_total_xa > 0 else 0.0
                mins_norm_sh = max(mins_starter_shadow_by_pid[pid], 1.0)
                xg_for_90_sh = xg_cal_sh * 90.0 / mins_norm_sh
                xa_for_90_sh = xa_cal_sh * 90.0 / mins_norm_sh
                p_s_sh, p_a_sh, os_sh, oa_sh, _, _ = _odds_from_xg_xa(xg_for_90_sh, xa_for_90_sh)
            result[pid]["xg_player_if_starter"] = xg_cal_sh
            result[pid]["xa_player_if_starter"] = xa_cal_sh
            result[pid]["p_scorer_if_starter"] = p_s_sh
            result[pid]["p_assist_if_starter"] = p_a_sh
            result[pid]["odd_scorer_if_starter"] = os_sh
            result[pid]["odd_assist_if_starter"] = oa_sh

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
