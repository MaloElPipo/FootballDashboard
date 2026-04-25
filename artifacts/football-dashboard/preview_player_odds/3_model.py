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
        else:
            a["xg_per_90"] = a["xa_per_90"] = a["shots_per_90"] = 0.0
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

    `league_prior` est utilisé tel quel — l'appelant doit le calculer via
    `position_prior(player)` pour bénéficier du prior par poste.
    """
    matches = player.get("matches_played", 0)
    obs = player.get(metric, 0.0)
    if matches == 0:
        return league_prior
    return (matches * obs + k * league_prior) / (matches + k)


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
    """Calcule le xG/90 utilisé pour le pricing buteur, en blendant :
      - signal carrière (Understat 4 saisons + BSD courante incrémentée)
      - signal saison courante shrunken vers prior position-aware (existant)

    Formule (inspirée Excel "Buteurs Maison 4.1") :
      cr = min(career_minutes / 15000, 1.0)
      g90_career = career_goals × 90 / career_minutes
      g90_curr_shrunk = (matches × xg_per_90 + K × prior) / (matches + K)
      g90_used = cr × g90_career + (1 - cr) × g90_curr_shrunk

    Si career_minutes < CAREER_MIN_USABLE_MINUTES → comportement = shrunk_per90 actuel
    (cr=0). Le saut « xG carrière vs goals carrière » : on prend `goals` car les vrais
    buteurs sur-performent leur xG (Watkins, Salah, Haaland tous over-perform).

    Returns: (g90_used, confidence_ratio, career_used)
    """
    g90_curr_shrunk = shrunk_per90(player or {}, "xg_per_90", prior_xg)
    cr = career_confidence_ratio(player or {})
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

    - Compo non confirmée → 90 pour tout le monde (pas de notion starter/sub)
    - Compo confirmée + titulaire → avg_mins_when_starter, floor 80 si <60
    - Compo confirmée + remplaçant → MINUTES_SUB_DEFAULT
    """
    if not lineup_confirmed:
        return MINUTES_DEFAULT_NO_LINEUP

    if not lp.get("is_starter"):
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
        raw_xg_per_player = {}
        raw_xa_per_player = {}
        for lp in team_lineup:
            pid = lp["player_id"]
            if pid is None:
                continue
            player = pool.get(pid)

            # Prior position-aware. Si lineup BSD donne une position pour ce match
            # (ex Maguire annoncé ST), elle prime — on construit un dict virtuel.
            pos_for_prior = lp.get("position")
            if pos_for_prior:
                prior_player = {"specific_position": pos_for_prior, "position": pos_for_prior,
                                "is_gk": (player or {}).get("is_gk", False)}
            else:
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

            mins_exp = _resolve_minutes(lp, player, side_confirmed)
            raw_xg = xg_p90 * (mins_exp / 90.0)
            raw_xa = xa_p90 * (mins_exp / 90.0)

            raw_xg_per_player[pid] = raw_xg
            raw_xa_per_player[pid] = raw_xa
            result[pid] = {
                "team_side": side, "team_id": team_id,
                "name": (player or {}).get("name", f"id={pid}"),
                "is_starter": lp["is_starter"], "is_gk": is_gk,
                "minutes_expected": mins_exp,
                "position_used": pos_for_prior or (player or {}).get("specific_position")
                                 or (player or {}).get("position"),
                "xg_per_90_used": xg_p90, "xa_per_90_used": xa_p90,
                "xg_raw": raw_xg, "xa_raw": raw_xa,
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

        for pid in raw_xg_per_player:
            xg_cal = team_xg * (raw_xg_per_player[pid] / total_raw_xg)
            xa_cal = team_xa_target * (raw_xa_per_player[pid] / total_raw_xa)
            # Cote brute Poisson (anytime)
            p_scorer_brut = 1.0 - math.exp(-xg_cal)
            p_assist_brut = 1.0 - math.exp(-xa_cal)
            odd_scorer_brut = (1.0 / p_scorer_brut) if p_scorer_brut > 0 else None
            odd_assist_brut = (1.0 / p_assist_brut) if p_assist_brut > 0 else None
            # Calibration anti-Poisson (réduit la sur-estimation des outsiders)
            odd_scorer = apply_anti_poisson_calibration(odd_scorer_brut)
            odd_assist = apply_anti_poisson_calibration(odd_assist_brut)
            # p_model = 1 / cote_calibrée pour rester cohérent avec edge = p × cote_book − 1
            p_scorer = (1.0 / odd_scorer) if (odd_scorer and odd_scorer > 0) else 0.0
            p_assist = (1.0 / odd_assist) if (odd_assist and odd_assist > 0) else 0.0
            result[pid]["xg_calibrated"] = xg_cal
            result[pid]["xa_calibrated"] = xa_cal
            result[pid]["p_scorer"] = p_scorer
            result[pid]["p_assist"] = p_assist
            result[pid]["odd_scorer"] = odd_scorer
            result[pid]["odd_assist"] = odd_assist
            result[pid]["odd_scorer_brut"] = odd_scorer_brut
            result[pid]["odd_assist_brut"] = odd_assist_brut

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
