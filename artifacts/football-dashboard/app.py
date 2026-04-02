import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import anthropic
from nations_data import WC2026_NATIONS, CONF_LABELS, CONF_COUNTS, get_nation_by_code
from squad_scraper import (
    get_squad_cached, get_cache_status, clear_cache_for, clear_all_cache,
    get_static_squad, get_static_db_status,
    load_player_selection, save_player_selection, get_nation_active_status,
)
from bsd_api import (
    get_bsd_odds_for_match,
    get_squad_bsd_stats,
    compute_player_rating,
    find_bsd_player,
    aggregate_bsd_season_stats,
    TM_TO_BSD_TEAM,
)
from bsd_cache import ensure_cache_ready, cache_summary

ensure_cache_ready()

API_BASE = os.environ.get("STATS_API_URL", "https://api.thestatsapi.com/api")
API_KEY = os.environ.get("STATS_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

ANTHROPIC_BASE_URL = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_BASE_URL", "")
ANTHROPIC_API_KEY = os.environ.get("AI_INTEGRATIONS_ANTHROPIC_API_KEY", "")

def get_claude_client():
    return anthropic.Anthropic(
        api_key=ANTHROPIC_API_KEY,
        base_url=ANTHROPIC_BASE_URL if ANTHROPIC_BASE_URL else None,
    )

st.set_page_config(
    page_title="Football Analytics Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

COMPETITION_GROUPS = {
    "🏆 Clubs — UEFA": [
        {"id": "comp_3498",   "name": "UEFA Champions League",         "region": "Europe", "type": "club"},
        {"id": "comp_7739",   "name": "UEFA Europa League",            "region": "Europe", "type": "club"},
        {"id": "comp_408698", "name": "UEFA Conference League",        "region": "Europe", "type": "club"},
        {"id": "comp_6694",   "name": "UEFA Women's Champions League", "region": "Europe", "type": "club"},
    ],
    "🏆 Clubs — Continentaux": [
        {"id": "comp_0499",   "name": "CONMEBOL Libertadores",         "region": "South America", "type": "club"},
        {"id": "comp_1615",   "name": "CONMEBOL Sudamericana",         "region": "South America", "type": "club"},
        {"id": "comp_08478",  "name": "CAF Champions League",          "region": "Africa",        "type": "club"},
        {"id": "comp_8649",   "name": "CONCACAF Champions Cup",        "region": "N&C America",   "type": "club"},
    ],
    "🏆 Clubs — Ligues Domestiques": [
        {"id": "comp_3039",   "name": "Premier League",                "region": "Angleterre",    "type": "club"},
        {"id": "comp_4643",   "name": "Bundesliga",                    "region": "Allemagne",     "type": "club"},
        {"id": "comp_0256",   "name": "Ligue 1",                       "region": "France",        "type": "club"},
        {"id": "comp_5840",   "name": "Serie A",                       "region": "Italie",        "type": "club"},
        {"id": "comp_0406",   "name": "2. Bundesliga",                 "region": "Allemagne",     "type": "club"},
    ],
    "🌍 Équipes Nationales — Tournois": [
        {"id": "comp_574977", "name": "UEFA Nations League",           "region": "Europe",        "type": "national"},
        {"id": "comp_5749",   "name": "Copa América",                  "region": "Amér. du Sud",  "type": "national"},
        {"id": "comp_1554",   "name": "Africa Cup of Nations",         "region": "Afrique",       "type": "national"},
        {"id": "comp_1376",   "name": "CONCACAF Gold Cup",             "region": "N&C Amér.",     "type": "national"},
        {"id": "comp_193547", "name": "CONCACAF Nations League",       "region": "N&C Amér.",     "type": "national"},
        {"id": "comp_29967",  "name": "Matchs Amicaux Internationaux", "region": "Monde",         "type": "national"},
    ],
    "🌍 Équipes Nationales — Qualif. Coupe du Monde": [
        {"id": "comp_2954",   "name": "Qualif. CM — UEFA (Europe)",    "region": "Europe",        "type": "national"},
        {"id": "comp_8973",   "name": "Qualif. CM — AFC (Asie)",       "region": "Asie",          "type": "national"},
        {"id": "comp_4682",   "name": "Qualif. CM — CONMEBOL",         "region": "Amér. du Sud",  "type": "national"},
        {"id": "comp_5720",   "name": "Qualif. CM — CAF (Afrique)",    "region": "Afrique",       "type": "national"},
        {"id": "comp_7363",   "name": "Qualif. CM — OFC (Océanie)",    "region": "Océanie",       "type": "national"},
        {"id": "comp_0836",   "name": "Qualif. CM — CONCACAF",         "region": "N&C Amér.",     "type": "national"},
    ],
}

CLUB_GROUPS = {k for k, v in COMPETITION_GROUPS.items() if v and v[0].get("type") == "club"}
NATIONAL_GROUPS = {k for k, v in COMPETITION_GROUPS.items() if v and v[0].get("type") == "national"}

ALL_CURATED = [c for comps in COMPETITION_GROUPS.values() for c in comps]

POSITION_MAP = {"GK": "Goalkeeper", "D": "Defender", "M": "Midfielder", "F": "Forward", "0": "Unknown"}


def pos_label(code):
    return POSITION_MAP.get(code, code or "Unknown")


def _display(df):
    display_cols = ["date", "home_team_name", "home_score", "away_score", "away_team_name", "status", "matchday"]
    existing = [c for c in display_cols if c in df.columns]
    display = df[existing].copy()
    rename = {"date": "Date", "home_team_name": "Home Team", "home_score": "Home",
              "away_score": "Away", "away_team_name": "Away Team", "status": "Status", "matchday": "MD"}
    display.rename(columns=rename, inplace=True)
    st.dataframe(display, width="stretch", hide_index=True)


@st.cache_data(ttl=300)
def fetch(endpoint, params=None):
    url = f"{API_BASE}/football/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_raw(endpoint, params=None):
    """Non-cached fetch for internal use in multi-page loops."""
    url = f"{API_BASE}/football/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=20)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=86400)
def fetch_competition_info(comp_id):
    """Fetch competition metadata (current_season_id, etc.). Cached 24h."""
    try:
        url = f"{API_BASE}/football/competitions/{comp_id}"
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("data", {})
    except Exception:
        pass
    return {}


@st.cache_data(ttl=300)
def get_teams(competition_id=None, per_page=50):
    params = {"per_page": per_page}
    if competition_id:
        params["competition_id"] = competition_id
    data = fetch("teams", params)
    return data.get("data", []), data.get("meta", {})


@st.cache_data(ttl=300)
def get_players(team_id=None, per_page=50, page=1):
    params = {"per_page": per_page, "page": page}
    if team_id:
        params["team_id"] = team_id
    data = fetch("players", params)
    return data.get("data", []), data.get("meta", {})


@st.cache_data(ttl=300)
def get_matches(competition_id=None, status=None, per_page=50, page=1):
    params = {"per_page": per_page, "page": page}
    if competition_id:
        params["competition_id"] = competition_id
    if status:
        params["status"] = status
    data = fetch("matches", params)
    return data.get("data", []), data.get("meta", {})


@st.cache_data(ttl=600)
def get_all_teams_from_matches(competition_id):
    """Extract unique teams by scanning all match pages for a competition."""
    all_teams = {}
    for page in range(1, 20):
        params = {"competition_id": competition_id, "per_page": 50, "page": page}
        try:
            data = fetch("matches", params)
        except Exception:
            break
        matches = data.get("data", [])
        if not matches:
            break
        for m in matches:
            for side in ("home_team", "away_team"):
                t = m.get(side)
                if t and isinstance(t, dict) and t.get("id"):
                    all_teams[t["id"]] = t["name"]
        meta = data.get("meta", {})
        if meta.get("page", page) >= meta.get("total_pages", 1):
            break
    return sorted(all_teams.values())


ALL_NATIONAL_IDS = [c["id"] for group, comps in COMPETITION_GROUPS.items() if group in NATIONAL_GROUPS for c in comps]
ALL_NATIONAL_OPTION = "🌍 Toutes équipes nationales (toutes compétitions)"


@st.cache_data(ttl=86400)
def get_all_matches_for_competition(competition_id):
    """Fetch ALL finished matches for a competition — current season + all discoverable historical seasons.
    
    Strategy:
    1. Fetch with status=finished across all pages (gets everything the API returns without season filter).
    2. Use the competition's current_season_id to discover older season IDs by decrementing,
       fetching each historical season until we hit 5 consecutive empty seasons.
    Cached for 24h since historical data never changes.
    """
    seen_ids = set()
    all_matches = []

    def _fetch_season(season_id=None):
        """Fetch all finished matches for one season (or no season filter if None)."""
        collected = []
        for page in range(1, 500):
            params = {
                "competition_id": competition_id,
                "per_page": 50,
                "page": page,
                "status": "finished",
            }
            if season_id:
                params["season_id"] = season_id
            try:
                data = fetch_raw("matches", params)
            except Exception:
                break
            matches = data.get("data", [])
            if not matches:
                break
            for m in matches:
                mid = m.get("id")
                if mid and mid not in seen_ids:
                    seen_ids.add(mid)
                    all_matches.append(m)
                    collected.append(m)
            meta = data.get("meta", {})
            if meta.get("page", page) >= meta.get("total_pages", 1):
                break
        return len(collected)

    # Pass 1: fetch without season filter (catches all seasons API exposes by default)
    _fetch_season(season_id=None)

    # Pass 2: discover and fetch older seasons via sequential season IDs
    comp_info = fetch_competition_info(competition_id)
    current_season_id = comp_info.get("current_season_id", "")
    if current_season_id and current_season_id.startswith("sn_"):
        try:
            current_num = int(current_season_id[3:])
            consecutive_misses = 0
            for delta in range(1, 200):
                if consecutive_misses >= 5:
                    break
                old_season_id = f"sn_{current_num - delta}"
                found = _fetch_season(season_id=old_season_id)
                if found == 0:
                    consecutive_misses += 1
                else:
                    consecutive_misses = 0
        except (ValueError, Exception):
            pass

    return all_matches


@st.cache_data(ttl=86400)
def get_all_national_matches():
    """Aggregate ALL finished matches from every national team competition. Cached 24h."""
    seen = set()
    combined = []
    for comp_id in ALL_NATIONAL_IDS:
        for m in get_all_matches_for_competition(comp_id):
            mid = m.get("id")
            if mid not in seen:
                seen.add(mid)
                combined.append(m)
    return combined


@st.cache_data(ttl=900)
def get_scheduled_matches_for_competition(competition_id):
    """Fetch upcoming scheduled matches for a competition."""
    all_matches = []
    for page in range(1, 20):
        params = {"competition_id": competition_id, "per_page": 50, "page": page, "status": "scheduled"}
        try:
            data = fetch_raw("matches", params)
        except Exception:
            break
        matches = data.get("data", [])
        if not matches:
            break
        all_matches.extend(matches)
        meta = data.get("meta", {})
        if meta.get("page", page) >= meta.get("total_pages", 1):
            break
    return all_matches


@st.cache_data(ttl=900)
def get_all_national_scheduled():
    """Aggregate ALL upcoming matches from every national team competition."""
    seen = set()
    combined = []
    for comp_id in ALL_NATIONAL_IDS:
        for m in get_scheduled_matches_for_competition(comp_id):
            mid = m.get("id")
            if mid not in seen:
                seen.add(mid)
                combined.append(m)
    return combined


ELO_CODE_TO_NAME = {
    "ES": "Spain", "AR": "Argentina", "FR": "France", "EN": "England", "BR": "Brazil",
    "PT": "Portugal", "CO": "Colombia", "NL": "Netherlands", "EC": "Ecuador", "HR": "Croatia",
    "DE": "Germany", "NO": "Norway", "JP": "Japan", "TR": "Turkey", "UY": "Uruguay",
    "CH": "Switzerland", "SN": "Senegal", "DK": "Denmark", "BE": "Belgium", "MX": "Mexico",
    "IT": "Italy", "PY": "Paraguay", "AT": "Austria", "MA": "Morocco", "CA": "Canada",
    "AU": "Australia", "RU": "Russia", "RS": "Serbia", "SQ": "Albania", "UA": "Ukraine",
    "IR": "Iran", "KR": "South Korea", "NG": "Nigeria", "GR": "Greece", "DZ": "Algeria",
    "PA": "Panama", "PL": "Poland", "UZ": "Uzbekistan", "VE": "Venezuela", "CZ": "Czechia",
    "US": "United States", "KO": "Kosovo", "SE": "Sweden", "CL": "Chile", "HU": "Hungary",
    "WA": "Wales", "PE": "Peru", "SI": "Slovenia", "IE": "Republic of Ireland", "JO": "Jordan",
    "EG": "Egypt", "CI": "Côte d'Ivoire", "SK": "Slovakia", "CD": "DR Congo", "GE": "Georgia",
    "AL": "Armenia", "BO": "Bolivia", "TN": "Tunisia", "IL": "Israel", "RO": "Romania",
    "CM": "Cameroon", "CR": "Costa Rica", "IQ": "Iraq", "EI": "Ireland", "ML": "Mali",
    "BA": "Bosnia & Herzegovina", "NM": "North Macedonia", "NZ": "New Zealand",
    "HN": "Honduras", "IS": "Iceland", "SA": "Saudi Arabia", "CV": "Cape Verde",
    "AO": "Angola", "FI": "Finland", "AE": "United Arab Emirates", "JM": "Jamaica",
    "HT": "Haiti", "BF": "Burkina Faso", "ZA": "South Africa", "GT": "Guatemala",
    "BY": "Belarus", "GH": "Ghana", "SY": "Syria", "OM": "Oman", "BG": "Bulgaria",
    "GN": "Guinea", "PS": "Palestine", "NS": "Northern Ireland", "ME": "Montenegro",
    "CW": "Curaçao", "LU": "Luxembourg", "SR": "Suriname", "KZ": "Kazakhstan",
    "BJ": "Benin", "QA": "Qatar", "KD": "Kyrgyzstan", "CN": "China", "GM": "Gambia",
    "LY": "Libya", "BH": "Bahrain", "GA": "Gabon", "UG": "Uganda", "NE": "Niger",
    "TT": "Trinidad & Tobago", "GQ": "Equatorial Guinea", "MG": "Madagascar",
    "FO": "Faroe Islands", "AM": "Armenia", "TH": "Thailand", "KP": "North Korea",
    "MZ": "Mozambique", "ZW": "Zimbabwe", "ZM": "Zambia", "KM": "Comoros",
    "TG": "Togo", "KE": "Kenya", "VN": "Vietnam", "SD": "Sudan", "SL": "Sierra Leone",
    "SV": "El Salvador", "AZ": "Azerbaijan", "EE": "Estonia", "RW": "Rwanda",
    "LB": "Lebanon", "ID": "Indonesia", "KW": "Kuwait", "NI": "Nicaragua",
    "TZ": "Tanzania", "MR": "Mauritania", "NA": "Namibia", "LV": "Latvia",
    "CY": "Cyprus", "LR": "Liberia", "MY": "Malaysia", "GY": "Guyana", "LT": "Lithuania",
    "KG": "Kyrgyzstan", "BI": "Burundi", "TJ": "Tajikistan", "ET": "Ethiopia",
    "DO": "Dominican Republic", "BW": "Botswana", "MD": "Moldova", "GW": "Guinea-Bissau",
    "MW": "Malawi", "CU": "Cuba", "CF": "Central African Republic", "MT": "Malta",
    "TM": "Turkmenistan", "CG": "Congo", "LS": "Lesotho", "PH": "Philippines",
    "YE": "Yemen", "VC": "Saint Vincent & the Grenadines", "IN": "India",
    "SG": "Singapore", "FJ": "Fiji", "GD": "Grenada", "AD": "Andorra",
    "TD": "Chad", "BZ": "Belize", "SM": "San Marino", "LI": "Liechtenstein",
    "MC": "Monaco", "BB": "Barbados", "NP": "Nepal", "MN": "Mongolia",
    "SS": "South Sudan", "TL": "Timor-Leste", "BT": "Bhutan", "BN": "Brunei",
    "ZN": "Zanzibar", "NC": "New Caledonia", "GP": "Guadeloupe", "MQ": "Martinique",
    "GF": "French Guiana", "RE": "Réunion", "MF": "Montserrat",
    "KN": "Saint Kitts & Nevis", "AF": "Afghanistan", "LC": "Saint Lucia",
    "GI": "Gibraltar", "MM": "Myanmar", "SO": "Somalia", "DJ": "Djibouti",
    "BD": "Bangladesh", "SC": "Seychelles", "MV": "Maldives", "KH": "Cambodia",
    "LK": "Sri Lanka", "PK": "Pakistan", "WS": "Samoa", "TO": "Tonga",
    "TV": "Tuvalu", "KI": "Kiribati", "MH": "Marshall Islands", "PW": "Palau",
    "AS": "American Samoa", "CK": "Cook Islands", "NU": "Niue", "PG": "Papua New Guinea",
    "VU": "Vanuatu", "SB": "Solomon Islands", "ST": "São Tomé & Príncipe",
}

API_TO_ELO_NAME = {
    "Czech Republic": "Czechia", "Korea Republic": "South Korea",
    "Republic of Korea": "South Korea", "USA": "United States",
    "Ivory Coast": "Côte d'Ivoire", "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Bosnia-Herzegovina": "Bosnia & Herzegovina", "DR Congo": "DR Congo",
    "Democratic Republic of Congo": "DR Congo", "Congo DR": "DR Congo",
    "Rep. of Ireland": "Republic of Ireland", "Trinidad and Tobago": "Trinidad & Tobago",
    "Cote d'Ivoire": "Côte d'Ivoire", "North Macedonia": "North Macedonia",
    "Republic of North Macedonia": "North Macedonia",
    "Türkiye": "Turkey", "Korea DPR": "North Korea",
    "Cape Verde Islands": "Cape Verde", "São Tomé and Príncipe": "São Tomé & Príncipe",
    "Saint Kitts and Nevis": "Saint Kitts & Nevis",
    "Saint Vincent and the Grenadines": "Saint Vincent & the Grenadines",
    "Antigua and Barbuda": "Antigua & Barbuda",
    "Trinidad & Tobago": "Trinidad & Tobago",
    "Kyrgyz Republic": "Kyrgyzstan",
}


@st.cache_data(ttl=3600)
def fetch_elorating_base():
    """Fetch current ELO base ratings from EloRating.net World.tsv."""
    try:
        r = requests.get(
            "https://www.eloratings.net/World.tsv",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        result = {}
        for line in r.text.split("\n"):
            parts = line.split("\t")
            if len(parts) >= 4:
                try:
                    code = parts[2].strip()
                    elo = int(parts[3])
                    name = ELO_CODE_TO_NAME.get(code)
                    if name:
                        result[name] = elo
                except Exception:
                    pass
        return result
    except Exception:
        return {}


def resolve_team_elo_name(api_name, base_ratings):
    """Map an API team name to its EloRating.net name."""
    if api_name in base_ratings:
        return api_name
    mapped = API_TO_ELO_NAME.get(api_name)
    if mapped and mapped in base_ratings:
        return mapped
    for elo_name in base_ratings:
        if elo_name.lower() == api_name.lower():
            return elo_name
    return None


def blend_base_ratings(base_ratings, manual_elos, weight=0.75):
    """Return a copy of base_ratings where teams with a manual ELO are blended:
       final = weight * manual + (1-weight) * elorating_net.
    Teams not in manual_elos are untouched.
    """
    if not manual_elos:
        return base_ratings or {}
    median = round(sum(base_ratings.values()) / len(base_ratings)) if base_ratings else 1500
    blended = dict(base_ratings or {})
    for team, manual_elo in manual_elos.items():
        ext = blended.get(team)
        if ext is None and base_ratings:
            elo_name = resolve_team_elo_name(team, base_ratings)
            ext = base_ratings.get(elo_name, median) if elo_name else median
        ext = ext or median
        blended[team] = round(weight * manual_elo + (1 - weight) * ext)
    return blended


def compute_elo(matches, k_base=32, home_advantage=100, initial_rating=1500, base_ratings=None):
    """Compute ELO ratings from a list of finished match dicts. Returns (ratings_dict, history_list)."""
    ratings = {}
    history = []
    median_base = round(sum(base_ratings.values()) / len(base_ratings)) if base_ratings else initial_rating

    sorted_matches = sorted(matches, key=lambda m: m.get("utc_date", ""))

    for match in sorted_matches:
        home_t = match.get("home_team") or {}
        away_t = match.get("away_team") or {}
        score = match.get("score") or {}
        home = home_t.get("name", "") if isinstance(home_t, dict) else ""
        away = away_t.get("name", "") if isinstance(away_t, dict) else ""
        hs = score.get("home") if isinstance(score, dict) else None
        as_ = score.get("away") if isinstance(score, dict) else None

        if not home or not away or hs is None or as_ is None:
            continue

        if home not in ratings:
            if base_ratings:
                elo_name = resolve_team_elo_name(home, base_ratings)
                ratings[home] = base_ratings.get(elo_name, median_base) if elo_name else median_base
            else:
                ratings[home] = initial_rating
        if away not in ratings:
            if base_ratings:
                elo_name = resolve_team_elo_name(away, base_ratings)
                ratings[away] = base_ratings.get(elo_name, median_base) if elo_name else median_base
            else:
                ratings[away] = initial_rating

        ra = ratings[home] + home_advantage
        rb = ratings[away]
        ea = 1 / (1 + 10 ** ((rb - ra) / 400))

        if hs > as_:
            sa, sb = 1, 0
        elif hs < as_:
            sa, sb = 0, 1
        else:
            sa, sb = 0.5, 0.5

        gd = abs(int(hs) - int(as_))
        gd_mult = 1 if gd <= 1 else (1.5 if gd == 2 else (11 + gd) / 8)

        delta = k_base * gd_mult * (sa - ea)
        ratings[home] = round(ratings[home] + delta, 1)
        ratings[away] = round(ratings[away] - delta, 1)

        date_str = match.get("utc_date", "")[:10]
        history.append({"date": date_str, "team": home, "elo": ratings[home],
                         "match": f"{home} {int(hs)}-{int(as_)} {away}"})
        history.append({"date": date_str, "team": away, "elo": ratings[away],
                         "match": f"{home} {int(hs)}-{int(as_)} {away}"})

    return ratings, history


def goals_supremacy_rating(team, all_matches, n=6):
    """Calculate goals supremacy rating for a team over their last n matches."""
    team_matches = [
        m for m in all_matches
        if (isinstance(m.get("home_team"), dict) and m["home_team"].get("name") == team)
        or (isinstance(m.get("away_team"), dict) and m["away_team"].get("name") == team)
    ]
    team_matches = sorted(team_matches, key=lambda m: m.get("utc_date", ""), reverse=True)[:n]

    if not team_matches:
        return None, 0, 0

    scored = 0
    conceded = 0
    for m in team_matches:
        score = m.get("score") or {}
        hs = score.get("home", 0) or 0
        as_ = score.get("away", 0) or 0
        home_name = (m.get("home_team") or {}).get("name", "")
        if home_name == team:
            scored += hs
            conceded += as_
        else:
            scored += as_
            conceded += hs

    rating = scored - conceded
    return rating, scored, conceded


def supremacy_to_probs(match_rating):
    """Convert goals supremacy match rating to result probabilities (from PDF formulas)."""
    x = match_rating
    p_home = 1.56 * x + 46.47
    p_away = 0.03 * x ** 2 - 1.27 * x + 23.65
    p_draw = -0.03 * x ** 2 - 0.29 * x + 29.48
    p_home = max(1, min(95, p_home))
    p_away = max(1, min(95, p_away))
    p_draw = max(1, min(95, p_draw))
    total = p_home + p_draw + p_away
    return round(p_home / total * 100, 1), round(p_draw / total * 100, 1), round(p_away / total * 100, 1)


def fair_odds(prob_pct):
    """Convert probability percentage to decimal fair odds."""
    if prob_pct <= 0:
        return None
    return round(100 / prob_pct, 2)


st.title("⚽ Football Analytics Dashboard")
st.caption("International competitions & top leagues — powered by TheStatsAPI")

st.sidebar.header("Filters")

_PAGE_LIST = [
    "📅 Calendrier CDM 2026",
    "🌍 Effectifs CM 2026",
    "🏅 Classement ELO",
    "🤖 Assistant IA",
]
_qp = st.query_params
_nav_page = _qp.get("page", None)
_nav_nation = _qp.get("nation", None)
_page_index = 0
if _nav_page == "effectifs":
    _page_index = 1

page = st.sidebar.radio(
    "Section",
    _PAGE_LIST,
    index=_page_index,
    label_visibility="visible",
)

active_competitions = ALL_CURATED
selected_group = "Toutes les compétitions"

_PAGES_WITHOUT_COMP_FILTER = {"🤖 Assistant IA", "🌍 Effectifs CM 2026", "📅 Calendrier CDM 2026"}

if page not in _PAGES_WITHOUT_COMP_FILTER:
    st.sidebar.markdown("---")
    st.sidebar.subheader("Catégorie")

    club_options = [k for k in COMPETITION_GROUPS if k in CLUB_GROUPS]
    national_options = [k for k in COMPETITION_GROUPS if k in NATIONAL_GROUPS]
    group_options = ["Toutes les compétitions"] + club_options + national_options

    selected_group = st.sidebar.radio(
        "Catégorie de compétition",
        group_options,
        label_visibility="collapsed",
    )

    if selected_group == "Toutes les compétitions":
        active_competitions = ALL_CURATED
    else:
        active_competitions = COMPETITION_GROUPS[selected_group]

comp_by_name = {c["name"]: c for c in active_competitions}
comp_by_id = {c["id"]: c for c in active_competitions}

st.sidebar.markdown("---")
st.sidebar.caption("Data refreshes every 5 minutes.")

if page == "🗓️ Match Results":
    st.header("🗓️ Résultats de Matchs")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        comp_choices = ["— Sélectionner une compétition —"] + [c["name"] for c in active_competitions]
        selected_comp_name = st.selectbox("Compétition", comp_choices)

    with col2:
        status_filter = st.selectbox("Statut", ["Tous", "finished", "scheduled", "in_progress"])

    with col3:
        page_num = st.number_input("Page", min_value=1, max_value=500, value=1)

    selected_comp_id = None
    if selected_comp_name != "— Sélectionner une compétition —":
        selected_comp_id = comp_by_name[selected_comp_name]["id"]

    status = None if status_filter == "Tous" else status_filter

    if selected_comp_id:
        comp_type = comp_by_name[selected_comp_name].get("type", "club")

        team_label = "Équipe nationale" if comp_type == "national" else "Club"
        with st.spinner(f"Chargement de toutes les équipes de {selected_comp_name}..."):
            teams_from_matches = get_all_teams_from_matches(selected_comp_id)

        team_filter_options = ["Toutes les équipes"] + teams_from_matches
        selected_team_filter = st.selectbox(f"Filtrer par {team_label} ({len(teams_from_matches)} disponibles)", team_filter_options)

        with st.spinner(f"Chargement des matchs..."):
            matches, meta = get_matches(competition_id=selected_comp_id, status=status, per_page=50, page=page_num)

        if matches:
            df = pd.DataFrame(matches)
            df["home_team_name"] = df["home_team"].apply(lambda x: x.get("name", "") if isinstance(x, dict) else "")
            df["away_team_name"] = df["away_team"].apply(lambda x: x.get("name", "") if isinstance(x, dict) else "")
            df["home_score"] = df["score"].apply(lambda x: x.get("home", 0) if isinstance(x, dict) else 0)
            df["away_score"] = df["score"].apply(lambda x: x.get("away", 0) if isinstance(x, dict) else 0)
            df["total_goals"] = df["home_score"] + df["away_score"]
            df["date"] = pd.to_datetime(df["utc_date"]).dt.date

            if selected_team_filter != "Toutes les équipes":
                df = df[(df["home_team_name"] == selected_team_filter) | (df["away_team_name"] == selected_team_filter)]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total matchs", meta.get("total", len(df)))
            c2.metric("Affichés", len(df))
            if status == "finished" and not df.empty:
                c3.metric("Buts moy./match", f"{df['total_goals'].mean():.1f}")
                c4.metric("≥ 4 buts", int((df["total_goals"] >= 4).sum()))

            if selected_team_filter != "Toutes les équipes":
                fin = df[df.apply(lambda r: r.get("status") == "finished" or True, axis=1)]
                wins = int(((fin["home_team_name"] == selected_team_filter) & (fin["home_score"] > fin["away_score"])).sum()
                           + ((fin["away_team_name"] == selected_team_filter) & (fin["away_score"] > fin["home_score"])).sum())
                draws = int(((fin["home_score"] == fin["away_score"]) & ((fin["home_team_name"] == selected_team_filter) | (fin["away_team_name"] == selected_team_filter))).sum())
                losses = len(fin) - wins - draws
                goals_for = int(((fin["home_team_name"] == selected_team_filter) * fin["home_score"]).sum()
                                + ((fin["away_team_name"] == selected_team_filter) * fin["away_score"]).sum())
                goals_against = int(((fin["home_team_name"] == selected_team_filter) * fin["away_score"]).sum()
                                    + ((fin["away_team_name"] == selected_team_filter) * fin["home_score"]).sum())

                st.markdown(f"### 📊 Bilan de **{selected_team_filter}**")
                s1, s2, s3, s4, s5 = st.columns(5)
                s1.metric("Victoires", wins)
                s2.metric("Nuls", draws)
                s3.metric("Défaites", losses)
                s4.metric("Buts marqués", goals_for)
                s5.metric("Buts encaissés", goals_against)

            st.markdown("---")

            if status == "finished" and not df.empty:
                tab1, tab2 = st.tabs(["📊 Analyse", "📋 Liste des matchs"])

                with tab1:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        goals_dist = df["total_goals"].value_counts().sort_index().reset_index()
                        goals_dist.columns = ["Buts", "Matchs"]
                        fig = px.bar(
                            goals_dist, x="Buts", y="Matchs",
                            color="Matchs", color_continuous_scale="Reds",
                            title="Distribution des buts par match",
                        )
                        fig.update_layout(showlegend=False)
                        st.plotly_chart(fig, width="stretch")

                    with col_b:
                        df["result"] = df.apply(
                            lambda r: "Victoire domicile" if r["home_score"] > r["away_score"]
                            else ("Victoire extérieur" if r["away_score"] > r["home_score"] else "Nul"),
                            axis=1,
                        )
                        result_counts = df["result"].value_counts().reset_index()
                        result_counts.columns = ["Résultat", "Matchs"]
                        fig = px.pie(
                            result_counts, names="Résultat", values="Matchs",
                            title="Répartition des résultats", hole=0.4,
                            color_discrete_map={"Victoire domicile": "#22c55e", "Victoire extérieur": "#ef4444", "Nul": "#f59e0b"},
                        )
                        st.plotly_chart(fig, width="stretch")

                    goals_by_day = df.groupby("date")["total_goals"].mean().reset_index()
                    goals_by_day.columns = ["Date", "Buts moy."]
                    if len(goals_by_day) > 1:
                        fig = px.line(
                            goals_by_day, x="Date", y="Buts moy.",
                            title="Buts moyens par match dans le temps", markers=True,
                        )
                        st.plotly_chart(fig, width="stretch")

                with tab2:
                    _display(df)
            else:
                _display(df)
        else:
            st.info("Aucun match trouvé pour ces filtres.")
    else:
        st.info("Sélectionne une compétition ci-dessus pour afficher les matchs.")
        st.markdown("### Compétitions disponibles dans cette catégorie")
        rows = [{"Compétition": c["name"], "Type": "🏆 Club" if c.get("type") == "club" else "🌍 Équipe Nationale", "Région": c["region"]} for c in active_competitions]
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


elif page == "👤 Players":
    st.header("👤 Effectifs & Profils Joueurs")

    col_left, col_right = st.columns([1, 3])

    with col_left:
        st.subheader("Filtres")

        comp_choices = [c["name"] for c in active_competitions]
        selected_comp_name = st.selectbox("Compétition", comp_choices)
        selected_comp_id = comp_by_name[selected_comp_name]["id"]

        with st.spinner("Chargement des équipes..."):
            teams, _ = get_teams(competition_id=selected_comp_id, per_page=50)

        team_options = {"Toutes les équipes": None}
        team_options.update({t["name"]: t["id"] for t in teams})

        selected_team_name = st.selectbox("Équipe", list(team_options.keys()))
        selected_team_id = team_options[selected_team_name]

        pos_filter = st.multiselect(
            "Filtrer par poste",
            ["Goalkeeper", "Defender", "Midfielder", "Forward"],
            default=[],
        )
        page_num = st.number_input("Page", min_value=1, max_value=100, value=1)

    with st.spinner("Chargement des joueurs..."):
        players, meta = get_players(team_id=selected_team_id, per_page=50, page=page_num)

    if players:
        df = pd.DataFrame(players)
        df["position_label"] = df["position"].apply(pos_label)
        df["age"] = pd.to_numeric(df["age"], errors="coerce")
        df["height_cm"] = pd.to_numeric(df["height_cm"], errors="coerce").replace(0, pd.NA)

        if "current_team" in df.columns:
            df["team_name"] = df["current_team"].apply(lambda x: x.get("name","") if isinstance(x, dict) else "")
            df["jersey"] = df["current_team"].apply(lambda x: x.get("jersey_number","") if isinstance(x, dict) else "")
        else:
            df["team_name"] = ""
            df["jersey"] = ""

        if pos_filter:
            df = df[df["position_label"].isin(pos_filter)]

        total = meta.get("total", len(df))
        avg_age = df["age"].dropna().mean()
        avg_height = df["height_cm"].dropna().mean()
        n_nat = df["nationality"].nunique()

        with col_right:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Joueurs", total)
            m2.metric("Âge moyen", f"{avg_age:.1f}" if pd.notna(avg_age) else "—")
            m3.metric("Taille moy.", f"{avg_height:.0f} cm" if pd.notna(avg_height) else "—")
            m4.metric("Nationalités", n_nat)

        st.markdown("---")

        tab1, tab2, tab3 = st.tabs(["📊 Analyse de l'effectif", "🗂️ Effectif par poste", "📋 Liste complète"])

        with tab1:
            col1, col2, col3 = st.columns(3)

            with col1:
                pos_counts = df["position_label"].value_counts().reset_index()
                pos_counts.columns = ["Poste", "Joueurs"]
                fig = px.pie(pos_counts, names="Poste", values="Joueurs", title="Répartition par poste", hole=0.4,
                             color_discrete_map={"Goalkeeper":"#f59e0b","Defender":"#3b82f6","Midfielder":"#22c55e","Forward":"#ef4444"})
                st.plotly_chart(fig, width="stretch")

            with col2:
                age_df = df.dropna(subset=["age"])
                if not age_df.empty:
                    fig = px.histogram(
                        age_df, x="age", nbins=20, title="Distribution des âges",
                        color_discrete_sequence=["#3b82f6"],
                        labels={"age": "Âge", "count": "Joueurs"},
                    )
                    fig.update_layout(bargap=0.1)
                    st.plotly_chart(fig, width="stretch")

            with col3:
                nat_counts = df["nationality"].value_counts().reset_index().head(10)
                nat_counts.columns = ["Nationalité", "Joueurs"]
                fig = px.bar(
                    nat_counts, x="Joueurs", y="Nationalité", orientation="h",
                    color="Joueurs", color_continuous_scale="Purples", title="Top nationalités",
                )
                fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
                st.plotly_chart(fig, width="stretch")

            col4, col5 = st.columns(2)

            with col4:
                height_df = df.dropna(subset=["height_cm", "position_label"])
                if not height_df.empty:
                    avg_by_pos = height_df.groupby("position_label")["height_cm"].mean().reset_index()
                    avg_by_pos.columns = ["Poste", "Taille moy. (cm)"]
                    fig = px.bar(avg_by_pos, x="Poste", y="Taille moy. (cm)",
                                 color="Poste", title="Taille moyenne par poste",
                                 color_discrete_map={"Goalkeeper":"#f59e0b","Defender":"#3b82f6","Midfielder":"#22c55e","Forward":"#ef4444"})
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, width="stretch")

            with col5:
                age_pos_df = df.dropna(subset=["age", "position_label"])
                if not age_pos_df.empty:
                    avg_age_pos = age_pos_df.groupby("position_label")["age"].mean().reset_index()
                    avg_age_pos.columns = ["Poste", "Âge moyen"]
                    fig = px.bar(avg_age_pos, x="Poste", y="Âge moyen",
                                 color="Poste", title="Âge moyen par poste",
                                 color_discrete_map={"Goalkeeper":"#f59e0b","Defender":"#3b82f6","Midfielder":"#22c55e","Forward":"#ef4444"})
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, width="stretch")

            height_age_df = df.dropna(subset=["height_cm", "age"])
            if not height_age_df.empty and len(height_age_df) > 5:
                fig = px.scatter(
                    height_age_df, x="age", y="height_cm", color="position_label",
                    hover_data=["name", "nationality"],
                    labels={"age": "Âge", "height_cm": "Taille (cm)", "position_label": "Poste"},
                    title="Taille vs Âge par poste",
                    color_discrete_map={"Goalkeeper":"#f59e0b","Defender":"#3b82f6","Midfielder":"#22c55e","Forward":"#ef4444"},
                )
                fig.update_layout(legend_title="Poste")
                st.plotly_chart(fig, width="stretch")

        with tab2:
            pos_order = ["Goalkeeper", "Defender", "Midfielder", "Forward", "Unknown"]
            pos_colors = {"Goalkeeper": "🟡", "Defender": "🔵", "Midfielder": "🟢", "Forward": "🔴", "Unknown": "⚪"}

            for pos in pos_order:
                pos_df = df[df["position_label"] == pos]
                if pos_df.empty:
                    continue
                st.markdown(f"### {pos_colors.get(pos,'⚪')} {pos}s ({len(pos_df)})")
                cols = st.columns(min(len(pos_df), 4))
                for i, (_, player) in enumerate(pos_df.iterrows()):
                    with cols[i % 4]:
                        jersey = f"#{player['jersey']}" if player.get('jersey') else ""
                        age = f"{int(player['age'])} ans" if pd.notna(player.get('age')) else "—"
                        height = f"{int(player['height_cm'])} cm" if pd.notna(player.get('height_cm')) else "—"
                        st.markdown(
                            f"""<div style='border:1px solid #e2e8f0;border-radius:8px;padding:10px;margin:4px 0;background:#f8fafc'>
                            <b>{player['name']}</b> <span style='color:#94a3b8'>{jersey}</span><br>
                            <span style='font-size:0.85em;color:#64748b'>{player.get('nationality','—')} · {age} · {height}</span>
                            </div>""",
                            unsafe_allow_html=True,
                        )
                st.markdown("")

        with tab3:
            cols_show = ["name", "jersey", "position_label", "age", "height_cm", "nationality"]
            if "team_name" in df.columns and df["team_name"].any():
                cols_show.append("team_name")
            cols_show = [c for c in cols_show if c in df.columns]
            display_df = df[cols_show].copy()
            display_df.columns = [
                {"name": "Nom", "jersey": "Maillot", "position_label": "Poste",
                 "age": "Âge", "height_cm": "Taille (cm)", "nationality": "Nationalité",
                 "team_name": "Équipe"}.get(c, c)
                for c in cols_show
            ]
            st.dataframe(display_df, width="stretch", hide_index=True)
    else:
        st.info("Aucun joueur trouvé. Sélectionne une équipe dans les filtres.")

elif page == "🏅 Classement ELO":
    st.header("🏅 Classement ELO")
    st.caption("Ratings cumulatifs calculés sur l'ensemble des matchs terminés — basé sur l'algorithme ELO avec avantage domicile et multiplicateur de goal difference.")

    if "manual_elos" not in st.session_state:
        st.session_state.manual_elos = {}

    comp_choices_elo = [ALL_NATIONAL_OPTION] + [c["name"] for c in active_competitions]
    selected_comp_name_elo = st.selectbox("Compétition pour le calcul ELO", comp_choices_elo, key="elo_comp")

    col_settings, col_main = st.columns([1, 3])
    with col_settings:
        k_factor = st.slider("Facteur K (sensibilité)", 10, 60, 32, help="K élevé = ratings plus volatils, K faible = plus stables")
        home_adv = st.slider("Avantage domicile (pts)", 0, 200, 100, help="Points ajoutés à l'équipe à domicile dans le calcul ELO")
        top_n = st.slider("Top N équipes à afficher", 5, 50, 20)

    is_national_comp = (
        selected_comp_name_elo == ALL_NATIONAL_OPTION
        or comp_by_name.get(selected_comp_name_elo, {}).get("type") == "national"
    )

    if selected_comp_name_elo == ALL_NATIONAL_OPTION:
        with st.spinner("Agrégation des matchs de toutes les compétitions nationales..."):
            all_finished = get_all_national_matches()
        elo_label = "Toutes équipes nationales"
    else:
        selected_comp_id_elo = comp_by_name[selected_comp_name_elo]["id"]
        with st.spinner(f"Calcul ELO sur tous les matchs de {selected_comp_name_elo}..."):
            all_finished = get_all_matches_for_competition(selected_comp_id_elo)
        elo_label = selected_comp_name_elo

    base_ratings = None
    elorating_base = {}
    if is_national_comp:
        with st.spinner("Récupération des ratings de base depuis EloRating.net..."):
            elorating_base = fetch_elorating_base()
        base_ratings = elorating_base if elorating_base else None

    effective_base = blend_base_ratings(base_ratings, st.session_state.get("manual_elos", {}))

    if not all_finished:
        st.warning("Aucun match terminé trouvé pour cette compétition.")
    else:
        elo_ratings, elo_history = compute_elo(
            all_finished, k_base=k_factor, home_advantage=home_adv, base_ratings=effective_base
        )
        n_matches = len(all_finished)
        n_teams = len(elo_ratings)

        dates = sorted([m.get("utc_date", "")[:10] for m in all_finished if m.get("utc_date")])
        oldest_date = dates[0] if dates else "—"
        newest_date = dates[-1] if dates else "—"
        if dates:
            from datetime import date
            try:
                y_old = int(oldest_date[:4])
                y_new = int(newest_date[:4])
                n_years = y_new - y_old + 1
                period_str = f"{oldest_date[:7]} → {newest_date[:7]}"
            except Exception:
                n_years = 0
                period_str = "—"
        else:
            n_years, period_str = 0, "—"

        with col_main:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Matchs analysés", n_matches)
            m2.metric("Équipes classées", n_teams)
            m3.metric("Meilleur rating", f"{max(elo_ratings.values()):.0f}" if elo_ratings else "—")
            if base_ratings:
                matched = sum(
                    1 for t in elo_ratings
                    if resolve_team_elo_name(t, base_ratings) is not None
                )
                m4.metric("Ancrées EloRating.net", f"{matched}/{n_teams}")
            else:
                m4.metric("Période couverte", f"~{n_years} ans" if n_years else "—")

        info_parts = [f"📅 Données du **{period_str}** ({n_matches} matchs)"]
        if base_ratings:
            info_parts.append(
                f"📡 Base EloRating.net ({len(elorating_base)} équipes) — ratings initiaux officiels, ajustés avec les résultats récents."
            )
        st.info("  \n".join(info_parts))

        st.markdown("---")
        tab_rank, tab_hist, tab_h2h, tab_manual = st.tabs(["🏆 Classement", "📈 Évolution ELO", "⚔️ Tête-à-tête", "⚙️ ELO Manuels"])

        ref_line = round(sum(effective_base.values()) / len(effective_base)) if effective_base else 1500
        ref_label = f"Médiane EloRating.net ({ref_line})" if base_ratings else "Base 1500"
        n_manual_active = len(st.session_state.get("manual_elos", {}))

        with tab_rank:
            sorted_teams = sorted(elo_ratings.items(), key=lambda x: x[1], reverse=True)
            rank_df = pd.DataFrame(sorted_teams[:top_n], columns=["Équipe", "ELO ajusté"])
            rank_df.insert(0, "Rang", range(1, len(rank_df) + 1))
            rank_df["ELO ajusté"] = rank_df["ELO ajusté"].round(0).astype(int)

            if base_ratings:
                def get_base(team_name):
                    elo_name = resolve_team_elo_name(team_name, base_ratings)
                    return base_ratings.get(elo_name, ref_line) if elo_name else ref_line

                rank_df["Base EloRating.net"] = rank_df["Équipe"].apply(get_base)
                rank_df["Variation"] = rank_df["ELO ajusté"] - rank_df["Base EloRating.net"]
                rank_df["Variation"] = rank_df["Variation"].apply(lambda x: f"+{x}" if x > 0 else str(x))
            else:
                rank_df["Écart vs base"] = rank_df["ELO ajusté"] - 1500

            if base_ratings:
                st.dataframe(
                    rank_df[["Rang", "Équipe", "ELO ajusté", "Base EloRating.net", "Variation"]],
                    use_container_width=True, hide_index=True
                )
            else:
                st.dataframe(rank_df[["Rang", "Équipe", "ELO ajusté", "Écart vs base"]], use_container_width=True, hide_index=True)

        with tab_hist:
            if elo_history:
                hist_df = pd.DataFrame(elo_history)
                hist_df["date"] = pd.to_datetime(hist_df["date"])
                all_team_names = sorted(elo_ratings.keys(), key=lambda t: -elo_ratings[t])
                default_teams = all_team_names[:5]
                selected_teams_hist = st.multiselect(
                    "Équipes à afficher", all_team_names, default=default_teams, key="elo_hist_teams"
                )
                if selected_teams_hist:
                    hist_filtered = hist_df[hist_df["team"].isin(selected_teams_hist)]
                    fig = px.line(
                        hist_filtered, x="date", y="elo", color="team",
                        title="Évolution du rating ELO dans le temps",
                        labels={"date": "Date", "elo": "Rating ELO", "team": "Équipe"},
                        hover_data=["match"],
                    )
                    fig.add_hline(y=ref_line, line_dash="dash", line_color="gray", annotation_text=ref_label)
                    st.plotly_chart(fig, width="stretch")

        with tab_h2h:
            st.markdown("#### Comparaison Tête-à-tête")
            all_team_names_sorted = sorted(elo_ratings.keys(), key=lambda t: -elo_ratings[t])
            c1, c2 = st.columns(2)
            with c1:
                team_a = st.selectbox("Équipe A", all_team_names_sorted, key="h2h_a")
            with c2:
                team_b = st.selectbox("Équipe B", all_team_names_sorted, index=1, key="h2h_b")

            if team_a and team_b and team_a != team_b:
                ra_computed = elo_ratings.get(team_a, ref_line)
                rb_computed = elo_ratings.get(team_b, ref_line)
                rank_a = all_team_names_sorted.index(team_a) + 1
                rank_b = all_team_names_sorted.index(team_b) + 1

                st.markdown("##### ⚙️ Ajustements pour ce match")
                adj1, adj2, adj3 = st.columns(3)
                with adj1:
                    ra = st.number_input(
                        f"ELO {team_a}",
                        min_value=500, max_value=2500,
                        value=int(ra_computed), step=1, key="h2h_ra_override",
                        help=f"ELO calculé par simulation : {int(ra_computed)}"
                    )
                with adj2:
                    rb = st.number_input(
                        f"ELO {team_b}",
                        min_value=500, max_value=2500,
                        value=int(rb_computed), step=1, key="h2h_rb_override",
                        help=f"ELO calculé par simulation : {int(rb_computed)}"
                    )
                with adj3:
                    home_adv_h2h = st.slider(
                        "Avantage domicile (match)",
                        0, 300, int(home_adv), step=5, key="h2h_home_adv",
                        help="Override l'avantage domicile global pour cette confrontation"
                    )
                if ra != int(ra_computed) or rb != int(rb_computed) or home_adv_h2h != home_adv:
                    st.caption(f"🔧 Valeurs modifiées — simulation : {team_a} {int(ra_computed)} | {team_b} {int(rb_computed)} | avantage dom. global {home_adv}")

                ra_home = ra + home_adv_h2h
                ea = 1 / (1 + 10 ** ((rb - ra_home) / 400))
                eb = 1 - ea

                if base_ratings:
                    base_a = base_ratings.get(resolve_team_elo_name(team_a, base_ratings), ref_line) if resolve_team_elo_name(team_a, base_ratings) else ref_line
                    base_b = base_ratings.get(resolve_team_elo_name(team_b, base_ratings), ref_line) if resolve_team_elo_name(team_b, base_ratings) else ref_line
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric(f"ELO final {team_a}", f"{ra}", f"{ra - base_a:+.0f} vs EloRating.net")
                    mc2.metric(f"ELO final {team_b}", f"{rb}", f"{rb - base_b:+.0f} vs EloRating.net")
                    mc3.metric("Différence", f"{abs(ra - rb):.0f} pts", f"{'Avantage ' + team_a if ra > rb else 'Avantage ' + team_b}")
                    st.caption(f"Base EloRating.net → {team_a}: **{base_a:.0f}** | {team_b}: **{base_b:.0f}**")
                else:
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric(f"ELO {team_a}", f"{ra}", f"#{rank_a}")
                    mc2.metric(f"ELO {team_b}", f"{rb}", f"#{rank_b}")
                    mc3.metric("Différence", f"{abs(ra - rb):.0f} pts", f"{'Avantage ' + team_a if ra > rb else 'Avantage ' + team_b}")

                st.markdown(f"**Si {team_a} joue à domicile contre {team_b} (avantage dom. {home_adv_h2h} pts) :**")
                pc1, pc2, pc3 = st.columns(3)
                pc1.metric(f"Victoire {team_a}", f"{ea*100:.1f}%", f"Cote équitable: {fair_odds(ea*100)}")
                pc2.metric("Nul (approx.)", "≈ ?", "Non calculé par l'ELO seul")
                pc3.metric(f"Victoire {team_b}", f"{eb*100:.1f}%", f"Cote équitable: {fair_odds(eb*100)}")

                h2h_matches = [
                    m for m in all_finished
                    if (isinstance(m.get("home_team"), dict) and isinstance(m.get("away_team"), dict))
                    and ((m["home_team"].get("name") == team_a and m["away_team"].get("name") == team_b)
                         or (m["home_team"].get("name") == team_b and m["away_team"].get("name") == team_a))
                ]
                if h2h_matches:
                    st.markdown(f"**Historique direct ({len(h2h_matches)} matchs) :**")
                    h2h_df = pd.DataFrame([{
                        "Date": m.get("utc_date", "")[:10],
                        "Domicile": m["home_team"]["name"],
                        "Score": f"{(m.get('score') or {}).get('home', '?')} - {(m.get('score') or {}).get('away', '?')}",
                        "Extérieur": m["away_team"]["name"],
                    } for m in sorted(h2h_matches, key=lambda x: x.get("utc_date", ""), reverse=True)])
                    st.dataframe(h2h_df, width="stretch", hide_index=True)
                else:
                    st.info("Aucun match direct entre ces deux équipes dans les données disponibles.")

        with tab_manual:
            st.markdown("#### ⚙️ ELO Manuels")
            st.caption(
                "Saisir un ELO manuel pour une équipe. "
                "L'ELO de départ final est calculé comme : **75% ELO manuel + 25% EloRating.net**. "
                "Ces valeurs affectent l'ensemble de la simulation (classement, historique, tête-à-tête)."
            )

            n_active = len(st.session_state.get("manual_elos", {}))
            if n_active:
                st.success(f"✅ {n_active} équipe(s) avec ELO manuel actif — simulation recalculée avec ces valeurs.")

            all_teams_for_manual = sorted(elo_ratings.keys(), key=lambda t: -elo_ratings[t])
            manual_rows = []
            for team in all_teams_for_manual:
                elo_net_val = ref_line
                if base_ratings:
                    elo_name = resolve_team_elo_name(team, base_ratings)
                    elo_net_val = int(base_ratings.get(elo_name, ref_line)) if elo_name else ref_line
                manual_val = st.session_state.get("manual_elos", {}).get(team, None)
                elo_final = round(0.75 * manual_val + 0.25 * elo_net_val) if manual_val else elo_net_val
                manual_rows.append({
                    "Équipe": team,
                    "ELO EloRating.net": elo_net_val,
                    "ELO Manuel": manual_val if manual_val else None,
                    "ELO de départ (75/25)": elo_final,
                    "ELO simulé final": int(elo_ratings.get(team, ref_line)),
                })

            manual_df_input = pd.DataFrame(manual_rows)

            with st.form("form_manual_elos"):
                st.markdown("**Modifie la colonne « ELO Manuel » puis clique sur Appliquer.**")
                edited = st.data_editor(
                    manual_df_input,
                    column_config={
                        "Équipe": st.column_config.TextColumn("Équipe", disabled=True),
                        "ELO EloRating.net": st.column_config.NumberColumn("EloRating.net", disabled=True),
                        "ELO Manuel": st.column_config.NumberColumn(
                            "ELO Manuel ✏️",
                            min_value=500, max_value=2500, step=1,
                            help="Laisser vide pour utiliser uniquement EloRating.net"
                        ),
                        "ELO de départ (75/25)": st.column_config.NumberColumn("Départ simulé (75/25)", disabled=True),
                        "ELO simulé final": st.column_config.NumberColumn("ELO après simulation", disabled=True),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key="manual_elo_editor_form",
                    num_rows="fixed",
                )
                col_apply, col_reset = st.columns([1, 1])
                with col_apply:
                    submitted = st.form_submit_button("✅ Appliquer les ELO manuels", type="primary")
                with col_reset:
                    reset = st.form_submit_button("🗑️ Réinitialiser tout")

            if submitted:
                new_manual = {}
                for _, row in edited.iterrows():
                    val = row["ELO Manuel"]
                    if val is not None and not (isinstance(val, float) and pd.isna(val)):
                        new_manual[row["Équipe"]] = int(val)
                st.session_state.manual_elos = new_manual
                st.rerun()

            if reset:
                st.session_state.manual_elos = {}
                st.rerun()


elif page == "🎯 Prédiction de Matchs":
    st.header("🎯 Prédiction de Matchs")
    st.caption("Système de prédiction basé sur la supériorité de buts des 6 derniers matchs — formules de conversion probabilité tirées du document Football-Data © 2003.")

    comp_choices_pred = [ALL_NATIONAL_OPTION] + [c["name"] for c in active_competitions]
    selected_comp_name_pred = st.selectbox("Compétition", comp_choices_pred, key="pred_comp")

    if selected_comp_name_pred == ALL_NATIONAL_OPTION:
        with st.spinner("Agrégation de toutes les compétitions nationales..."):
            all_finished_pred = get_all_national_matches()
            scheduled_matches = get_all_national_scheduled()
        st.info(f"Pool global : {len(all_finished_pred)} matchs de toutes les compétitions nationales")
    else:
        selected_comp_id_pred = comp_by_name[selected_comp_name_pred]["id"]
        with st.spinner("Chargement de l'historique des matchs..."):
            all_finished_pred = get_all_matches_for_competition(selected_comp_id_pred)
            scheduled_matches = get_scheduled_matches_for_competition(selected_comp_id_pred)

    tab_upcoming, tab_custom = st.tabs(["📅 Matchs à venir", "🔧 Prédiction personnalisée"])

    with tab_upcoming:
        if not scheduled_matches:
            st.info("Aucun match à venir trouvé. Tu peux utiliser la prédiction personnalisée ci-dessous.")
        else:
            st.markdown(f"**{len(scheduled_matches)} matchs à venir** — prédictions basées sur les 6 derniers matchs joués")
            pred_rows = []
            for m in sorted(scheduled_matches, key=lambda x: x.get("utc_date", ""))[:30]:
                home = (m.get("home_team") or {}).get("name", "")
                away = (m.get("away_team") or {}).get("name", "")
                date = m.get("utc_date", "")[:10]
                if not home or not away:
                    continue

                h_rat, h_sc, h_cc = goals_supremacy_rating(home, all_finished_pred)
                a_rat, a_sc, a_cc = goals_supremacy_rating(away, all_finished_pred)

                if h_rat is None or a_rat is None:
                    continue

                match_rating = h_rat - a_rat
                ph, pd_, pa = supremacy_to_probs(match_rating)
                pred_rows.append({
                    "Date": date,
                    "Domicile": home,
                    "Extérieur": away,
                    "Rating dom.": h_rat,
                    "Rating ext.": a_rat,
                    "Match rating": round(match_rating, 1),
                    "% Victoire dom.": ph,
                    "% Nul": pd_,
                    "% Victoire ext.": pa,
                    "Cote dom.": fair_odds(ph),
                    "Cote nul": fair_odds(pd_),
                    "Cote ext.": fair_odds(pa),
                })

            if pred_rows:
                pred_df = pd.DataFrame(pred_rows)

                def color_pct(val):
                    if not isinstance(val, (int, float)):
                        return ""
                    if val >= 50:
                        intensity = int(80 + (val - 50) / 50 * 120)
                        return f"background-color: rgb(50,{intensity},50); color: white"
                    else:
                        intensity = int(80 + (50 - val) / 50 * 120)
                        return f"background-color: rgb({intensity},50,50); color: white"

                st.dataframe(
                    pred_df.style.applymap(color_pct, subset=["% Victoire dom.", "% Victoire ext."]),
                    width="stretch", hide_index=True,
                )
            else:
                st.info("Pas assez de données pour calculer les prédictions (6 matchs min. requis par équipe).")

    with tab_custom:
        st.markdown("#### Prédiction pour un match spécifique")
        all_pred_teams = sorted(set(
            (m.get("home_team") or {}).get("name", "")
            for m in all_finished_pred
            if (m.get("home_team") or {}).get("name")
        ) | set(
            (m.get("away_team") or {}).get("name", "")
            for m in all_finished_pred
            if (m.get("away_team") or {}).get("name")
        ))

        if len(all_pred_teams) < 2:
            st.info("Pas assez de données pour cette compétition.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                home_team_pred = st.selectbox("Équipe Domicile", all_pred_teams, key="pred_home")
            with c2:
                away_team_pred = st.selectbox("Équipe Extérieur", all_pred_teams, index=min(1, len(all_pred_teams)-1), key="pred_away")

            n_matches_pred = st.slider("Nombre de matchs récents à analyser", 3, 10, 6, key="pred_n")

            if home_team_pred != away_team_pred:
                h_rat, h_sc, h_cc = goals_supremacy_rating(home_team_pred, all_finished_pred, n=n_matches_pred)
                a_rat, a_sc, a_cc = goals_supremacy_rating(away_team_pred, all_finished_pred, n=n_matches_pred)

                if h_rat is not None and a_rat is not None:
                    match_rating = h_rat - a_rat
                    ph, pd_, pa = supremacy_to_probs(match_rating)

                    st.markdown("---")
                    st.markdown(f"### {home_team_pred} vs {away_team_pred}")

                    col_stats, col_probs = st.columns(2)
                    with col_stats:
                        st.markdown("**Forme récente (supériorité de buts)**")
                        st.markdown(f"- **{home_team_pred}** : {h_sc} buts pour / {h_cc} contre → rating **{h_rat:+d}**")
                        st.markdown(f"- **{away_team_pred}** : {a_sc} buts pour / {a_cc} contre → rating **{a_rat:+d}**")
                        st.markdown(f"- **Match rating** : {h_rat:+d} − ({a_rat:+d}) = **{match_rating:+.1f}**")

                    with col_probs:
                        st.markdown("**Probabilités prédites**")
                        p1, p2, p3 = st.columns(3)
                        p1.metric(f"Victoire {home_team_pred}", f"{ph}%", f"Cote: {fair_odds(ph)}")
                        p2.metric("Nul", f"{pd_}%", f"Cote: {fair_odds(pd_)}")
                        p3.metric(f"Victoire {away_team_pred}", f"{pa}%", f"Cote: {fair_odds(pa)}")

                    fig = px.bar(
                        pd.DataFrame({"Résultat": [f"Victoire {home_team_pred}", "Nul", f"Victoire {away_team_pred}"],
                                      "Probabilité (%)": [ph, pd_, pa]}),
                        x="Résultat", y="Probabilité (%)",
                        color="Résultat",
                        color_discrete_map={
                            f"Victoire {home_team_pred}": "#22c55e",
                            "Nul": "#f59e0b",
                            f"Victoire {away_team_pred}": "#ef4444",
                        },
                        title="Distribution des probabilités",
                    )
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, width="stretch")
                else:
                    st.warning("Pas assez de matchs joués pour calculer les ratings de ces équipes.")


elif page == "💰 Comparaison de Cotes":
    st.header("💰 Comparaison de Cotes")
    st.caption("Compare les cotes équitables calculées par le modèle de supériorité de buts avec les cotes de ton bookmaker. Une cote bookmaker supérieure à la cote équitable indique un pari potentiellement à valeur.")

    comp_choices_cotes = [ALL_NATIONAL_OPTION] + [c["name"] for c in active_competitions]
    selected_comp_name_cotes = st.selectbox("Compétition", comp_choices_cotes, key="cotes_comp")

    if selected_comp_name_cotes == ALL_NATIONAL_OPTION:
        with st.spinner("Agrégation de toutes les compétitions nationales..."):
            all_finished_cotes = get_all_national_matches()
        st.info(f"Pool global : {len(all_finished_cotes)} matchs de toutes les compétitions nationales")
    else:
        selected_comp_id_cotes = comp_by_name[selected_comp_name_cotes]["id"]
        with st.spinner("Chargement des données..."):
            all_finished_cotes = get_all_matches_for_competition(selected_comp_id_cotes)

    all_cotes_teams = sorted(set(
        (m.get("home_team") or {}).get("name", "")
        for m in all_finished_cotes
        if (m.get("home_team") or {}).get("name")
    ) | set(
        (m.get("away_team") or {}).get("name", "")
        for m in all_finished_cotes
        if (m.get("away_team") or {}).get("name")
    ))

    if len(all_cotes_teams) < 2:
        st.info("Pas assez de données pour cette compétition.")
    else:
        c1, c2 = st.columns(2)
        with c1:
            home_cotes = st.selectbox("Équipe Domicile", all_cotes_teams, key="cotes_home")
        with c2:
            away_cotes = st.selectbox("Équipe Extérieur", all_cotes_teams, index=min(1, len(all_cotes_teams)-1), key="cotes_away")

        n_cotes = st.slider("Matchs récents à analyser", 3, 10, 6, key="cotes_n")

        if home_cotes != away_cotes:
            h_rat, h_sc, h_cc = goals_supremacy_rating(home_cotes, all_finished_cotes, n=n_cotes)
            a_rat, a_sc, a_cc = goals_supremacy_rating(away_cotes, all_finished_cotes, n=n_cotes)

            if h_rat is not None and a_rat is not None:
                match_rating = h_rat - a_rat
                ph, pd_, pa = supremacy_to_probs(match_rating)
                fo_home = fair_odds(ph)
                fo_draw = fair_odds(pd_)
                fo_away = fair_odds(pa)

                st.markdown("---")
                st.markdown(f"### {home_cotes} vs {away_cotes}")
                st.markdown(f"Match rating : **{match_rating:+.1f}** (dom. {h_rat:+d} vs ext. {a_rat:+d})")

                st.markdown("#### Cotes équitables calculées par le modèle")
                eq1, eq2, eq3 = st.columns(3)
                eq1.metric(f"Victoire {home_cotes}", f"{ph}%", f"Cote équitable : **{fo_home}**")
                eq2.metric("Nul", f"{pd_}%", f"Cote équitable : **{fo_draw}**")
                eq3.metric(f"Victoire {away_cotes}", f"{pa}%", f"Cote équitable : **{fo_away}**")

                st.markdown("---")

                # ── BSD API : cotes réelles en direct ──────────────────
                bsd_odds = get_bsd_odds_for_match(home_cotes, away_cotes)

                if bsd_odds:
                    st.success(
                        f"📡 **Cotes BSD API trouvées** — Match du {bsd_odds.get('event_date', 'N/A')} "
                        f"({bsd_odds.get('league', 'N/A')}) — pré-chargées automatiquement",
                        icon="📡",
                    )
                    bsd_default_home = float(bsd_odds.get("home") or fo_home or 2.0)
                    bsd_default_draw = float(bsd_odds.get("draw") or fo_draw or 3.0)
                    bsd_default_away = float(bsd_odds.get("away") or fo_away or 4.0)

                    # Afficher les cotes O/U et BTTS si disponibles
                    with st.expander("📊 Plus de cotes BSD (O/U, BTTS, xG)", expanded=False):
                        bc1, bc2, bc3 = st.columns(3)
                        if bsd_odds.get("over25"):
                            bc1.metric("+ 2.5 buts", f"{bsd_odds['over25']}")
                        if bsd_odds.get("under25"):
                            bc1.metric("- 2.5 buts", f"{bsd_odds['under25']}")
                        if bsd_odds.get("over15"):
                            bc2.metric("+ 1.5 buts", f"{bsd_odds['over15']}")
                        if bsd_odds.get("over35"):
                            bc2.metric("+ 3.5 buts", f"{bsd_odds['over35']}")
                        if bsd_odds.get("btts_yes"):
                            bc3.metric("Les deux équipes marquent (oui)", f"{bsd_odds['btts_yes']}")
                        if bsd_odds.get("btts_no"):
                            bc3.metric("Les deux équipes marquent (non)", f"{bsd_odds['btts_no']}")
                        if bsd_odds.get("xg_home") or bsd_odds.get("xg_away"):
                            xgc1, xgc2 = st.columns(2)
                            xgc1.metric("xG Domicile", f"{bsd_odds.get('xg_home', '—')}")
                            xgc2.metric("xG Extérieur", f"{bsd_odds.get('xg_away', '—')}")
                else:
                    st.info(
                        "ℹ️ Aucune cote BSD API disponible pour ce match "
                        "(match non programmé dans les 2-3 prochains jours). "
                        "Saisis les cotes manuellement.",
                        icon="ℹ️",
                    )
                    bsd_default_home = float(fo_home) if fo_home else 2.0
                    bsd_default_draw = float(fo_draw) if fo_draw else 3.0
                    bsd_default_away = float(fo_away) if fo_away else 4.0

                st.markdown("#### Cotes bookmaker (modifiables)")
                st.caption("Pré-remplies depuis BSD API si disponible, sinon depuis le modèle. Modifie si besoin.")
                b1, b2, b3 = st.columns(3)
                with b1:
                    bk_home = st.number_input(f"Cote {home_cotes}", min_value=1.01, max_value=100.0,
                                               value=max(1.01, bsd_default_home), step=0.05, format="%.2f", key="bk_home")
                with b2:
                    bk_draw = st.number_input("Cote Nul", min_value=1.01, max_value=100.0,
                                               value=max(1.01, bsd_default_draw), step=0.05, format="%.2f", key="bk_draw")
                with b3:
                    bk_away = st.number_input(f"Cote {away_cotes}", min_value=1.01, max_value=100.0,
                                               value=max(1.01, bsd_default_away), step=0.05, format="%.2f", key="bk_away")

                st.markdown("---")
                st.markdown("#### Analyse de valeur")

                bk_implied_home = round(100 / bk_home, 1)
                bk_implied_draw = round(100 / bk_draw, 1)
                bk_implied_away = round(100 / bk_away, 1)
                overround = round(bk_implied_home + bk_implied_draw + bk_implied_away - 100, 1)

                def value_analysis(result_label, model_prob, bk_odd, bk_implied):
                    edge = round(model_prob - bk_implied, 1)
                    is_value = bk_odd > fair_odds(model_prob) if fair_odds(model_prob) else False
                    status = "✅ Valeur !" if is_value else "❌ Pas de valeur"
                    return {
                        "Résultat": result_label,
                        "Prob. modèle": f"{model_prob}%",
                        "Prob. implicite bookmaker": f"{bk_implied}%",
                        "Cote bookmaker": bk_odd,
                        "Cote équitable": fair_odds(model_prob),
                        "Avantage modèle": f"{edge:+.1f}%",
                        "Valeur ?": status,
                    }

                analysis_data = [
                    value_analysis(f"Victoire {home_cotes}", ph, bk_home, bk_implied_home),
                    value_analysis("Nul", pd_, bk_draw, bk_implied_draw),
                    value_analysis(f"Victoire {away_cotes}", pa, bk_away, bk_implied_away),
                ]
                analysis_df = pd.DataFrame(analysis_data)
                st.dataframe(analysis_df, width="stretch", hide_index=True)

                st.markdown(f"**Overround bookmaker :** {overround:+.1f}% (marge prélevée par le bookmaker)")

                fig = px.bar(
                    pd.DataFrame({
                        "Résultat": [f"Vic. {home_cotes}", "Nul", f"Vic. {away_cotes}"],
                        "Modèle (%)": [ph, pd_, pa],
                        "Bookmaker (%)": [bk_implied_home, bk_implied_draw, bk_implied_away],
                    }).melt(id_vars="Résultat", var_name="Source", value_name="Probabilité (%)"),
                    x="Résultat", y="Probabilité (%)", color="Source", barmode="group",
                    title="Probabilités : modèle vs bookmaker",
                    color_discrete_map={"Modèle (%)": "#3b82f6", "Bookmaker (%)": "#f59e0b"},
                )
                st.plotly_chart(fig, width="stretch")
            else:
                st.warning("Pas assez de données pour calculer les ratings.")


elif page == "🤖 Assistant IA":
    st.header("🤖 Assistant Football IA")
    st.caption("Posez vos questions sur le football, les stats, les équipes ou les compétitions. Alimenté par Claude (Anthropic).")

    SYSTEM_PROMPT = """Tu es un expert en football et en analyse sportive. 
Tu connais les compétitions internationales (Ligue des Champions, Europa League, Copa América, Coupe du Monde, qualifications, etc.), 
les ligues domestiques majeures (Premier League, Bundesliga, Ligue 1, Serie A), 
les statistiques, les tactiques, et l'histoire du football.
Réponds de manière concise, précise et engageante.
Si l'utilisateur pose une question en français, réponds en français. 
Si la question est en anglais, réponds en anglais."""

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    col_chat, col_info = st.columns([3, 1])

    with col_info:
        st.markdown("**Exemples de questions**")
        examples = [
            "Qui a gagné la Champions League 2024 ?",
            "Explique-moi le système de qualification pour la Coupe du Monde.",
            "Quelles sont les meilleures équipes du groupe A ?",
            "Compare le style de jeu du Bayern et de Manchester City.",
            "Qu'est-ce que l'expected goals (xG) ?",
        ]
        for ex in examples:
            if st.button(ex, key=f"ex_{ex[:20]}", use_container_width=True):
                st.session_state.pending_example = ex
                st.rerun()

        st.markdown("---")
        if st.button("Effacer la conversation", use_container_width=True):
            st.session_state.chat_messages = []
            st.rerun()

    with col_chat:
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        user_input = st.chat_input("Posez votre question football...")

        if "pending_example" in st.session_state:
            user_input = st.session_state.pending_example
            del st.session_state.pending_example

        if user_input:
            st.session_state.chat_messages.append({"role": "user", "content": user_input})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(user_input)

            with chat_container:
                with st.chat_message("assistant"):
                    placeholder = st.empty()
                    full_response = ""

                    try:
                        client = get_claude_client()
                        history = [
                            {"role": m["role"], "content": m["content"]}
                            for m in st.session_state.chat_messages[:-1]
                        ]
                        history.append({"role": "user", "content": user_input})

                        with client.messages.stream(
                            model="claude-sonnet-4-6",
                            max_tokens=1024,
                            system=SYSTEM_PROMPT,
                            messages=history,
                        ) as stream:
                            for text in stream.text_stream:
                                full_response += text
                                placeholder.markdown(full_response + "▌")
                        placeholder.markdown(full_response)

                    except Exception as e:
                        full_response = f"Erreur lors de la connexion à Claude : {e}"
                        placeholder.error(full_response)

            st.session_state.chat_messages.append({"role": "assistant", "content": full_response})

# ═══════════════════════════════════════════════════════════════════
# PAGE : 🌍 Effectifs CM 2026
# ═══════════════════════════════════════════════════════════════════
elif page == "📅 Calendrier CDM 2026":
    st.header("📅 Calendrier — Coupe du Monde 2026")
    st.caption("🇺🇸🇨🇦🇲🇽 États-Unis · Canada · Mexique — 11 juin au 19 juillet 2026 — Données BSD Sports")

    BSD_BASE_URL = "https://sports.bzzoiro.com/api"
    BSD_KEY = os.environ.get("BSD_API_KEY", "")
    BSD_HEADERS = {"Authorization": f"Token {BSD_KEY}"}

    ROUND_LABELS = {
        1: "Journée 1", 2: "Journée 2", 3: "Journée 3",
        6: "🏆 Huitièmes de finale", 5: "🏆 Quarts de finale",
        27: "🏆 Demi-finales", 50: "🥉 Match pour la 3e place",
        28: "🥇 Finale", 29: "🥇 Finale",
    }

    ROUND_ORDER = [1, 2, 3, 6, 5, 27, 50, 28, 29]

    COUNTRY_ISO = {
        "Mexico": "mx", "South Africa": "za", "Canada": "ca", "USA": "us",
        "France": "fr", "Spain": "es", "Germany": "de", "England": "gb-eng",
        "Portugal": "pt", "Netherlands": "nl", "Belgium": "be", "Croatia": "hr",
        "Austria": "at", "Switzerland": "ch", "Norway": "no", "Sweden": "se",
        "Czechia": "cz", "Türkiye": "tr", "Turkey": "tr", "Scotland": "gb-sct",
        "Bosnia & Herzegovina": "ba", "Bosnia and Herzegovina": "ba",
        "Argentina": "ar", "Brazil": "br", "Colombia": "co", "Uruguay": "uy",
        "Ecuador": "ec", "Paraguay": "py", "Panama": "pa", "Curacao": "cw",
        "Haiti": "ht", "Japan": "jp", "South Korea": "kr", "Korea Republic": "kr",
        "Iran": "ir", "Saudi Arabia": "sa", "Australia": "au", "Qatar": "qa",
        "Iraq": "iq", "Jordan": "jo", "Uzbekistan": "uz",
        "Morocco": "ma", "Senegal": "sn", "Egypt": "eg", "Algeria": "dz",
        "Tunisia": "tn", "Ivory Coast": "ci", "Côte d'Ivoire": "ci",
        "Ghana": "gh", "DR Congo": "cd", "Cape Verde": "cv",
        "New Zealand": "nz", "Italy": "it", "Denmark": "dk", "Poland": "pl",
        "Serbia": "rs", "Wales": "gb-wls", "Ukraine": "ua", "Romania": "ro",
        "Greece": "gr", "Hungary": "hu", "Republic of Ireland": "ie",
        "Iceland": "is", "Georgia": "ge", "Slovenia": "si", "Slovakia": "sk",
        "North Macedonia": "mk", "Chile": "cl", "Peru": "pe", "Bolivia": "bo",
        "Venezuela": "ve", "Costa Rica": "cr", "Honduras": "hn", "Jamaica": "jm",
        "China": "cn", "Thailand": "th", "Vietnam": "vn", "Indonesia": "id",
        "Malaysia": "my", "Bahrain": "bh", "Oman": "om", "Palestine": "ps",
        "Cameroon": "cm", "Nigeria": "ng", "Mali": "ml", "Burkina Faso": "bf",
        "Tanzania": "tz", "Mozambique": "mz", "Zambia": "zm", "Uganda": "ug",
        "Benin": "bj", "Comoros": "km", "Gabon": "ga", "Congo": "cg", "Sudan": "sd",
    }

    ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
    ODDS_API_BASE = "https://api.the-odds-api.com/v4"
    SELECTED_BOOKMAKERS = {
        "pinnacle":      "Pinnacle",
        "betfair_ex_eu": "Betfair Exch.",
        "unibet_fr":     "Unibet FR",
        "pmu_fr":        "PMU FR",
    }
    BK_KEYS = list(SELECTED_BOOKMAKERS.keys())
    BK_LABELS = list(SELECTED_BOOKMAKERS.values())

    _BSD_TO_NATION = {}
    for _conf, _nations in WC2026_NATIONS.items():
        for _n in _nations:
            _BSD_TO_NATION[_n["name"]] = _n["code"]

    def _flag(team_name: str) -> str:
        iso = COUNTRY_ISO.get(team_name, "")
        if iso:
            return f"<img src='https://flagcdn.com/24x18/{iso}.png' style='vertical-align:middle;margin:0 4px' alt='{team_name}'>"
        return ""

    def _team_display(team_name: str) -> str:
        code = _BSD_TO_NATION.get(team_name)
        if code:
            return (
                f"<a href='?page=effectifs&nation={code}' "
                f"style='color:inherit;text-decoration:none;border-bottom:1px dashed rgba(136,136,136,0.6)' "
                f"title='Voir l&#39;effectif {team_name}'>{team_name}</a>"
            )
        return team_name

    @st.cache_data(ttl=3600)
    def fetch_wc_events():
        all_events = []
        page_num = 1
        while True:
            r = requests.get(f"{BSD_BASE_URL}/events/", params={
                "league": 27, "date_from": "2026-06-11", "date_to": "2026-07-19",
                "per_page": 100, "page": page_num,
            }, headers=BSD_HEADERS, timeout=15)
            if r.status_code != 200:
                break
            data = r.json()
            all_events.extend(data.get("results", []))
            if not data.get("next"):
                break
            page_num += 1
        return all_events

    @st.cache_data(ttl=1800)
    def fetch_odds_api_h2h():
        if not ODDS_API_KEY:
            return {}
        try:
            r = requests.get(f"{ODDS_API_BASE}/sports/soccer_fifa_world_cup/odds/", params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu,uk",
                "markets": "h2h",
                "oddsFormat": "decimal",
                "bookmakers": ",".join(BK_KEYS),
            }, timeout=15)
            if r.status_code != 200:
                return {}
            data = r.json()
            odds_map = {}
            for match in data:
                home = match.get("home_team", "")
                away = match.get("away_team", "")
                key = f"{home} vs {away}"
                bk_odds = {}
                for bk in match.get("bookmakers", []):
                    bk_key = bk.get("key", "")
                    if bk_key not in SELECTED_BOOKMAKERS:
                        continue
                    market = bk.get("markets", [{}])[0]
                    outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                    bk_odds[bk_key] = {
                        "home": outcomes.get(home),
                        "draw": outcomes.get("Draw"),
                        "away": outcomes.get(away),
                    }
                if bk_odds:
                    odds_map[key] = bk_odds
            return odds_map
        except Exception:
            return {}

    @st.cache_data(ttl=3600)
    def fetch_odds_api_outright():
        if not ODDS_API_KEY:
            return {}
        try:
            r = requests.get(f"{ODDS_API_BASE}/sports/soccer_fifa_world_cup_winner/odds/", params={
                "apiKey": ODDS_API_KEY,
                "regions": "eu,uk",
                "markets": "outrights",
                "oddsFormat": "decimal",
            }, timeout=15)
            if r.status_code != 200:
                return {}
            data = r.json()
            outright = {}
            for match in data:
                for bk in match.get("bookmakers", []):
                    bk_key = bk.get("key", "")
                    if bk_key not in SELECTED_BOOKMAKERS:
                        continue
                    market = bk.get("markets", [{}])[0]
                    for o in market.get("outcomes", []):
                        name = o["name"]
                        price = o["price"]
                        if name not in outright:
                            outright[name] = {}
                        outright[name][bk_key] = price
            return outright
        except Exception:
            return {}

    BSD_TO_ODDS_TEAM = {
        "South Korea": "Korea Republic",
        "Türkiye": "Turkey",
        "Côte d'Ivoire": "Ivory Coast",
        "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    }

    def _match_key_from_bsd(home: str, away: str) -> str:
        h = BSD_TO_ODDS_TEAM.get(home, home)
        a = BSD_TO_ODDS_TEAM.get(away, away)
        return f"{h} vs {a}"

    if st.button("🔄 Rafraîchir toutes les cotes", type="primary", key="refresh_all_odds"):
        fetch_wc_events.clear()
        fetch_odds_api_h2h.clear()
        fetch_odds_api_outright.clear()
        st.rerun()

    try:
        events = fetch_wc_events()
    except Exception as exc:
        st.error(f"Erreur de récupération des matchs : {exc}")
        events = []

    odds_h2h = fetch_odds_api_h2h()
    outright_odds = fetch_odds_api_outright()

    if not events:
        st.warning("Aucun match trouvé pour la Coupe du Monde 2026.")
    else:
        total_matches = len(events)
        matches_with_odds = sum(1 for e in events if _match_key_from_bsd(e.get("home_team",""), e.get("away_team","")) in odds_h2h or e.get("odds_home"))
        finished = sum(1 for e in events if e.get("status") == "finished")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🏟️ Matchs", total_matches)
        c2.metric("✅ Terminés", finished)
        c3.metric("⏳ À venir", total_matches - finished)
        c4.metric("📊 Avec cotes", matches_with_odds)

        st.markdown("---")

        phase_filter = st.radio(
            "Phase",
            ["Tout", "Phase de groupes", "Phase finale"],
            horizontal=True,
            key="wc_phase_filter",
        )

        group_rounds = {1, 2, 3}
        ko_rounds = {5, 6, 27, 28, 29, 50}

        if phase_filter == "Phase de groupes":
            filtered = [e for e in events if e.get("round_number") in group_rounds]
        elif phase_filter == "Phase finale":
            filtered = [e for e in events if e.get("round_number") in ko_rounds]
        else:
            filtered = events

        rounds_in_data = sorted(set(e.get("round_number", 0) for e in filtered),
                                key=lambda r: ROUND_ORDER.index(r) if r in ROUND_ORDER else 99)

        for rnd in rounds_in_data:
            label = ROUND_LABELS.get(rnd, f"Tour {rnd}")
            if rnd in group_rounds:
                label = f"⚽ Phase de groupes — {label}"

            rnd_events = [e for e in filtered if e.get("round_number") == rnd]
            rnd_events.sort(key=lambda e: e.get("event_date", ""))

            with st.expander(f"{label}  ({len(rnd_events)} matchs)", expanded=(rnd == rounds_in_data[0])):
                dates_in_round = sorted(set(e.get("event_date", "")[:10] for e in rnd_events))
                for date_str in dates_in_round:
                    from datetime import datetime
                    try:
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                        jour_fr = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"][dt.weekday()]
                        mois_fr = ["janv.", "fév.", "mars", "avr.", "mai", "juin",
                                   "juil.", "août", "sept.", "oct.", "nov.", "déc."][dt.month - 1]
                        display_date = f"{jour_fr} {dt.day} {mois_fr} {dt.year}"
                    except Exception:
                        display_date = date_str

                    st.markdown(f"**📆 {display_date}**")

                    day_events = [e for e in rnd_events if e.get("event_date", "")[:10] == date_str]

                    for ev in day_events:
                        home = ev.get("home_team", "?")
                        away = ev.get("away_team", "?")
                        h_flag = _flag(home)
                        a_flag = _flag(away)

                        try:
                            raw_dt = ev.get("event_date", "")
                            if "T" in raw_dt:
                                from datetime import timezone, timedelta
                                ev_dt = datetime.fromisoformat(raw_dt)
                                paris_offset = timedelta(hours=2)
                                ev_local = ev_dt.astimezone(timezone(paris_offset))
                                kick_time = ev_local.strftime("%H:%M")
                            else:
                                kick_time = "—"
                        except Exception:
                            kick_time = "—"

                        status = ev.get("status", "notstarted")
                        hs = ev.get("home_score")
                        as_ = ev.get("away_score")

                        if status == "finished" and hs is not None:
                            score_display = f"**{hs} — {as_}**"
                        elif status == "inprogress":
                            minute = ev.get("current_minute", "?")
                            score_display = f"🔴 {hs} — {as_} ({minute}')"
                        else:
                            score_display = f"🕐 {kick_time}"

                        h_link = _team_display(home)
                        a_link = _team_display(away)

                        match_cols = st.columns([3, 1, 3])
                        with match_cols[0]:
                            st.markdown(f"<div style='text-align:right;font-size:1.25em;font-weight:600'>{h_flag} {h_link}</div>",
                                        unsafe_allow_html=True)
                        with match_cols[1]:
                            st.markdown(f"<div style='text-align:center;font-size:1.15em'>{score_display}</div>",
                                        unsafe_allow_html=True)
                        with match_cols[2]:
                            st.markdown(f"<div style='text-align:left;font-size:1.25em;font-weight:600'>{a_link} {a_flag}</div>",
                                        unsafe_allow_html=True)

                        mkey = _match_key_from_bsd(home, away)
                        match_odds = odds_h2h.get(mkey, {})

                        if match_odds:
                            header_html = (
                                "<table style='width:100%;border-collapse:collapse;margin:4px 0;font-size:0.85em'>"
                                "<thead><tr style='border-bottom:1px solid #444'>"
                                "<th style='text-align:left;padding:2px 6px;color:#888'>Bookmaker</th>"
                                "<th style='text-align:center;padding:2px 6px;color:#2ecc71'>1</th>"
                                "<th style='text-align:center;padding:2px 6px;color:#f39c12'>N</th>"
                                "<th style='text-align:center;padding:2px 6px;color:#e74c3c'>2</th>"
                                "</tr></thead><tbody>"
                            )
                            best = {"home": 0, "draw": 0, "away": 0}
                            for bk_key in BK_KEYS:
                                bk_data = match_odds.get(bk_key, {})
                                for col in ("home", "draw", "away"):
                                    v = bk_data.get(col) or 0
                                    if v > best[col]:
                                        best[col] = v

                            rows_html = ""
                            for bk_key in BK_KEYS:
                                bk_data = match_odds.get(bk_key)
                                if not bk_data:
                                    continue
                                bk_label = SELECTED_BOOKMAKERS[bk_key]
                                oh = bk_data.get("home")
                                od = bk_data.get("draw")
                                oa = bk_data.get("away")

                                def _cell(val, best_val):
                                    if val is None:
                                        return "<td style='text-align:center;padding:2px 6px;color:#555'>—</td>"
                                    bold = "font-weight:bold;color:#00ff88" if val == best_val and best_val > 0 else ""
                                    return f"<td style='text-align:center;padding:2px 6px;{bold}'>{val:.2f}</td>"

                                rows_html += (
                                    f"<tr>"
                                    f"<td style='text-align:left;padding:2px 6px;font-size:0.9em'>{bk_label}</td>"
                                    f"{_cell(oh, best['home'])}"
                                    f"{_cell(od, best['draw'])}"
                                    f"{_cell(oa, best['away'])}"
                                    f"</tr>"
                                )

                            if rows_html:
                                st.markdown(header_html + rows_html + "</tbody></table>", unsafe_allow_html=True)
                        else:
                            oh = ev.get("odds_home")
                            od = ev.get("odds_draw")
                            oa = ev.get("odds_away")
                            if oh and od and oa:
                                st.markdown(
                                    f"<div style='text-align:center;font-size:0.85em;color:#888'>"
                                    f"BSD · <span style='color:#2ecc71'>1: {oh:.2f}</span> · "
                                    f"<span style='color:#f39c12'>N: {od:.2f}</span> · "
                                    f"<span style='color:#e74c3c'>2: {oa:.2f}</span></div>",
                                    unsafe_allow_html=True,
                                )
                            else:
                                st.markdown(
                                    "<div style='text-align:center;font-size:0.8em;color:#555'>Cotes indisponibles</div>",
                                    unsafe_allow_html=True,
                                )

                        st.markdown("<hr style='margin:4px 0;border-color:#333'>", unsafe_allow_html=True)

        st.markdown("---")

        st.subheader("📊 Résumé des cotes — Multi-bookmakers")
        if odds_h2h:
            summary_rows = []
            for ev in sorted(events, key=lambda e: e.get("event_date", "")):
                home = ev.get("home_team", "?")
                away = ev.get("away_team", "?")
                rnd = ev.get("round_number", 0)
                mkey = _match_key_from_bsd(home, away)
                modd = odds_h2h.get(mkey, {})
                if not modd:
                    continue
                try:
                    d_str = ev.get("event_date", "")[:10]
                except Exception:
                    d_str = "—"

                row = {
                    "Date": d_str,
                    "Phase": ROUND_LABELS.get(rnd, f"Tour {rnd}"),
                    "Match": f"{home}  vs  {away}",
                }
                best_home = 0
                best_fav = "—"
                for bk_key in BK_KEYS:
                    bk_data = modd.get(bk_key, {})
                    bk_label = SELECTED_BOOKMAKERS[bk_key]
                    oh = bk_data.get("home")
                    od = bk_data.get("draw")
                    oa = bk_data.get("away")
                    row[f"1 {bk_label}"] = oh if oh else None
                    row[f"N {bk_label}"] = od if od else None
                    row[f"2 {bk_label}"] = oa if oa else None

                summary_rows.append(row)

            if summary_rows:
                df_summary = pd.DataFrame(summary_rows)
                st.dataframe(df_summary, use_container_width=True, hide_index=True)
            else:
                st.info("Aucune cote multi-bookmakers disponible.")
        else:
            st.info("Impossible de charger les cotes multi-bookmakers (clé API manquante ou erreur).")

        st.markdown("---")

        st.subheader("🏆 Cotes vainqueur — Coupe du Monde 2026")
        if outright_odds:
            outright_rows = []
            for nation, bk_odds in sorted(outright_odds.items(), key=lambda x: min(x[1].values())):
                row = {"Nation": nation}
                for bk_key in BK_KEYS:
                    bk_label = SELECTED_BOOKMAKERS[bk_key]
                    row[bk_label] = bk_odds.get(bk_key)
                best_val = min(bk_odds.values())
                row["Meilleure"] = best_val
                outright_rows.append(row)
            df_out = pd.DataFrame(outright_rows)
            st.dataframe(df_out, use_container_width=True, hide_index=True)
        else:
            st.info("Cotes vainqueur indisponibles pour le moment.")


# ═══════════════════════════════════════════════════════════════════
elif page == "🌍 Effectifs CM 2026":
    st.header("🌍 Effectifs — Coupe du Monde 2026")
    st.caption(
        "Données issues de Transfermarkt · 5 derniers matchs par nation · "
        "Base statique pré-chargée — rafraîchissement en direct disponible"
    )

    # ── Statut des sources de données ───────────────────────────────
    static_status = get_static_db_status()
    cache_status = get_cache_status()
    n_static = len(static_status)

    if n_static > 0:
        st.success(
            f"**{n_static} / 48** nations disponibles instantanément depuis la base statique.",
            icon="⚡",
        )
    else:
        st.warning(
            "La base statique est vide. Utilisez **Rafraîchir depuis TM** "
            "pour charger un effectif à la demande.",
            icon="⚠️",
        )

    # ── Statut cache BSD ─────────────────────────────────────────────
    bsd_cache_info = cache_summary()
    if bsd_cache_info.get("exists") and bsd_cache_info.get("fresh"):
        age_h = bsd_cache_info.get("age_hours", 0)
        n_stats = bsd_cache_info.get("player_stats", 0)
        updated = bsd_cache_info.get("updated_at", "")[:19].replace("T", " ")
        st.info(
            f"📊 **Cache BSD actif** — {n_stats} joueurs pré-chargés · "
            f"Mis à jour : {updated} UTC (il y a {age_h:.0f}h) · "
            f"Prochain rafraîchissement : 05:00 UTC",
            icon="📊",
        )
    else:
        from bsd_cache import is_cache_fresh
        if not is_cache_fresh():
            st.warning(
                "⏳ Cache BSD en cours de construction en arrière-plan… "
                "Les stats seront disponibles d'ici quelques minutes. "
                "En attendant, les données sont chargées en direct depuis l'API.",
                icon="⏳",
            )

    # ── Helper d'affichage/édition du tableau ────────────────────────
    def _show_squad_editor(players_raw: list[dict], nation_code: str):
        if not players_raw:
            return

        # Charger l'état actif/inactif persisté
        active_status = get_nation_active_status(nation_code, players_raw)

        # Construire le DataFrame (sans valeur marchande)
        rows = []
        for p in players_raw:
            rows.append({
                "Actif": active_status.get(p.get("name", ""), True),
                "Joueur": p.get("name", "—"),
                "Club": p.get("club", "—"),
                "Matchs (5 dern.)": p.get("appearances", 0) or 0,
            })

        df_edit = pd.DataFrame(rows).sort_values("Matchs (5 dern.)", ascending=False).reset_index(drop=True)
        n_active_saved = int(df_edit["Actif"].sum())

        # ── Boutons rapides (hors formulaire) ────────────────────────
        btn_col1, btn_col2, info_col = st.columns([1, 1, 5])
        with btn_col1:
            if st.button("✅ Tout activer", key=f"all_on_{nation_code}",
                         help="Marquer tous les joueurs comme actifs"):
                save_player_selection(nation_code, {p["name"]: True for p in players_raw})
                st.rerun()
        with btn_col2:
            if st.button("❌ Tout désactiver", key=f"all_off_{nation_code}",
                         help="Marquer tous les joueurs comme inactifs"):
                save_player_selection(nation_code, {p["name"]: False for p in players_raw})
                st.rerun()
        with info_col:
            st.markdown(
                f"**{n_active_saved} / {len(df_edit)} joueur(s) actif(s).** "
                "Modifiez les cases puis cliquez **Valider** (ou appuyez sur **Entrée**)."
            )

        # ── Formulaire avec validation explicite ─────────────────────
        with st.form(key=f"form_squad_{nation_code}"):
            edited_df = st.data_editor(
                df_edit[["Actif", "Joueur", "Club", "Matchs (5 dern.)"]],
                column_config={
                    "Actif": st.column_config.CheckboxColumn(
                        "✅ Actif",
                        help="Cocher = joueur retenu pour la Coupe du Monde",
                        default=True,
                        width="small",
                    ),
                    "Joueur": st.column_config.TextColumn("Joueur", width="medium"),
                    "Club": st.column_config.TextColumn("Club", width="medium"),
                    "Matchs (5 dern.)": st.column_config.NumberColumn("⚽ Matchs", width="small"),
                },
                disabled=["Joueur", "Club", "Matchs (5 dern.)"],
                hide_index=True,
                height=min(700, 50 + len(df_edit) * 37),
                key=f"editor_{nation_code}",
                use_container_width=True,
            )

            submitted = st.form_submit_button(
                "💾 Valider la sélection",
                type="primary",
                use_container_width=False,
            )

        if submitted:
            new_selection = {
                name: bool(val)
                for name, val in zip(edited_df["Joueur"], edited_df["Actif"])
            }
            save_player_selection(nation_code, new_selection)
            n_new = sum(new_selection.values())
            st.success(f"✅ Sélection enregistrée — **{n_new}** joueur(s) actif(s).")
            st.rerun()

        # ── Résumé simple sous le tableau ────────────────────────────
        n_inactive = len(df_edit) - n_active_saved
        if n_inactive > 0:
            inactive_names = df_edit.loc[~df_edit["Actif"], "Joueur"].tolist()
            with st.expander(f"👁 {n_inactive} joueur(s) non retenu(s)", expanded=False):
                st.markdown(", ".join(inactive_names))

    _linked_nation = None
    if _nav_nation:
        _linked_nation = get_nation_by_code(_nav_nation)
    if _linked_nation:
        _ln_code = _linked_nation["code"]
        _ln_fr = _linked_nation["fr"]
        st.markdown(f"### 📌 {_ln_fr}")
        if st.button("← Retour à tous les effectifs"):
            st.query_params.clear()
            st.rerun()

        _ln_live = cache_status.get(_ln_code, {})
        _ln_has_live = bool(_ln_live and _ln_live.get("valid"))
        if _ln_has_live:
            from squad_scraper import _load_cache as _sc_load
            _ln_players = _sc_load().get(_ln_code, {}).get("players", [])
        else:
            _ln_players = get_static_squad(_ln_code)

        if _ln_players:
            _show_squad_editor(_ln_players, _ln_code)
        else:
            st.info("Aucune donnée disponible pour cette nation.")
        st.markdown("---")

    # ── Tabs par confédération ──────────────────────────────────────
    conf_keys = list(WC2026_NATIONS.keys())
    tab_labels = [f"{CONF_LABELS[c]} ({CONF_COUNTS[c]})" for c in conf_keys]
    tabs = st.tabs(tab_labels)

    for tab, conf in zip(tabs, conf_keys):
        with tab:
            nations = WC2026_NATIONS[conf]
            nation_names_fr = [n["fr"] for n in nations]

            _sel_index = 0
            if _linked_nation and _linked_nation.get("conf") == conf:
                try:
                    _sel_index = nation_names_fr.index(_linked_nation["fr"])
                except ValueError:
                    _sel_index = 0

            col_sel, col_btn = st.columns([3, 1])
            with col_sel:
                selected_fr = st.selectbox(
                    "Sélectionner une nation",
                    nation_names_fr,
                    index=_sel_index,
                    key=f"sel_{conf}",
                )
            nation = next((n for n in nations if n["fr"] == selected_fr), nations[0])
            code = nation["code"]

            # Chercher les données : cache live > base statique
            live_entry = cache_status.get(code, {})
            has_live_cache = bool(live_entry and live_entry.get("valid"))

            if has_live_cache:
                from squad_scraper import _load_cache as _sc_load
                players_raw = _sc_load().get(code, {}).get("players", [])
                data_source = "live"
            else:
                players_raw = get_static_squad(code)
                data_source = "static" if players_raw else "none"

            with col_btn:
                st.markdown("<br>", unsafe_allow_html=True)
                refresh_btn = st.button(
                    "🔄 Rafraîchir depuis TM",
                    key=f"btn_{conf}_{code}",
                    help="Scrape Transfermarkt en direct (~3-5 min)",
                )

            # Badge de statut
            if data_source == "live":
                fetched = live_entry.get("fetched_at", "")[:19].replace("T", " ")
                st.success(
                    f"✅ Mis à jour en direct — {len(players_raw)} joueurs · {fetched}",
                    icon="✅",
                )
            elif data_source == "static":
                st.info(
                    f"⚡ Base statique — {len(players_raw)} joueurs · "
                    "Cliquez **Rafraîchir** pour des données en temps réel.",
                    icon="⚡",
                )
            elif nation["tm_id"] is None:
                st.warning("⚠️ ID Transfermarkt non disponible pour cette nation.", icon="⚠️")
            else:
                st.info(
                    "ℹ️ Aucune donnée. Cliquez sur **Rafraîchir depuis TM** (~3-5 min).",
                    icon="ℹ️",
                )

            # ── Rafraîchissement live depuis TM ──────────────────────
            if refresh_btn and nation["tm_id"] is not None:
                progress_bar = st.progress(0, text="Initialisation…")

                def _progress(step, total, msg, _bar=progress_bar):
                    _bar.progress(min(int(step), 100), text=msg)

                with st.spinner(f"Chargement de {selected_fr} depuis Transfermarkt…"):
                    try:
                        players = get_squad_cached(
                            nation, force_refresh=True,
                            progress_callback=_progress,
                        )
                        progress_bar.progress(100, text="Terminé ✅")
                        if players:
                            st.success(
                                f"✅ {len(players)} joueurs récupérés pour {selected_fr}.",
                                icon="✅",
                            )
                        else:
                            st.error(
                                "❌ Aucun joueur trouvé. TM bloque peut-être "
                                "les requêtes. Réessayez plus tard.",
                                icon="❌",
                            )
                        st.rerun()
                    except Exception as e:
                        progress_bar.empty()
                        st.error(f"Erreur lors du chargement : {e}")

            # ── Affichage/édition du tableau ─────────────────────────
            if players_raw:
                _show_squad_editor(players_raw, code)

                # ── Stats BSD API ──────────────────────────────────────
                from bsd_api import TM_CODE_TO_BSD_NATIONALITY
                nat_name = TM_CODE_TO_BSD_NATIONALITY.get(code)
                if nat_name or any(p.get("club") in TM_TO_BSD_TEAM for p in players_raw):
                    with st.expander(
                        f"📊 Stats BSD API — Saison 2025/26"
                        + (f" · Nationalité : {nat_name}" if nat_name else ""),
                        expanded=False,
                    ):
                        st.caption(
                            "Notes moyennes, buts, passes décisives, xG et valeur marchande "
                            "via BSD API (saison 2025/26). Chargement ~10-20 sec à la première ouverture."
                        )
                        with st.spinner("Récupération des stats clubs…"):
                            bsd_stats_map = get_squad_bsd_stats(players_raw, nation_code=code)

                        bsd_rows = []
                        for p in players_raw:
                            pname = p.get("name", "")
                            s = bsd_stats_map.get(pname)
                            if not s:
                                continue
                            rating_comp = compute_player_rating(s, p.get("market_value_eur", 0))
                            raw_rating = s.get("rating")
                            try:
                                note = float(raw_rating) if raw_rating is not None else 0.0
                            except (ValueError, TypeError):
                                note = 0.0
                            try:
                                score_comp = float(rating_comp) if rating_comp is not None else 0.0
                            except (ValueError, TypeError):
                                score_comp = 0.0
                            total_mins = int(s.get("minutes_played", 0) or 0)
                            apps = int(s.get("appearances", 0) or 0)
                            full_90_count = int(s.get("full_90", 0) or 0)
                            avg_mins = round(total_mins / apps, 1) if apps > 0 else 0.0
                            xg_val = float(s.get("xg", 0) or 0)
                            xa_val = float(s.get("xa", 0) or 0)
                            nineties = total_mins / 90.0 if total_mins > 0 else 0
                            xg_per90 = round(xg_val / nineties, 2) if nineties > 0 else 0.0
                            xa_per90 = round(xa_val / nineties, 2) if nineties > 0 else 0.0

                            bsd_rows.append({
                                "Joueur": pname,
                                "Club": p.get("club", "—"),
                                "Note moy.": note,
                                "Matchs": apps,
                                "Min.": total_mins,
                                "Min./match": avg_mins,
                                "90 min": full_90_count,
                                "Buts": int(s.get("goals", 0) or 0),
                                "Passes D.": int(s.get("assists", 0) or 0),
                                "xG": xg_val,
                                "xG/90": xg_per90,
                                "xA": xa_val,
                                "xA/90": xa_per90,
                                "% Duels": f"{s.get('duel_pct', 0)}%",
                                "⭐ Score composite": score_comp,
                            })

                        if bsd_rows:
                            df_bsd = pd.DataFrame(bsd_rows).sort_values(
                                "Note moy.", ascending=False
                            ).reset_index(drop=True)
                            st.dataframe(
                                df_bsd,
                                hide_index=True,
                                use_container_width=True,
                                column_config={
                                    "Note moy.": st.column_config.NumberColumn(
                                        "Note moy.", format="%.2f", width="small"
                                    ),
                                    "Min.": st.column_config.NumberColumn("Min.", format="%d"),
                                    "Min./match": st.column_config.NumberColumn("Min./match", format="%.1f"),
                                    "90 min": st.column_config.NumberColumn("90 min", format="%d",
                                        help="Nombre de matchs complets (≥90 min)"),
                                    "xG": st.column_config.NumberColumn("xG", format="%.2f"),
                                    "xG/90": st.column_config.NumberColumn("xG/90", format="%.2f",
                                        help="Expected Goals par 90 minutes"),
                                    "xA": st.column_config.NumberColumn("xA", format="%.2f"),
                                    "xA/90": st.column_config.NumberColumn("xA/90", format="%.2f",
                                        help="Expected Assists par 90 minutes"),
                                    "⭐ Score composite": st.column_config.NumberColumn(
                                        "⭐ Score", format="%.1f", width="small",
                                        help="Score composite 0-100 (note + valeur marchande + forme)"
                                    ),
                                },
                            )

                            # Top 3 de la sélection
                            top3 = df_bsd.head(3)
                            st.markdown("**🏆 Top 3 joueurs de la sélection (note BSD)**")
                            tcol1, tcol2, tcol3 = st.columns(3)
                            for i, (col, (_, row)) in enumerate(
                                zip([tcol1, tcol2, tcol3], top3.iterrows())
                            ):
                                medal = ["🥇", "🥈", "🥉"][i]
                                col.metric(
                                    f"{medal} {row['Joueur']}",
                                    f"{row['Note moy.']:.2f}" if isinstance(row['Note moy.'], float) else "—",
                                    f"{row['Buts']}G / {row['Passes D.']}A — xG {row['xG']:.2f}",
                                )
                        else:
                            st.info(
                                "Aucun joueur de cette sélection n'a pu être "
                                "identifié dans la BSD API pour la saison en cours."
                            )
            elif data_source == "none" and nation["tm_id"] is not None:
                st.info("Cliquez sur **Rafraîchir depuis TM** pour charger cet effectif.")

    # ── Admin : gestion du cache ────────────────────────────────────
    with st.expander("⚙️ Gestion des caches"):
        # ── Cache BSD API ─────────────────────────────────────────
        st.markdown("##### Cache BSD API (stats joueurs)")
        bsd_info = cache_summary()
        if bsd_info.get("exists"):
            bc1, bc2, bc3 = st.columns(3)
            bc1.metric("Joueurs avec stats", bsd_info.get("player_stats", 0))
            bc2.metric("Nations couvertes", bsd_info.get("squads_matched", 0))
            age = bsd_info.get("age_hours", 0)
            bc3.metric("Ancienneté", f"{age:.0f}h", "Frais" if bsd_info.get("fresh") else "Périmé")
        else:
            st.info("Cache BSD non encore construit.")

        if st.button("🔄 Reconstruire le cache BSD maintenant", key="rebuild_bsd"):
            import threading
            from bsd_cache import build_full_cache
            st.info("Construction du cache BSD lancée en arrière-plan (~10-15 min)…")
            t = threading.Thread(target=build_full_cache, daemon=True)
            t.start()

        st.markdown("---")

        # ── Cache TM live ─────────────────────────────────────────
        st.markdown("##### Cache TM live (scrape Transfermarkt)")
        cache_status2 = get_cache_status()
        st.markdown("Vider le cache live force un re-scrape depuis TM à la prochaine demande.")
        all_codes = [n["code"] for conf in WC2026_NATIONS.values() for n in conf]
        cached_codes = [c for c in all_codes if cache_status2.get(c, {}).get("valid")]

        if cached_codes:
            nation_to_clear = st.selectbox(
                "Nation à vider du cache live",
                ["— Choisir —"] + cached_codes,
                key="clear_sel",
            )
            ccol1, ccol2 = st.columns(2)
            with ccol1:
                if st.button("🗑️ Vider cette nation") and nation_to_clear != "— Choisir —":
                    clear_cache_for(nation_to_clear)
                    st.success(f"Cache live de {nation_to_clear} vidé.")
                    st.rerun()
            with ccol2:
                if st.button("🗑️ Vider tout le cache live", type="secondary"):
                    clear_all_cache()
                    st.success("Cache live entièrement vidé.")
                    st.rerun()
        else:
            st.info("Aucun cache live actif.")
