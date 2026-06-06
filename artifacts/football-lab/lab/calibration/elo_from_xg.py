"""Phase 2 — Recalibrage Elo via xG getStandings.

Methode :
  1. Fetch standings BSD pour N saisons × M leagues -> xGF/xGA par equipe par saison
  2. Regression moindres carres simultanee : pour chaque equipe, on extrait
     un coef d'attaque (att) et un coef de defense (def) tels que
        xGF_t,s = att_t + def_opp_avg_s + home_advantage
     en moyennant sur la saison (proxy : sans repartition par adversaire on
     utilise la moyenne league/saison comme baseline).
  3. Conversion en Elo : Elo_t = mu + scale * (att_t - def_t)
  4. Backtest : Elo_xg vs Elo_prod vs Elo_marche (Pinnacle close implied)
     -> log-loss 1X2, Brier, ROI Pinnacle close.

Pour la CDM, on agrege joueurs -> nations en ponderant par minutes club
(squad BSD x stats club).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from . import bsd_client


# Liste BSD canonical (id, nom court). A ajuster via lab Admin si BSD bouge.
TOP7_LEAGUES = {
    1: "Premier League",
    3: "La Liga",
    4: "Serie A",
    5: "Bundesliga",
    6: "Ligue 1",
    2: "Liga Portugal",
    10: "Eredivisie",
}


@dataclass
class TeamSeasonXG:
    team_id: int
    team_name: str
    league_id: int
    season_id: int
    matches_played: int
    xgf: float
    xga: float
    gf: int
    ga: int

    @property
    def xgf_per_match(self) -> float:
        return self.xgf / max(self.matches_played, 1)

    @property
    def xga_per_match(self) -> float:
        return self.xga / max(self.matches_played, 1)


def fetch_standings_xg(league_id: int, season_id: int) -> list[TeamSeasonXG]:
    """Fetch standings BSD + extrait xGF/xGA par equipe."""
    candidates = [
        ("v2/standings/", {"league": league_id, "season": season_id}),
        (f"v2/leagues/{league_id}/seasons/{season_id}/standings/", {}),
        ("standings/", {"league": league_id, "season": season_id}),
    ]
    payload = None
    for ep, p in candidates:
        try:
            payload = bsd_client.bsd_get(ep, params=p)
            if payload:
                break
        except Exception:
            continue
    if not payload:
        return []

    rows = _extract_rows(payload)
    out: list[TeamSeasonXG] = []
    for r in rows:
        team = r.get("team") or {}
        if isinstance(team, dict):
            tid = team.get("id") or r.get("team_id")
            tname = team.get("name") or r.get("team_name") or "?"
        else:
            tid = r.get("team_id")
            tname = str(team)
        mp = int(r.get("matches_played") or r.get("played") or r.get("mp") or 0)
        xgf = float(r.get("xg_for") or r.get("xgf") or r.get("xg") or 0.0)
        xga = float(r.get("xg_against") or r.get("xga") or 0.0)
        gf = int(r.get("goals_for") or r.get("gf") or 0)
        ga = int(r.get("goals_against") or r.get("ga") or 0)
        if tid is None:
            continue
        out.append(
            TeamSeasonXG(
                team_id=int(tid),
                team_name=str(tname),
                league_id=league_id,
                season_id=season_id,
                matches_played=mp,
                xgf=xgf,
                xga=xga,
                gf=gf,
                ga=ga,
            )
        )
    return out


def _extract_rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for k in ("standings", "table", "results", "data", "rows"):
        v = payload.get(k)
        if isinstance(v, list):
            # parfois c'est une liste de groupes [{group:'overall', table:[...]}]
            if v and isinstance(v[0], dict) and "table" in v[0]:
                return v[0]["table"]
            return v
        if isinstance(v, dict) and "table" in v:
            return v["table"]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Regression att/def par equipe
# ─────────────────────────────────────────────────────────────────────────────


def regress_att_def(rows: Iterable[TeamSeasonXG]) -> dict[int, dict]:
    """Regression simple : pour chaque equipe on calcule
        att_t = mean(xgf_per_match_t) / league_avg_xgf_par_saison
        def_t = mean(xga_per_match_t) / league_avg_xga_par_saison
    Centre sur 1.0 = niveau moyen.

    Si l'equipe apparait sur plusieurs saisons, on moyenne avec decay
    exponentiel (saison la plus recente pondere le plus).
    """
    rows = list(rows)
    if not rows:
        return {}

    # baseline par (league, season)
    baseline: dict[tuple[int, int], dict] = {}
    by_ls: dict[tuple[int, int], list[TeamSeasonXG]] = {}
    for r in rows:
        key = (r.league_id, r.season_id)
        by_ls.setdefault(key, []).append(r)
    for key, lst in by_ls.items():
        xgf_avg = float(np.mean([x.xgf_per_match for x in lst]))
        xga_avg = float(np.mean([x.xga_per_match for x in lst]))
        baseline[key] = {"xgf": xgf_avg, "xga": xga_avg}

    # decay : saison la plus haute (id ou year) = poids 1.0, decay 0.7 par saison
    seasons_sorted = sorted({r.season_id for r in rows}, reverse=True)
    season_weight = {s: 0.7 ** i for i, s in enumerate(seasons_sorted)}

    agg: dict[int, dict] = {}
    for r in rows:
        b = baseline[(r.league_id, r.season_id)]
        if b["xgf"] <= 0 or b["xga"] <= 0:
            continue
        att = r.xgf_per_match / b["xgf"]  # 1.0 = niveau league
        defc = r.xga_per_match / b["xga"]  # 1.0 = niveau league
        w = season_weight.get(r.season_id, 0.5)
        d = agg.setdefault(
            r.team_id,
            {
                "team_name": r.team_name,
                "league_id": r.league_id,
                "att_num": 0.0,
                "att_den": 0.0,
                "def_num": 0.0,
                "def_den": 0.0,
                "seasons": [],
            },
        )
        d["att_num"] += att * w
        d["att_den"] += w
        d["def_num"] += defc * w
        d["def_den"] += w
        d["seasons"].append(r.season_id)

    out: dict[int, dict] = {}
    for tid, d in agg.items():
        att = d["att_num"] / max(d["att_den"], 1e-9)
        defc = d["def_num"] / max(d["def_den"], 1e-9)
        out[tid] = {
            "team_name": d["team_name"],
            "league_id": d["league_id"],
            "att": att,
            "def": defc,
            "strength": att - defc,  # > 0 = solde positif net
            "seasons_used": sorted(set(d["seasons"]), reverse=True),
        }
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Conversion strength -> Elo
# ─────────────────────────────────────────────────────────────────────────────


def calibrate_to_elo(
    strengths: dict[int, dict],
    elo_anchor: dict[int, float] | None = None,
    target_mu: float = 1500.0,
    target_sigma: float = 80.0,
) -> dict[int, float]:
    """Convertit la 'strength' (att - def, centree 0) en Elo.

    Si elo_anchor fourni (mapping team_id -> Elo prod), on cale mu/sigma sur
    l'intersection plutot que sur des valeurs nominales -> Elo_xg comparable a Elo_prod.
    """
    s_vals = np.array([d["strength"] for d in strengths.values()])
    if elo_anchor and len(elo_anchor) >= 5:
        common = [t for t in strengths if t in elo_anchor]
        if len(common) >= 5:
            s_common = np.array([strengths[t]["strength"] for t in common])
            e_common = np.array([elo_anchor[t] for t in common])
            # regression lineaire elo = a + b * strength
            b, a = np.polyfit(s_common, e_common, 1)
            return {tid: float(a + b * strengths[tid]["strength"]) for tid in strengths}

    mu = float(s_vals.mean()) if len(s_vals) else 0.0
    sigma = float(s_vals.std()) or 1.0
    return {
        tid: target_mu + target_sigma * (d["strength"] - mu) / sigma
        for tid, d in strengths.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Backtest 1X2 contre cotes marche (log-loss / Brier / ROI)
# ─────────────────────────────────────────────────────────────────────────────


def elo_to_probs_1x2(elo_h: float, elo_a: float, home_adv: float = 65.0) -> tuple[float, float, float]:
    """Conversion Elo classique avec avantage du terrain + slot draw.

    Avec :  expected_h = 1 / (1 + 10**(-(elo_h - elo_a + home_adv) / 400))
    Repartition X = 0.27 - alpha * |expected_h - 0.5| (decroissance pres des extremes).
    """
    eh = 1.0 / (1.0 + 10 ** (-(elo_h - elo_a + home_adv) / 400.0))
    # repartition empirique : X ~ 0.27 au centre, ~ 0.18 aux extremes
    p_d = max(0.10, 0.27 - 0.35 * abs(eh - 0.5))
    p_h = (1.0 - p_d) * eh
    p_a = (1.0 - p_d) * (1.0 - eh)
    return p_h, p_d, p_a


def log_loss_1x2(p_h: float, p_d: float, p_a: float, outcome: str) -> float:
    eps = 1e-12
    if outcome == "H":
        return -math.log(max(p_h, eps))
    if outcome == "D":
        return -math.log(max(p_d, eps))
    if outcome == "A":
        return -math.log(max(p_a, eps))
    raise ValueError(outcome)


def brier_1x2(p_h: float, p_d: float, p_a: float, outcome: str) -> float:
    yh, yd, ya = (
        (1, 0, 0) if outcome == "H" else (0, 1, 0) if outcome == "D" else (0, 0, 1)
    )
    return (p_h - yh) ** 2 + (p_d - yd) ** 2 + (p_a - ya) ** 2


def roi_pinnacle_close(
    p_model: tuple[float, float, float],
    odds_close: tuple[float, float, float],
    outcome: str,
    edge_threshold: float = 0.02,
) -> float:
    """Stake unitaire 1 si EV > edge_threshold sur un des 3 outcomes, sinon 0.

    Retourne le PnL en unites (gain - mise, ou -mise si perd).
    """
    bets = []
    for p, odd, lbl in zip(p_model, odds_close, "HDA"):
        ev = p * odd - 1.0
        if ev > edge_threshold:
            bets.append((lbl, odd))
    pnl = 0.0
    for lbl, odd in bets:
        pnl += (odd - 1.0) if lbl == outcome else -1.0
    return pnl


# ─────────────────────────────────────────────────────────────────────────────
# Agregation joueurs -> nations CDM
# ─────────────────────────────────────────────────────────────────────────────


def aggregate_nation_elo(
    squad: list[dict],
    club_strengths: dict[int, dict],
    minutes_by_player: dict[int, float] | None = None,
) -> dict:
    """Agrege la strength club -> nation en ponderant par minutes club.

    Args:
        squad: liste de joueurs (each dict avec 'player_id', 'club_id', 'minutes_club')
        club_strengths: output de regress_att_def
        minutes_by_player: optionnel, override sur les minutes
    """
    total_w = 0.0
    att_acc = 0.0
    def_acc = 0.0
    contribs = []
    for p in squad:
        pid = p.get("player_id") or p.get("id")
        cid = p.get("club_id") or p.get("team_id")
        mins = (
            (minutes_by_player or {}).get(pid)
            or p.get("minutes_club")
            or p.get("minutes")
            or 0
        )
        if cid not in club_strengths or mins <= 0:
            continue
        s = club_strengths[cid]
        w = float(mins)
        att_acc += s["att"] * w
        def_acc += s["def"] * w
        total_w += w
        contribs.append(
            {"player_id": pid, "club_id": cid, "mins": mins, "att": s["att"], "def": s["def"]}
        )
    if total_w <= 0:
        return {"att": 1.0, "def": 1.0, "strength": 0.0, "minutes": 0.0, "contribs": []}
    return {
        "att": att_acc / total_w,
        "def": def_acc / total_w,
        "strength": (att_acc - def_acc) / total_w,
        "minutes": total_w,
        "contribs": contribs,
    }
