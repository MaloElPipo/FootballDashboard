import os
import requests
import unicodedata
import streamlit as st

BSD_BASE = "https://sports.bzzoiro.com/api"

def _bsd_headers():
    key = os.environ.get("BSD_API_KEY", "")
    return {"Authorization": f"Token {key}"}

# ── League IDs ────────────────────────────────────────────────────────────────
BSD_LEAGUE_IDS = {
    "Premier League":      1,
    "La Liga":             3,
    "Serie A":             4,
    "Bundesliga":          5,
    "Ligue 1":             6,
    "Champions League":    7,
    "Europa League":       8,
    "Super Lig":          11,
    "Saudi Pro League":   17,
    "World Cup 2026":     27,
}

BSD_LEAGUE_NAMES = {v: k for k, v in BSD_LEAGUE_IDS.items()}

# ── TM club name → BSD team ID (all 25 clubs of France WC2026 squad) ─────────
TM_TO_BSD_TEAM = {
    "AC Milan":      63,  "AS Roma":    65,  "Al-Hilal":   262,
    "Al-Nassr":     267,  "Arsenal":    18,  "Aston Villa":  3,
    "Atlético":      54,  "Barcelone":  44,  "Bayern":      79,
    "Chelsea":       13,  "Crystal Palace": 14, "Fenerbahçe": 134,
    "Inter":         77,  "Juventus":   73,  "Leverkusen":  85,
    "Liverpool":      1,  "Man City":   12,  "Marseille":   98,
    "Monaco":       101,  "OGC Nice":  103,  "Paris SG":   114,
    "RC Lens":       99,  "Real Madrid": 57, "Stade Rennais": 97,
    "Tottenham":      9,
}

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())


# ── TM nation code → BSD nationality name ─────────────────────────────────────
# Les noms de nationalité exacts tels qu'utilisés dans l'API BSD
TM_CODE_TO_BSD_NATIONALITY = {
    "FRA": "France",   "ESP": "Spain",    "DEU": "Germany",  "ENG": "England",
    "ITA": "Italy",    "BRA": "Brazil",   "ARG": "Argentina","PRT": "Portugal",
    "NLD": "Netherlands", "BEL": "Belgium",  "HRV": "Croatia",  "URU": "Uruguay",
    "COL": "Colombia", "MEX": "Mexico",   "USA": "United States", "CAN": "Canada",
    "SEN": "Senegal",  "MAR": "Morocco",  "GHA": "Ghana",    "NGR": "Nigeria",
    "CMR": "Cameroon", "CIV": "Ivory Coast", "TUN": "Tunisia","EGY": "Egypt",
    "ALG": "Algeria",  "JPN": "Japan",    "KOR": "South Korea","AUS": "Australia",
    "IRN": "Iran",     "SAU": "Saudi Arabia", "QAT": "Qatar","MAS": "Malaysia",
    "SRB": "Serbia",   "AUT": "Austria",  "SUI": "Switzerland","DEN": "Denmark",
    "SWE": "Sweden",   "NOR": "Norway",   "POL": "Poland",   "CZE": "Czech Republic",
    "SVK": "Slovakia", "HUN": "Hungary",  "ROU": "Romania",  "UKR": "Ukraine",
    "TUR": "Turkey",   "GRE": "Greece",   "SCO": "Scotland", "WAL": "Wales",
    "IRL": "Ireland",  "NZL": "New Zealand",
}


# ── Low-level fetch ───────────────────────────────────────────────────────────
def _get(endpoint: str, params: dict = None, timeout: int = 15):
    url = f"{BSD_BASE}/{endpoint}/"
    try:
        r = requests.get(url, headers=_bsd_headers(), params=params or {}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


# ── Leagues ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400)
def get_bsd_leagues():
    data = _get("leagues")
    return data.get("results", [])


# ── Events / Odds ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_bsd_events(league_id: int = None, per_page: int = 100):
    params = {"per_page": per_page}
    if league_id:
        params["league_id"] = league_id
    data = _get("events", params)
    return data.get("results", [])


def get_all_bsd_events():
    """Return all upcoming events across all tracked leagues."""
    return get_bsd_events(per_page=258)


def get_bsd_odds_for_match(home: str, away: str):
    """Find BSD odds for a specific match by team name fuzzy-match."""
    events = get_all_bsd_events()
    hn, an = _norm(home), _norm(away)
    for evt in events:
        eh = _norm(evt.get("home_team", ""))
        ea = _norm(evt.get("away_team", ""))
        if (hn in eh or eh in hn) and (an in ea or ea in an):
            return {
                "home":   evt.get("odds_home"),
                "draw":   evt.get("odds_draw"),
                "away":   evt.get("odds_away"),
                "over15": evt.get("odds_over_15"),
                "over25": evt.get("odds_over_25"),
                "over35": evt.get("odds_over_35"),
                "under15": evt.get("odds_under_15"),
                "under25": evt.get("odds_under_25"),
                "under35": evt.get("odds_under_35"),
                "btts_yes": evt.get("odds_btts_yes"),
                "btts_no":  evt.get("odds_btts_no"),
                "xg_home":  evt.get("actual_home_xg"),
                "xg_away":  evt.get("actual_away_xg"),
                "event_date": evt.get("event_date", "")[:10],
                "status": evt.get("status"),
                "league": evt.get("league", {}).get("name", ""),
            }
    return None


# ── Players ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_bsd_team_players(team_id: int):
    data = _get("players", {"team": team_id, "per_page": 60})
    return data.get("results", [])


@st.cache_data(ttl=86400)
def get_bsd_players_by_nationality(nationality: str) -> list:
    """
    Fetch all BSD players of a given nationality (all pages).
    Returns a flat list of player dicts.
    """
    all_players = []
    page = 1
    while True:
        data = _get("players", {"nationality": nationality, "per_page": 100, "page": page})
        results = data.get("results", [])
        all_players.extend(results)
        if not data.get("next"):
            break
        page += 1
        if page > 15:  # safety cap
            break
    return all_players


def _match_player_in_list(player_name: str, candidates: list):
    """Fuzzy name match of player_name against a list of BSD player dicts."""
    target = _norm(player_name)
    parts_t = target.split()
    # 1. Exact normalised match
    for p in candidates:
        if _norm(p.get("name", "")) == target:
            return p
    # 2. Last-name + first initial
    for p in candidates:
        pn = _norm(p.get("name", "")).split()
        if parts_t and pn and parts_t[-1] == pn[-1]:
            if len(parts_t) > 1 and len(pn) > 1 and parts_t[0][0] == pn[0][0]:
                return p
    # 3. Last name only (>= 5 chars to avoid false positives)
    for p in candidates:
        pn = _norm(p.get("name", "")).split()
        if parts_t and pn and parts_t[-1] == pn[-1] and len(parts_t[-1]) >= 5:
            return p
    return None


@st.cache_data(ttl=3600)
def find_bsd_player(player_name: str, club_tm: str, nation_code: str = None):
    """
    Find a BSD player record.
    Strategy (in order):
      1. If nation_code is known → search by nationality (most accurate for national squads)
      2. If club_tm is in TM_TO_BSD_TEAM → search club roster
    Returns BSD player dict or None.
    """
    # 1. Nationality-based search (best coverage for WC squads)
    if nation_code:
        nat_name = TM_CODE_TO_BSD_NATIONALITY.get(nation_code)
        if nat_name:
            nat_players = get_bsd_players_by_nationality(nat_name)
            result = _match_player_in_list(player_name, nat_players)
            if result:
                return result

    # 2. Club roster fallback
    team_id = TM_TO_BSD_TEAM.get(club_tm)
    if team_id:
        club_players = get_bsd_team_players(team_id)
        result = _match_player_in_list(player_name, club_players)
        if result:
            return result

    return None


# ── Player stats ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def get_bsd_player_stats_raw(player_id: int, per_page: int = 100):
    """Return list of per-match stat dicts for a given BSD player id."""
    data = _get("player-stats", {"player": player_id, "per_page": per_page})
    return data.get("results", [])


def aggregate_bsd_season_stats(player_id: int):
    """
    Aggregate all per-match records into season totals.
    Returns a dict with summed/averaged stats.
    """
    records = get_bsd_player_stats_raw(player_id)
    if not records:
        return None

    def _sum(key):
        return sum((r.get(key) or 0) for r in records)

    def _avg(key):
        vals = [r.get(key) for r in records if r.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    minutes = _sum("minutes_played")
    appearances = sum(1 for r in records if (r.get("minutes_played") or 0) > 0)

    return {
        "appearances":       appearances,
        "minutes_played":    minutes,
        "rating":            _avg("rating"),
        "goals":             _sum("goals"),
        "assists":           _sum("goal_assist"),
        "xg":                round(sum((r.get("expected_goals") or 0) for r in records), 2),
        "xa":                round(sum((r.get("expected_assists") or 0) for r in records), 2),
        "total_shots":       _sum("total_shots"),
        "shots_on_target":   _sum("shots_on_target"),
        "key_passes":        _sum("key_pass"),
        "total_passes":      _sum("total_pass"),
        "accurate_passes":   _sum("accurate_pass"),
        "pass_accuracy":     round(_sum("accurate_pass") / max(_sum("total_pass"), 1) * 100, 1),
        "tackles":           _sum("total_tackle"),
        "interceptions":     _sum("interception"),
        "duels_won":         _sum("duel_won"),
        "duels_lost":        _sum("duel_lost"),
        "duel_pct":          round(_sum("duel_won") / max(_sum("duel_won") + _sum("duel_lost"), 1) * 100, 1),
        "yellow_cards":      _sum("yellow_card"),
        "red_cards":         _sum("red_card"),
        "saves":             _sum("saves"),
        "goals_conceded":    _sum("goals_conceded"),
        "records":           len(records),
    }


def get_squad_bsd_stats(players_raw: list, nation_code: str = None):
    """
    For a list of TM squad players (dicts with 'name' and 'club'),
    return a dict: player_name → aggregated BSD stats (or None).
    If nation_code is provided (e.g. 'FRA'), uses nationality-based player lookup.
    """
    results = {}
    for p in players_raw:
        name = p.get("name", "")
        club = p.get("club", "")
        bsd_player = find_bsd_player(name, club, nation_code=nation_code)
        if bsd_player:
            stats = aggregate_bsd_season_stats(bsd_player["id"])
            if stats:
                stats["bsd_id"] = bsd_player["id"]
                stats["bsd_name"] = bsd_player.get("name", name)
                stats["position"] = bsd_player.get("position", "")
                stats["market_value"] = bsd_player.get("market_value") or p.get("market_value_eur", 0)
        else:
            stats = None
        results[name] = stats
    return results


# ── Player Rating ─────────────────────────────────────────────────────────────
def compute_player_rating(stats: dict, market_value_eur: int = 0) -> float:
    """
    Compute a composite player rating on a 0-100 scale.
    Weights:
      - API rating (0-10)  → 45 pts
      - Market value (normalised to 200M cap) → 35 pts
      - Form (appearances, goals+assists, xG) → 20 pts
    """
    if not stats:
        return None

    # 1. API rating component (0→45)
    api_r = stats.get("rating") or 0
    rating_pts = (api_r / 10) * 45

    # 2. Market value component (0→35), capped at 200M
    mv = market_value_eur or stats.get("market_value") or 0
    mv_cap = 200_000_000
    mv_pts = min(mv / mv_cap, 1.0) * 35

    # 3. Form component (0→20)
    apps = min(stats.get("appearances", 0), 30)
    ga   = stats.get("goals", 0) + stats.get("assists", 0)
    xg   = stats.get("xg", 0)
    apps_pts = (apps / 30) * 8
    ga_pts   = min(ga / 20, 1.0) * 7
    xg_pts   = min(xg / 15, 1.0) * 5
    form_pts = apps_pts + ga_pts + xg_pts

    return round(rating_pts + mv_pts + form_pts, 1)
