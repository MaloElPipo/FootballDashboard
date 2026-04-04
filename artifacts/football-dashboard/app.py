import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import anthropic
from nations_data import WC2026_NATIONS, CONF_LABELS, CONF_COUNTS, get_nation_by_code, FIFA_TO_ISO, flag_img
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
    "🔮 Prédictions",
    "🔬 Backtest V8",
    "📊 Suivi des paris",
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

_PAGES_WITHOUT_COMP_FILTER = {"🤖 Assistant IA", "🌍 Effectifs CM 2026", "📅 Calendrier CDM 2026", "🏅 Classement ELO", "🔮 Prédictions", "🔬 Backtest V8", "📊 Suivi des paris"}

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
    from elo_engine import (
        fetch_elorating_base as elo_fetch_base,
        compute_all_nations_elo,
        load_elo_overrides,
        save_elo_overrides,
        load_pin_calibrated_elo,
        calibrate_elo_from_pinnacle,
        FORCED_ELO_WEIGHT_DEFAULT,
        PIN_WEIGHT_DEFAULT,
    )

    st.header("🏅 Classement ELO — Coupe du Monde 2026")
    st.caption(
        "ELO Système = EloRating.net + BSD. ELO Pinnacle = calibré via cotes Pinnacle WC2026. "
        "ELO Final = blend des deux + override manuel possible."
    )

    pin_data = load_pin_calibrated_elo()
    pin_date = pin_data.get("calibrated_at", "jamais")[:16].replace("T", " ") if pin_data else "jamais"
    pin_n_matches = pin_data.get("n_matches", 0) if pin_data else 0
    pin_n_nations = pin_data.get("n_nations", 0) if pin_data else 0

    col_settings, col_main = st.columns([1, 3])
    with col_settings:
        st.markdown("#### ⚙️ Réglages")
        pin_weight_pct = st.slider(
            "Poids ELO Pinnacle (%)", 0, 100,
            int(PIN_WEIGHT_DEFAULT * 100), key="pin_weight",
            help="ELO = Pinnacle × poids + Système × (1−poids). 100% = full Pinnacle."
        )
        pin_weight = pin_weight_pct / 100.0

        forced_weight_pct = st.slider(
            "Poids ELO forcé (%)", 0, 100,
            int(FORCED_ELO_WEIGHT_DEFAULT * 100), key="forced_weight",
            help="Quand un ELO forcé est renseigné, il remplace l'ELO calculé avec ce poids."
        )
        forced_weight = forced_weight_pct / 100.0

        st.markdown("---")
        st.markdown("#### 📡 Calibration Pinnacle")
        st.caption(f"Dernière calibration : **{pin_date}**  \n{pin_n_matches} matchs · {pin_n_nations} nations")
        if st.button("🔄 Recalibrer ELO Pinnacle", type="primary", use_container_width=True):
            with st.spinner("Récupération des cotes Pinnacle et inversion sigmoid..."):
                elorating_base_tmp = elo_fetch_base()
                all_tmp = compute_all_nations_elo(
                    elorating_base=elorating_base_tmp,
                    forced_weight=0,
                    pin_weight=0,
                )
                current_system_elo = {r["code"]: r["elo_system"] for r in all_tmp}
                result, err = calibrate_elo_from_pinnacle(current_system_elo)
            if err:
                st.error(f"❌ {err}")
            else:
                st.success(
                    f"✅ Calibration terminée — {result['n_matches']} matchs, "
                    f"{result['n_nations']} nations. API restant : {result['api_remaining']}"
                )
                st.cache_data.clear()
                st.rerun()

    with st.spinner("Calcul du classement ELO (48 nations)..."):
        elorating_base = elo_fetch_base()
        all_elo_data = compute_all_nations_elo(
            elorating_base=elorating_base,
            forced_weight=forced_weight,
            pin_weight=pin_weight,
        )

    with col_main:
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Nations", len(all_elo_data))
        best = all_elo_data[0] if all_elo_data else None
        m2.metric("N°1", f"{best['fr']}" if best else "—")
        m3.metric("Meilleur ELO", f"{best['elo']}" if best else "—")
        n_pin = sum(1 for r in all_elo_data if r.get("elo_pin") is not None)
        m4.metric("ELO Pinnacle", f"{n_pin}/48")
        n_forced = sum(1 for r in all_elo_data if r.get("elo_forced") is not None)
        m5.metric("ELO forcés", f"{n_forced}/48")

    st.info(
        f"📡 **EloRating.net** : {len(elorating_base)} équipes  \n"
        f"⚽ **BSD** : ajustement ±50 pts  \n"
        f"📌 **Pinnacle** : {pin_n_nations} nations calibrées ({pin_n_matches} matchs) — poids {pin_weight_pct}%  \n"
        f"⚖️ **ELO forcé** : poids {forced_weight_pct}% (quand renseigné)"
    )

    st.markdown("---")
    tab_rank, tab_override, tab_detail, tab_h2h, tab_conf = st.tabs([
        "🏆 Classement", "✏️ ELO forcé", "🔍 Détail par nation", "⚔️ Tête-à-tête", "🌍 Par confédération"
    ])

    with tab_rank:
        rank_rows = []
        for r in all_elo_data:
            fhtml = flag_img(r["code"])
            pin_display = str(r["elo_pin"]) if r.get("elo_pin") is not None else "—"
            forced_display = str(r["elo_forced"]) if r.get("elo_forced") is not None else "—"
            rank_rows.append({
                "Rang": r["rank"],
                "Nation": f"{fhtml} {r['fr']}",
                "ELO Final": r["elo"],
                "Base": r["elo_base"],
                "BSD": f"{r['bsd_adj']:+d}",
                "Système": r["elo_system"],
                "Pinnacle": pin_display,
                "Forcé": forced_display,
            })

        rank_df = pd.DataFrame(rank_rows)
        st.markdown(
            rank_df.to_html(escape=False, index=False),
            unsafe_allow_html=True,
        )

    with tab_override:
        st.markdown("#### Ajustements manuels d'ELO")
        st.caption(
            "Renseigne un ELO forcé pour corriger les nations mal évaluées par EloRating.net. "
            f"L'ELO final sera : **forcé × {forced_weight_pct}% + calculé × {100-forced_weight_pct}%**. "
            "Laisse vide pour utiliser l'ELO calculé."
        )

        current_overrides = load_elo_overrides()

        sorted_for_edit = sorted(all_elo_data, key=lambda x: x["fr"])

        edit_rows = []
        for r in sorted_for_edit:
            edit_rows.append({
                "code": r["code"],
                "Nation": r["fr"],
                "Base EloRating": r["elo_base"],
                "Adj. BSD": r["bsd_adj"],
                "Système": r["elo_system"],
                "Pinnacle": r.get("elo_pin"),
                "ELO forcé": current_overrides.get(r["code"], None),
                "ELO final": r["elo"],
            })

        edit_df = pd.DataFrame(edit_rows)

        edited = st.data_editor(
            edit_df,
            column_config={
                "code": st.column_config.TextColumn("Code", disabled=True, width="small"),
                "Nation": st.column_config.TextColumn("Nation", disabled=True),
                "Base EloRating": st.column_config.NumberColumn("Base", disabled=True, format="%d"),
                "Adj. BSD": st.column_config.NumberColumn("Adj. BSD", disabled=True, format="%+d"),
                "Calculé": st.column_config.NumberColumn("Calculé", disabled=True, format="%d"),
                "ELO forcé": st.column_config.NumberColumn(
                    "ELO forcé",
                    min_value=800, max_value=2500, step=1,
                    help="Valeur ELO que tu veux forcer. Laisse vide pour garder le calculé.",
                ),
                "ELO final": st.column_config.NumberColumn("ELO final", disabled=True, format="%d"),
            },
            hide_index=True,
            use_container_width=True,
            key="elo_override_editor",
        )

        if st.button("💾 Sauvegarder les ELO forcés", type="primary"):
            new_overrides = {}
            for _, row in edited.iterrows():
                code = row["code"]
                val = row["ELO forcé"]
                if pd.notna(val) and val is not None:
                    new_overrides[code] = int(val)
            save_elo_overrides(new_overrides)
            st.success(f"✅ {len(new_overrides)} ELO forcé(s) sauvegardé(s). Recharge la page pour voir l'effet.")
            st.cache_data.clear()

    with tab_detail:
        nation_options = [f"{r['fr']} ({r['code']})" for r in all_elo_data]
        selected_nation_str = st.selectbox("Sélectionner une nation", nation_options, key="elo_detail_nation")
        selected_code = selected_nation_str.split("(")[-1].rstrip(")")

        nation_data = next((r for r in all_elo_data if r["code"] == selected_code), None)
        if nation_data:
            st.markdown(f"### {nation_data['fr']} — ELO {nation_data['elo']} (Rang #{nation_data['rank']})")

            sc1, sc2, sc3, sc4, sc5, sc6 = st.columns(6)
            sc1.metric("Base EloRating", f"{nation_data['elo_base']}")
            sc2.metric("Ajust. BSD", f"{nation_data['bsd_adj']:+d}")
            sc3.metric("ELO Système", f"{nation_data['elo_system']}")
            pin_val = nation_data.get("elo_pin")
            sc4.metric("ELO Pinnacle", f"{pin_val}" if pin_val else "—")
            forced_val = nation_data.get("elo_forced")
            sc5.metric("ELO Forcé", f"{forced_val}" if forced_val else "—")
            sc6.metric("ELO Final", f"{nation_data['elo']}")

            st.markdown("---")

            sq1, sq2 = st.columns(2)
            with sq1:
                st.metric("Force effectif (BSD)", f"{nation_data['squad_score']:.1f}/100")
            with sq2:
                st.metric("Performance collective (BSD)", f"{nation_data['performance_score']:.1f}/100")

            sd = nation_data.get("squad_detail", {})
            pd_detail = nation_data.get("performance_detail", {})

            if sd:
                st.markdown("#### Force de l'effectif")
                sq1, sq2, sq3, sq4 = st.columns(4)
                sq1.metric("Top 11 — Note moy.", f"{sd.get('top11_avg', 0):.2f}")
                sq2.metric("Banc — Note moy.", f"{sd.get('bench_avg', 0):.2f}")
                sq3.metric("xG/90 (effectif)", f"{sd.get('xg_per90', 0):.2f}")
                sq4.metric("xA/90 (effectif)", f"{sd.get('xa_per90', 0):.2f}")

                sub_scores_sq = {
                    "Note (45%)": sd.get("rating_score", 0),
                    "Profondeur (20%)": sd.get("depth_score", 0),
                    "xG (20%)": sd.get("xg_score", 0),
                    "xA (15%)": sd.get("xa_score", 0),
                }
                fig_sq = px.bar(
                    x=list(sub_scores_sq.keys()),
                    y=list(sub_scores_sq.values()),
                    title="Décomposition — Force effectif",
                    labels={"x": "", "y": "Score /100"},
                    color=list(sub_scores_sq.keys()),
                )
                fig_sq.update_layout(showlegend=False, yaxis_range=[0, 100])
                st.plotly_chart(fig_sq, width="stretch")

            if pd_detail:
                st.markdown("#### Performance collective")
                pf1, pf2, pf3, pf4 = st.columns(4)
                pf1.metric("xG/90", f"{pd_detail.get('xg_per90', 0):.2f}")
                pf2.metric("Tirs cadrés/90", f"{pd_detail.get('shots_on_target_per90', 0):.2f}")
                pf3.metric("Duels gagnés (%)", f"{pd_detail.get('duel_pct', 0):.1f}%")
                pf4.metric("Passes clés/90", f"{pd_detail.get('key_passes_per90', 0):.2f}")

                sub_scores_pf = {
                    "xG (40%)": pd_detail.get("xg_score", 0),
                    "Duels (25%)": pd_detail.get("duels_score", 0),
                    "Tirs cadrés (20%)": pd_detail.get("shots_score", 0),
                    "Créativité (15%)": pd_detail.get("creativity_score", 0),
                }
                fig_pf = px.bar(
                    x=list(sub_scores_pf.keys()),
                    y=list(sub_scores_pf.values()),
                    title="Décomposition — Performance collective",
                    labels={"x": "", "y": "Score /100"},
                    color=list(sub_scores_pf.keys()),
                )
                fig_pf.update_layout(showlegend=False, yaxis_range=[0, 100])
                st.plotly_chart(fig_pf, width="stretch")

            st.markdown("#### Radar")
            import plotly.graph_objects as go
            radar_fig = go.Figure(data=go.Scatterpolar(
                r=[nation_data["squad_score"],
                   nation_data["performance_score"],
                   nation_data["squad_score"]],
                theta=["Effectif", "Performance", "Effectif"],
                fill="toself",
                name=nation_data["fr"],
            ))
            radar_fig.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                showlegend=False,
                title=f"Profil — {nation_data['fr']}",
            )
            st.plotly_chart(radar_fig, width="stretch")

    with tab_h2h:
        st.markdown("#### Comparaison Tête-à-tête")
        nation_names_sorted = [f"{r['fr']} ({r['code']})" for r in all_elo_data]
        c1, c2 = st.columns(2)
        with c1:
            h2h_a_str = st.selectbox("Équipe A", nation_names_sorted, index=0, key="elo_h2h_a")
        with c2:
            h2h_b_str = st.selectbox("Équipe B", nation_names_sorted, index=1, key="elo_h2h_b")

        code_a = h2h_a_str.split("(")[-1].rstrip(")")
        code_b = h2h_b_str.split("(")[-1].rstrip(")")

        data_a = next((r for r in all_elo_data if r["code"] == code_a), None)
        data_b = next((r for r in all_elo_data if r["code"] == code_b), None)

        if data_a and data_b and code_a != code_b:
            from wc_simulator import sigmoid_v8_1x2 as h2h_buchdahl

            mc1, mc2, mc3 = st.columns(3)
            mc1.metric(
                f"{data_a['fr']}",
                f"ELO {data_a['elo']}",
                f"#{data_a['rank']}"
            )
            mc2.metric(
                f"{data_b['fr']}",
                f"ELO {data_b['elo']}",
                f"#{data_b['rank']}"
            )
            mc3.metric("Écart", f"{abs(data_a['elo'] - data_b['elo'])} pts")

            delta_h2h = data_a["elo"] - data_b["elo"]
            elo_avg_h2h = (data_a["elo"] + data_b["elo"]) / 2
            p1_h2h, px_h2h, p2_h2h = h2h_buchdahl(delta_h2h, elo_avg=elo_avg_h2h, phase="G")

            st.markdown(f"**Probabilités Sigmoid V8 (terrain neutre, phase de groupes) :**")
            pc1, pc2, pc3 = st.columns(3)
            pc1.metric(f"Victoire {data_a['fr']}", f"{p1_h2h*100:.1f}%", f"Cote: {1/p1_h2h:.2f}")
            pc2.metric("Nul", f"{px_h2h*100:.1f}%", f"Cote: {1/px_h2h:.2f}")
            pc3.metric(f"Victoire {data_b['fr']}", f"{p2_h2h*100:.1f}%", f"Cote: {1/p2_h2h:.2f}")

            st.markdown("---")
            st.markdown("#### Comparaison des profils")
            comp_df = pd.DataFrame({
                "Attribut": ["ELO final", "Base EloRating", "Adj. BSD", "Effectif", "Performance"],
                data_a["fr"]: [
                    data_a["elo"], data_a["elo_base"],
                    data_a["bsd_adj"], data_a["squad_score"], data_a["performance_score"],
                ],
                data_b["fr"]: [
                    data_b["elo"], data_b["elo_base"],
                    data_b["bsd_adj"], data_b["squad_score"], data_b["performance_score"],
                ],
            })
            st.dataframe(comp_df, width="stretch", hide_index=True)

            import plotly.graph_objects as go
            radar_cmp = go.Figure()
            for d in [data_a, data_b]:
                radar_cmp.add_trace(go.Scatterpolar(
                    r=[d["squad_score"],
                       d["performance_score"],
                       d["squad_score"]],
                    theta=["Effectif", "Performance", "Effectif"],
                    fill="toself",
                    name=d["fr"],
                ))
            radar_cmp.update_layout(
                polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                title=f"{data_a['fr']} vs {data_b['fr']}",
            )
            st.plotly_chart(radar_cmp, width="stretch")

    with tab_conf:
        st.markdown("#### Classement par confédération")
        conf_labels = {
            "UEFA": "UEFA (Europe)",
            "CONMEBOL": "CONMEBOL (Amérique du Sud)",
            "CONCACAF": "CONCACAF (Amérique du Nord)",
            "AFC": "AFC (Asie)",
            "CAF": "CAF (Afrique)",
            "OFC": "OFC (Océanie)",
        }
        for conf_key in ["UEFA", "CONMEBOL", "CONCACAF", "AFC", "CAF", "OFC"]:
            conf_nations = [r for r in all_elo_data if r["conf"] == conf_key]
            if not conf_nations:
                continue
            conf_nations.sort(key=lambda x: x["elo"], reverse=True)
            with st.expander(f"{conf_labels.get(conf_key, conf_key)} — {len(conf_nations)} nations", expanded=(conf_key == "UEFA")):
                conf_rows = []
                for i, r in enumerate(conf_nations):
                    conf_rows.append({
                        "Rang conf.": i + 1,
                        "Rang mondial": r["rank"],
                        "Nation": r["fr"],
                        "ELO final": r["elo"],
                        "Base": r["elo_base"],
                        "Adj. BSD": r["bsd_adj"],
                        "Effectif": round(r["squad_score"], 1),
                        "Performance": round(r["performance_score"], 1),
                    })
                st.dataframe(pd.DataFrame(conf_rows), width="stretch", hide_index=True)


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
            if st.button(ex, key=f"ex_{ex[:20]}", width="stretch"):
                st.session_state.pending_example = ex
                st.rerun()

        st.markdown("---")
        if st.button("Effacer la conversation", width="stretch"):
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

                        bsd_oh = ev.get("odds_home")
                        bsd_od = ev.get("odds_draw")
                        bsd_oa = ev.get("odds_away")
                        has_bsd = bsd_oh and bsd_od and bsd_oa

                        if match_odds or has_bsd:
                            header_html = (
                                "<table style='width:100%;border-collapse:collapse;margin:4px 0;font-size:0.85em'>"
                                "<thead><tr style='border-bottom:1px solid #444'>"
                                "<th style='text-align:left;padding:2px 6px;color:#888'>Bookmaker</th>"
                                "<th style='text-align:center;padding:2px 6px;color:#2ecc71'>1</th>"
                                "<th style='text-align:center;padding:2px 6px;color:#f39c12'>N</th>"
                                "<th style='text-align:center;padding:2px 6px;color:#e74c3c'>2</th>"
                                "</tr></thead><tbody>"
                            )
                            all_odds = {}
                            if has_bsd:
                                all_odds["bet365"] = {"home": float(bsd_oh), "draw": float(bsd_od), "away": float(bsd_oa)}
                            for bk_key in BK_KEYS:
                                bk_data = match_odds.get(bk_key, {})
                                if bk_data:
                                    all_odds[bk_key] = bk_data

                            best = {"home": 0, "draw": 0, "away": 0}
                            for bk_data in all_odds.values():
                                for col in ("home", "draw", "away"):
                                    v = bk_data.get(col) or 0
                                    if v > best[col]:
                                        best[col] = v

                            ALL_BK_LABELS = {"bet365": "Bet365", **SELECTED_BOOKMAKERS}
                            rows_html = ""
                            for bk_key, bk_data in all_odds.items():
                                bk_label = ALL_BK_LABELS.get(bk_key, bk_key)
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
                            st.markdown(
                                "<div style='text-align:center;font-size:0.8em;color:#555'>Cotes indisponibles</div>",
                                unsafe_allow_html=True,
                            )

                        st.markdown("<hr style='margin:4px 0;border-color:#333'>", unsafe_allow_html=True)

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
            st.dataframe(df_out, width="stretch", hide_index=True)
        else:
            st.info("Cotes vainqueur indisponibles pour le moment.")


# ═══════════════════════════════════════════════════════════════════
elif page == "🔮 Prédictions":
    from wc_simulator import (
        WC2026_GROUPS, run_simulation, get_group_predictions,
        sigmoid_v8_1x2, _build_elo_map,
    )
    import plotly.graph_objects as go

    st.header("🔮 Prédictions — Coupe du Monde 2026")
    st.caption(
        "Simulation Monte Carlo basée sur notre ELO composite + modèle Sigmoid V8 calibré sur 136 matchs "
        "(WC 2022, Euro 2024, Copa 2024). Draw boost + favori boost + ajustement KO. "
        "Brier Score V8 bat Pinnacle globalement (0.575 vs 0.583)."
    )

    def _odds_cell(prob_pct):
        if prob_pct <= 0:
            return "—"
        odds = 100 / prob_pct
        return f"<b>{odds:.2f}</b><br><span style='font-size:0.7em;color:#888'>{prob_pct:.1f}%</span>"

    tab_sim, tab_matches, tab_value = st.tabs([
        "🏆 Simulation globale",
        "⚽ Matchs 1X2",
        "💎 Détection de Value",
    ])

    @st.cache_data(ttl=600)
    def _cached_simulation(n):
        return run_simulation(n_sims=n)

    @st.cache_data(ttl=600)
    def _cached_group_preds():
        return get_group_predictions()

    with tab_sim:
        st.subheader("Probabilités de parcours — 48 nations")
        n_sims = st.selectbox("Nombre de simulations", [1000, 5000, 10000, 50000], index=2)
        sim_data = _cached_simulation(n_sims)

        view_mode = st.radio("Vue", ["Classement général", "Par poule"], horizontal=True, key="sim_view")

        if view_mode == "Classement général":
            rows = []
            for i, r in enumerate(sim_data):
                rows.append({
                    "#": i + 1,
                    "Nation": f"{flag_img(r['code'])} {r['fr']}",
                    "Poule": r["group"],
                    "ELO": r["elo"],
                    "Pts moy.": f"{r['avg_pts']:.1f}",
                    "1/32": _odds_cell(r["p_r32"]),
                    "1/16": _odds_cell(r["p_r16"]),
                    "1/4": _odds_cell(r["p_qf"]),
                    "1/2": _odds_cell(r["p_sf"]),
                    "Finale": _odds_cell(r["p_final"]),
                    "🏆 Titre": _odds_cell(r["p_winner"]),
                })
            df_sim = pd.DataFrame(rows)
            st.markdown(
                df_sim.to_html(escape=False, index=False),
                unsafe_allow_html=True,
            )

            st.subheader("Top 20 — Probabilité de titre")
            top20 = sim_data[:20]
            fig = go.Figure()
            fig.add_trace(go.Bar(
                y=[r["fr"] for r in reversed(top20)],
                x=[r["p_winner"] for r in reversed(top20)],
                orientation="h",
                marker_color=["#FFD700" if i == len(top20)-1 else
                              "#C0C0C0" if i == len(top20)-2 else
                              "#CD7F32" if i == len(top20)-3 else
                              "#1f77b4" for i in range(len(top20))],
                text=[f"{r['p_winner']:.1f}%" for r in reversed(top20)],
                textposition="outside",
            ))
            fig.update_layout(
                xaxis_title="Probabilité de remporter le titre (%)",
                height=600, margin=dict(l=0, r=50),
                xaxis=dict(range=[0, max(r["p_winner"] for r in top20) * 1.3]),
            )
            st.plotly_chart(fig, use_container_width=True)

        else:
            for grp_letter in sorted(WC2026_GROUPS.keys()):
                grp_teams = [r for r in sim_data if r["group"] == grp_letter]
                grp_teams.sort(key=lambda x: -x["p_r32"])
                st.markdown(f"#### Poule {grp_letter}")
                rows = []
                for r in grp_teams:
                    rows.append({
                        "Nation": f"{flag_img(r['code'])} {r['fr']}",
                        "ELO": r["elo"],
                        "Pts moy.": f"{r['avg_pts']:.1f}",
                        "1er": f"{r['p_1st']:.0f}%",
                        "2e": f"{r['p_2nd']:.0f}%",
                        "3e": f"{r['p_3rd']:.0f}%",
                        "4e": f"{r['p_4th']:.0f}%",
                        "Qualif.": _odds_cell(r["p_r32"]),
                        "Titre": _odds_cell(r["p_winner"]),
                    })
                st.markdown(
                    pd.DataFrame(rows).to_html(escape=False, index=False),
                    unsafe_allow_html=True,
                )

    with tab_matches:
        st.subheader("Probabilités 1X2 — Tous les matchs de poules")

        preds = _cached_group_preds()
        grp_filter = st.selectbox(
            "Poule", ["Toutes"] + sorted(WC2026_GROUPS.keys()), key="match_grp_filter"
        )

        groups_to_show = sorted(WC2026_GROUPS.keys()) if grp_filter == "Toutes" else [grp_filter]

        for grp_letter in groups_to_show:
            st.markdown(f"#### Poule {grp_letter}")
            matches = preds[grp_letter]
            rows = []
            for m in matches:
                fh = flag_img(m["home_code"], "20x15")
                fa = flag_img(m["away_code"], "20x15")

                rows.append({
                    "Match": f"{fh} {m['home_fr']} vs {m['away_fr']} {fa}",
                    "ΔElo": f"{m['delta']:+d}",
                    "1": _odds_cell(m["p_home"]),
                    "X": _odds_cell(m["p_draw"]),
                    "2": _odds_cell(m["p_away"]),
                })
            st.markdown(
                pd.DataFrame(rows).to_html(escape=False, index=False),
                unsafe_allow_html=True,
            )

    with tab_value:
        st.subheader("💎 Détection de Value vs Pinnacle (V8)")
        st.caption(
            "Compare nos cotes V8 aux cotes Pinnacle. "
            "Backtest sur 136 matchs (WC22, Euro24, Copa24) : ROI +26.5% (EV≥2%, cote≤10). "
            "Filtre cotes >10 pour éviter les pièges."
        )

        try:
            import os as _os
            ODDS_KEY = _os.environ.get("ODDS_API_KEY", "")
            _r = requests.get(
                "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds/",
                params={
                    "apiKey": ODDS_KEY, "regions": "eu", "markets": "h2h",
                    "bookmakers": "pinnacle", "oddsFormat": "decimal",
                },
                timeout=15,
            )
            pin_matches = _r.json() if _r.status_code == 200 else []
        except Exception:
            pin_matches = []

        if not pin_matches:
            st.warning("Impossible de récupérer les cotes Pinnacle actuelles.")
        else:
            ODDS_TO_CODE = {
                "France":"FRA","Spain":"ESP","Germany":"GER","England":"ENG",
                "Portugal":"POR","Netherlands":"NED","Belgium":"BEL","Croatia":"CRO",
                "Austria":"AUT","Switzerland":"SUI","Norway":"NOR","Sweden":"SWE",
                "Czech Republic":"CZE","Czechia":"CZE","Turkey":"TUR","Scotland":"SCO",
                "Bosnia and Herzegovina":"BIH","Bosnia & Herzegovina":"BIH",
                "Argentina":"ARG","Brazil":"BRA",
                "Colombia":"COL","Uruguay":"URU","Ecuador":"ECU","Paraguay":"PAR",
                "United States":"USA","USA":"USA","Mexico":"MEX","Canada":"CAN",
                "Panama":"PAN","Curacao":"CUW","Curaçao":"CUW","Haiti":"HAI",
                "Japan":"JPN","South Korea":"KOR","Korea Republic":"KOR",
                "Iran":"IRN","Saudi Arabia":"KSA","Australia":"AUS",
                "Qatar":"QAT","Iraq":"IRQ","Jordan":"JOR","Uzbekistan":"UZB",
                "Morocco":"MAR","Senegal":"SEN","Egypt":"EGY","Algeria":"ALG",
                "Tunisia":"TUN","Ivory Coast":"CIV","Ghana":"GHA",
                "DR Congo":"COD","South Africa":"RSA","Cape Verde":"CPV","New Zealand":"NZL",
            }

            code_to_group = {}
            for g, t in WC2026_GROUPS.items():
                for c in t:
                    code_to_group[c] = g

            def resolve_odds_code(name, opponent_code):
                code = ODDS_TO_CODE.get(name)
                if code and opponent_code:
                    grp_c = code_to_group.get(code)
                    grp_o = code_to_group.get(opponent_code)
                    if grp_c and grp_o and grp_c != grp_o:
                        if code == "AUS" and code_to_group.get("AUT") == grp_o:
                            return "AUT"
                return code

            elo_map = _build_elo_map()

            value_rows = []
            for pm in pin_matches:
                home = pm.get("home_team", "")
                away = pm.get("away_team", "")
                pin = None
                for bk in pm.get("bookmakers", []):
                    if bk["key"] == "pinnacle":
                        for mk in bk["markets"]:
                            if mk["key"] == "h2h":
                                pin = {o["name"]: o["price"] for o in mk["outcomes"]}
                if not pin:
                    continue

                ch_raw = ODDS_TO_CODE.get(home)
                ca_raw = ODDS_TO_CODE.get(away)
                ch = resolve_odds_code(home, ca_raw)
                ca = resolve_odds_code(away, ch)
                if not ch or not ca or ch not in elo_map or ca not in elo_map:
                    continue

                oh = pin.get(home, 0)
                od = pin.get("Draw", 0)
                oa = pin.get(away, 0)
                if not oh or not od or not oa:
                    continue

                mg = 1/oh + 1/od + 1/oa
                pin_h = (1/oh)/mg * 100
                pin_d = (1/od)/mg * 100
                pin_a = (1/oa)/mg * 100

                delta = elo_map[ch] - elo_map[ca]
                ea_val = (elo_map[ch] + elo_map[ca]) / 2
                grp_ch = code_to_group.get(ch)
                grp_ca = code_to_group.get(ca)
                phase_val = "G" if grp_ch and grp_ca and grp_ch == grp_ca else "K"
                mod_h, mod_d, mod_a = sigmoid_v8_1x2(delta, elo_avg=ea_val, phase=phase_val)
                mod_h *= 100
                mod_d *= 100
                mod_a *= 100

                nation_h = get_nation_by_code(ch)
                nation_a = get_nation_by_code(ca)
                fr_h = nation_h["fr"] if nation_h else home
                fr_a = nation_a["fr"] if nation_a else away

                for side, ec, odds_pin, prob_mod, prob_pin in [
                    ("1", mod_h - pin_h, oh, mod_h, pin_h),
                    ("X", mod_d - pin_d, od, mod_d, pin_d),
                    ("2", mod_a - pin_a, oa, mod_a, pin_a),
                ]:
                    odds_mod = 100 / prob_mod if prob_mod > 0 else 0
                    ev_pct = (prob_mod / 100 * odds_pin - 1) * 100 if prob_mod > 0 else 0
                    value_rows.append({
                        "match": f"{fr_h} vs {fr_a}",
                        "side": side,
                        "odds_pin": odds_pin,
                        "odds_mod": odds_mod,
                        "model_prob": prob_mod,
                        "pin_prob": prob_pin,
                        "ecart": ec,
                        "ev": ev_pct,
                        "phase": phase_val,
                    })

            value_rows.sort(key=lambda x: -x["ecart"])

            def _fmt_ec(val):
                if val > 3:
                    return f"<span style='color:green;font-weight:bold'>+{val:.1f}%</span>"
                elif val < -3:
                    return f"<span style='color:red'>{val:+.1f}%</span>"
                return f"{val:+.1f}%"

            def _fmt_ev(val):
                if val >= 5:
                    return f"<span style='color:#006400;font-weight:bold'>+{val:.1f}%</span>"
                elif val >= 2:
                    return f"<span style='color:green'>+{val:.1f}%</span>"
                elif val > 0:
                    return f"<span style='color:#888'>+{val:.1f}%</span>"
                return f"<span style='color:red'>{val:+.1f}%</span>"

            def _fmt_conf(ev, ecart, cote):
                stars = 0
                if ev >= 2 and cote <= 10:
                    stars += 1
                if ecart >= 4:
                    stars += 1
                if ev >= 5:
                    stars += 1
                if stars >= 3:
                    return "⭐⭐⭐"
                elif stars >= 2:
                    return "⭐⭐"
                elif stars >= 1:
                    return "⭐"
                return ""

            from bet_tracker import load_bankroll_config, kelly_stake, get_stats as bt_stats

            bk_config = load_bankroll_config()
            bt_s = bt_stats()
            current_bank = bt_s["available"]

            st.markdown("#### 🎯 Recommandations de paris (EV≥2%, cote≤10)")
            st.caption(
                f"Bankroll disponible : **{current_bank:.0f}{bt_s['unit']}** · "
                f"Kelly fraction : {bk_config['kelly_fraction']:.0%} · "
                f"Mise max : {bk_config['max_stake_pct']}% de la bankroll"
            )

            value_pos = [v for v in value_rows if v["ev"] >= 2 and v["odds_pin"] <= 10 and v["ecart"] > 2]
            value_pos.sort(key=lambda x: -x["ev"])
            if value_pos:
                vr = []
                for v in value_pos:
                    prob_dec = v["model_prob"] / 100
                    k_stake = kelly_stake(
                        prob_dec, v["odds_pin"], current_bank,
                        fraction=bk_config["kelly_fraction"],
                        max_pct=bk_config["max_stake_pct"],
                        min_stake=bk_config["min_stake"],
                    )
                    vr.append({
                        "Match": v["match"],
                        "Pari": v["side"],
                        "Cote Pin.": f"{v['odds_pin']:.2f}",
                        "Cote V8": f"{v['odds_mod']:.2f}",
                        "Écart": _fmt_ec(v["ecart"]),
                        "EV": _fmt_ev(v["ev"]),
                        "Mise Kelly": f"{k_stake:.1f}{bt_s['unit']}" if k_stake > 0 else "—",
                        "Confiance": _fmt_conf(v["ev"], v["ecart"], v["odds_pin"]),
                    })
                st.markdown(
                    pd.DataFrame(vr).to_html(escape=False, index=False),
                    unsafe_allow_html=True,
                )
                total_kelly = sum(
                    kelly_stake(v["model_prob"]/100, v["odds_pin"], current_bank,
                                fraction=bk_config["kelly_fraction"],
                                max_pct=bk_config["max_stake_pct"],
                                min_stake=bk_config["min_stake"])
                    for v in value_pos
                )
                st.info(
                    f"💡 **{len(value_pos)} paris identifiés** · "
                    f"Exposition totale Kelly : {total_kelly:.1f}{bt_s['unit']} "
                    f"({total_kelly/current_bank*100:.1f}% de la bankroll)" if current_bank > 0 else
                    f"💡 **{len(value_pos)} paris identifiés**"
                )
            else:
                st.info("Aucune value détectée (modèle très proche de Pinnacle, ou cotes non disponibles).")

            st.markdown("#### Tous les matchs vs Pinnacle")
            all_rows = []
            seen = set()
            for v in value_rows:
                if v["match"] not in seen:
                    seen.add(v["match"])
                    m_data = [x for x in value_rows if x["match"] == v["match"]]
                    d1 = next((x for x in m_data if x["side"] == "1"), None)
                    dx = next((x for x in m_data if x["side"] == "X"), None)
                    d2 = next((x for x in m_data if x["side"] == "2"), None)
                    if d1 and dx and d2:
                        all_rows.append({
                            "Match": v["match"],
                            "V8 1": f"{d1['odds_mod']:.2f}",
                            "Pin. 1": f"{d1['odds_pin']:.2f}",
                            "Éc. 1": _fmt_ec(d1["ecart"]),
                            "V8 X": f"{dx['odds_mod']:.2f}",
                            "Pin. X": f"{dx['odds_pin']:.2f}",
                            "Éc. X": _fmt_ec(dx["ecart"]),
                            "V8 2": f"{d2['odds_mod']:.2f}",
                            "Pin. 2": f"{d2['odds_pin']:.2f}",
                            "Éc. 2": _fmt_ec(d2["ecart"]),
                        })
            if all_rows:
                st.markdown(
                    pd.DataFrame(all_rows).to_html(escape=False, index=False),
                    unsafe_allow_html=True,
                )


# ═══════════════════════════════════════════════════════════════════
elif page == "🔬 Backtest V8":
    from backtest_engine import build_backtest_dataset, run_backtest, run_backtest_dynamic, compute_metrics, DEFAULT_PARAMS, V8PIN_PARAMS, ALL_COMPS, COMP_LABELS
    import plotly.graph_objects as _go_bt
    import numpy as np

    st.header("🔬 Backtest V8 — Calibration du modèle")
    st.caption(
        "Ajustez les paramètres du modèle V8 et observez l'impact en temps réel sur les matchs historiques. "
        "Cotes de référence : Roobet/Winamax dé-marginées (proxy sharp closing)."
    )

    with st.expander("📖 Lexique — Notions techniques", expanded=False):
        st.markdown("""
**Brier Score** — Mesure la précision d'une prédiction probabiliste. C'est la moyenne des carrés des écarts entre les probabilités prédites et le résultat réel (0 ou 1).
- Formule : `(p_prédit − résultat)²` moyenné sur toutes les issues (1/X/2)
- **Plus c'est bas, mieux c'est** (0 = parfait, 2 = pire possible)
- Exemple : si on prédit 70% victoire dom. et le dom. gagne → Brier = (0.70−1)² + (0.15−0)² + (0.15−0)² = 0.135

**Log Loss** — Mesure similaire au Brier mais pénalise beaucoup plus les erreurs de confiance élevée. Si vous prédisez 95% pour une issue qui ne se produit pas, la pénalité est sévère.
- **Plus c'est bas, mieux c'est** (0 = parfait)
- Plus sensible que le Brier aux erreurs "confiantes"

**Divergence absolue** — Écart moyen en cotes décimales entre V8 et les cotes de référence (Roobet/Winamax dé-marginées). Par exemple, V8 donne 2.50 et Ref donne 2.30 → divergence = 0.20.
- **Plus c'est bas, plus on est proche du marché sharp**

**Divergence en %** — Même concept mais en pourcentage relatif : `(cote_V8 / cote_Ref − 1) × 100`. Utile pour comparer des écarts sur des cotes de magnitudes différentes.

**Précision (%)** — Pourcentage de matchs où l'issue la plus probable selon V8 correspond au résultat réel.
- ⚠️ Attention : une précision de 50% ne veut pas dire que le modèle est mauvais — au football, même le meilleur modèle ne dépasse guère 55% car les nuls et surprises sont fréquents.

**Proximité ±0.10 / ±0.20 / ±0.50** — Pourcentage d'issues (1/X/2) où notre cote V8 est à moins de 0.10, 0.20 ou 0.50 de la cote de référence. Plus c'est haut, plus on "colle" au marché.

**Cotes de référence** — Roobet (prioritaire, ~6.3% marge) et Winamax (fallback, ~9.4% marge) dé-marginées via `cote_fair = cote × (1 + marge)`. Proxy des closing lines sharp en l'absence de Pinnacle sur les .fr.
        """)

    @st.cache_data(ttl=86400)
    def _cached_bt_dataset():
        return build_backtest_dataset()

    bt_dataset = _cached_bt_dataset()
    bt_with_pin = [m for m in bt_dataset if m["pin_h"] > 0 and m["pin_d"] > 0 and m["pin_a"] > 0]

    st.subheader("⚙️ Paramètres du modèle")

    _presets = {"V8-Pin (optimisé)": V8PIN_PARAMS, "V7 (défaut)": DEFAULT_PARAMS}
    _pc1, _pc2 = st.columns([2, 2])
    preset_choice = _pc1.radio("Preset", list(_presets.keys()), horizontal=True, index=0)
    use_dynamic_elo = _pc2.toggle("ELO Dynamiques", value=False, help="Met à jour les ELO match par match pendant le backtest. Chaque résultat ajuste les forces relatives des équipes pour les matchs suivants.")
    _active_preset = _presets[preset_choice]

    with st.expander("🔧 Ajuster les paramètres manuellement", expanded=False):
        st.markdown("**Paramètres de base (Sigmoid V7)**")
        _help_scale = "Contrôle la sensibilité au Δ ELO. Plus c'est élevé, plus la courbe est douce (moins de différence entre favori et outsider)."
        _help_draw_base = "Pourcentage de nul de base quand le Δ ELO est nul. Plus c'est haut, plus le modèle prédit de nuls."
        _help_d_half = "Vitesse de décroissance du nul quand le Δ ELO augmente. Plus c'est bas, plus vite le nul diminue avec l'écart."
        _help_power = "Exposant de la courbe de décroissance du nul. Plus c'est élevé, plus la transition est abrupte."
        _help_quality = "Ajustement qualité : modifie le % de nul selon le niveau moyen des équipes. Négatif = moins de nuls entre top teams."

        bc1, bc2, bc3 = st.columns(3)
        p_scale = bc1.slider("SCALE", 200.0, 800.0, _active_preset["scale"], 0.1, help=_help_scale, key="bt_scale")
        p_draw_base = bc2.slider("DRAW_BASE (%)", 15.0, 40.0, _active_preset["draw_base"], 0.1, help=_help_draw_base, key="bt_draw_base")
        p_d_half = bc3.slider("D_HALF", 100.0, 1000.0, _active_preset["d_half"], 1.0, help=_help_d_half, key="bt_d_half")
        bc4, bc5 = st.columns(2)
        p_power = bc4.slider("POWER", 1.0, 5.0, _active_preset["power"], 0.1, help=_help_power, key="bt_power")
        p_quality = bc5.slider("QUALITY", -3.0, 1.0, _active_preset["quality"], 0.05, help=_help_quality, key="bt_quality")

        st.markdown("---")
        st.markdown("**Ajustements V8 — Draw Boost**")
        _help_db_close = "Boost du nul (en points de %) quand le Δ ELO < 100. Les matchs serrés produisent plus de nuls."
        _help_db_mid = "Boost du nul quand 100 ≤ Δ ELO < 200."
        _help_db_ko = "Boost supplémentaire du nul en phase KO (les équipes jouent plus prudemment)."
        _help_db_max = "Plafond maximal du draw boost cumulé."

        dc1, dc2, dc3, dc4 = st.columns(4)
        p_db_close = dc1.slider("DB_CLOSE", 0.0, 15.0, _active_preset["db_close"], 0.5, help=_help_db_close, key="bt_db_close")
        p_db_mid = dc2.slider("DB_MID", 0.0, 10.0, _active_preset["db_mid"], 0.5, help=_help_db_mid, key="bt_db_mid")
        p_db_ko = dc3.slider("DB_KO", 0.0, 15.0, _active_preset["db_ko"], 0.5, help=_help_db_ko, key="bt_db_ko")
        p_db_max = dc4.slider("DB_MAX", 0.0, 50.0, _active_preset["db_max"], 0.5, help=_help_db_max, key="bt_db_max")

        st.markdown("---")
        st.markdown("**Ajustements V8 — Favori Boost**")
        _help_fb_group = "Boost du favori en phase de groupes (en points de %) quand le Δ ELO dépasse le seuil. Les gros favoris surperforment en poules."
        _help_fb_ko = "Boost du favori en phase KO. Généralement plus faible qu'en groupes car les outsiders résistent mieux en KO."
        _help_fav_thr = "Seuil de Δ ELO à partir duquel le boost favori s'active."

        fc1, fc2, fc3 = st.columns(3)
        p_fb_group = fc1.slider("FAV_GROUP", -5.0, 15.0, _active_preset["fb_group"], 0.5, help=_help_fb_group, key="bt_fb_group")
        p_fb_ko = fc2.slider("FAV_KO", 0.0, 10.0, _active_preset["fb_ko"], 0.5, help=_help_fb_ko, key="bt_fb_ko")
        p_fav_thr = fc3.slider("FAV_SEUIL Δ", 100, 600, int(_active_preset["fav_threshold"]), 10, help=_help_fav_thr, key="bt_fav_thr")

    current_params = {
        "scale": p_scale, "draw_base": p_draw_base, "d_half": p_d_half,
        "power": p_power, "quality": p_quality,
        "db_close": p_db_close, "db_mid": p_db_mid, "db_ko": p_db_ko, "db_max": p_db_max,
        "fb_group": p_fb_group, "fb_ko": p_fb_ko, "fav_threshold": p_fav_thr,
    }

    is_preset = all(abs(current_params[k] - _active_preset[k]) < 0.01 for k in _active_preset)

    if use_dynamic_elo:
        bt_dataset_sorted = sorted(bt_dataset, key=lambda m: m.get("date", "9999"))
        bt_results, _final_elo = run_backtest_dynamic(bt_dataset_sorted, current_params)
    else:
        bt_results = run_backtest(bt_dataset, current_params)
    bt_metrics = compute_metrics(bt_results)

    if not is_preset:
        if use_dynamic_elo:
            bt_results_default, _ = run_backtest_dynamic(bt_dataset_sorted, _active_preset)
        else:
            bt_results_default = run_backtest(bt_dataset, _active_preset)
        bt_metrics_default = compute_metrics(bt_results_default)

    st.markdown("---")
    st.subheader("📊 Résultats du backtest")

    def _delta_str(val, ref, lower_is_better=True):
        diff = val - ref
        if abs(diff) < 0.0001:
            return ""
        arrow = "↓" if diff < 0 else "↑"
        color = "green" if (diff < 0 and lower_is_better) or (diff > 0 and not lower_is_better) else "red"
        return f" :{color}[{arrow} {abs(diff):.4f}]"

    st.markdown("##### Métriques globales")
    _h_brier = "Erreur quadratique moyenne des probabilités prédites. Plus c'est bas, mieux c'est. Référence : un modèle naïf (33/33/33) donne ~0.667."
    _h_ll = "Pénalise les prédictions confiantes et fausses. Plus c'est bas, mieux c'est."
    _h_acc = "% de matchs où l'issue la plus probable V8 correspond au résultat réel."

    mg1, mg2, mg3, mg4 = st.columns(4)
    mg1.metric("📐 Matchs analysés", bt_metrics["n_matches"])
    _brier_delta = ""
    if not is_preset:
        _brier_delta = f"{bt_metrics['brier_v8'] - bt_metrics_default['brier_v8']:+.4f}"
    mg2.metric("📉 Brier Score V8", f"{bt_metrics['brier_v8']:.4f}", _brier_delta or None, delta_color="inverse", help=_h_brier)
    _ll_delta = ""
    if not is_preset:
        _ll_delta = f"{bt_metrics['log_loss_v8'] - bt_metrics_default['log_loss_v8']:+.4f}"
    mg3.metric("📉 Log Loss V8", f"{bt_metrics['log_loss_v8']:.4f}", _ll_delta or None, delta_color="inverse", help=_h_ll)
    _acc_delta = ""
    if not is_preset:
        _acc_delta = f"{bt_metrics['accuracy'] - bt_metrics_default['accuracy']:+.1f}%"
    mg4.metric("🎯 Précision", f"{bt_metrics['accuracy']:.1f}%", _acc_delta or None, help=_h_acc)

    if bt_metrics.get("n_with_pin"):
        st.markdown("##### V8 vs Cotes de Référence (Roobet/Winamax dé-marginées)")
        st.caption(f"Comparaison sur {bt_metrics['n_with_pin']} matchs avec cotes de référence disponibles")

        _h_brier_cmp = "Brier Score comparé : V8 vs marché de référence. Si V8 < Ref, notre modèle est plus précis que le marché."
        _h_div = "Écart moyen absolu entre cotes V8 et Ref (en cotes décimales). Plus c'est bas, plus on colle au marché."
        _h_div_pct = "Même écart mais en % relatif. Utile pour comparer des écarts sur des cotes de magnitudes différentes."

        vp1, vp2, vp3, vp4 = st.columns(4)
        _b_v8 = bt_metrics["brier_v8_sub"]
        _b_pin = bt_metrics["brier_pin"]
        _beat = "✅" if _b_v8 < _b_pin else "❌"
        vp1.metric(f"Brier V8 {_beat}", f"{_b_v8:.4f}", help=_h_brier_cmp)
        vp2.metric("Brier Réf.", f"{_b_pin:.4f}")

        _dv_delta = ""
        if not is_preset:
            _dv_delta = f"{bt_metrics['div_abs_mean'] - bt_metrics_default['div_abs_mean']:+.3f}"
        vp3.metric("📏 Div. moy. |absolue|", f"{bt_metrics['div_abs_mean']:.3f}", _dv_delta or None, delta_color="inverse", help=_h_div)

        _dvp_delta = ""
        if not is_preset:
            _dvp_delta = f"{bt_metrics['div_pct_abs_mean'] - bt_metrics_default['div_pct_abs_mean']:+.2f}%"
        vp4.metric("📏 Div. moy. |%|", f"{bt_metrics['div_pct_abs_mean']:.2f}%", _dvp_delta or None, delta_color="inverse", help=_h_div_pct)

        st.markdown("##### Proximité V8 ↔ Réf.")
        st.caption("Pourcentage d'issues (1/X/2) où notre cote V8 est proche de la référence. Plus c'est haut, mieux c'est.")
        _total_o = bt_metrics["total_outcomes"]
        px1, px2, px3, px4 = st.columns(4)

        def _prox_delta(key):
            if is_preset:
                return None
            diff = bt_metrics[key] / _total_o * 100 - bt_metrics_default[key] / bt_metrics_default["total_outcomes"] * 100
            if abs(diff) < 0.01:
                return None
            return f"{diff:+.1f}%"

        px1.metric("À ±0.10", f"{bt_metrics['close_010']}/{_total_o} ({bt_metrics['close_010']/_total_o*100:.1f}%)", _prox_delta("close_010"))
        px2.metric("À ±0.20", f"{bt_metrics['close_020']}/{_total_o} ({bt_metrics['close_020']/_total_o*100:.1f}%)", _prox_delta("close_020"))
        px3.metric("À ±0.50", f"{bt_metrics['close_050']}/{_total_o} ({bt_metrics['close_050']/_total_o*100:.1f}%)", _prox_delta("close_050"))
        px4.metric("À ±1.00", f"{bt_metrics['close_100']}/{_total_o} ({bt_metrics['close_100']/_total_o*100:.1f}%)", _prox_delta("close_100"))

    st.markdown("---")
    st.markdown("##### Détail par compétition")
    comp_rows = []
    for comp, data in bt_metrics.get("by_comp", {}).items():
        row = {"Compétition": COMP_LABELS.get(comp, comp), "Matchs": data["n"], "Brier": data["brier"], "Précision": f"{data['accuracy']}%"}
        if "div_abs" in data:
            row["|Div.| moy."] = data["div_abs"]
        if "n_with_ref" in data:
            row["Avec cotes réf."] = data["n_with_ref"]
        comp_rows.append(row)
    if comp_rows:
        st.dataframe(pd.DataFrame(comp_rows), hide_index=True, use_container_width=True)

    st.markdown("##### Détail par phase")
    phase_rows = []
    for phase, data in bt_metrics.get("by_phase", {}).items():
        phase_rows.append({"Phase": phase, "Matchs": data["n"], "Brier": data["brier"], "Précision": f"{data['accuracy']}%"})
    if phase_rows:
        st.dataframe(pd.DataFrame(phase_rows), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.subheader("📋 Détail par match")
    st.caption("Cliquez sur une colonne pour trier. Les matchs avec cotes de référence montrent les divergences.")

    _available_comps = sorted(set(r["comp"] for r in bt_results))
    _comp_options = [c for c in ALL_COMPS if c in _available_comps]
    _comp_display = {c: f"{COMP_LABELS.get(c, c)} ({sum(1 for r in bt_results if r['comp'] == c)})" for c in _comp_options}
    _bt_filter_comp = st.multiselect(
        "Filtrer par compétition",
        _comp_options,
        default=_comp_options,
        format_func=lambda x: _comp_display.get(x, x),
        key="bt_fcomp",
    )
    _bt_filter_phase = st.radio("Phase", ["Tout", "Groupes", "Qualifs", "KO"], horizontal=True, key="bt_fphase")

    filtered = bt_results
    if _bt_filter_comp:
        filtered = [r for r in filtered if r["comp"] in _bt_filter_comp]
    if _bt_filter_phase == "Groupes":
        filtered = [r for r in filtered if r["phase"] == "G"]
    elif _bt_filter_phase == "Qualifs":
        filtered = [r for r in filtered if r["phase"] == "Q"]
    elif _bt_filter_phase == "KO":
        filtered = [r for r in filtered if r["phase"] == "K"]

    detail_rows = []
    _phase_labels = {"G": "Gr.", "K": "KO", "Q": "Qual."}
    for r in filtered:
        row = {
            "Comp.": COMP_LABELS.get(r["comp"], r["comp"]),
            "Phase": _phase_labels.get(r["phase"], r["phase"]),
            "Match": f"{r['home']} vs {r['away']}",
            "Rés.": r["result"],
            "Δ ELO": r["delta"],
            "V8 1": round(r["v8_h"], 2),
            "V8 X": round(r["v8_d"], 2),
            "V8 2": round(r["v8_a"], 2),
            "Brier": round(r["brier"], 3),
        }
        if r["has_pin"]:
            row["Réf 1"] = r["pin_h"]
            row["Réf X"] = r["pin_d"]
            row["Réf 2"] = r["pin_a"]
            row["Div 1"] = round(r["div_h"], 2) if r["div_h"] is not None else ""
            row["Div X"] = round(r["div_d"], 2) if r["div_d"] is not None else ""
            row["Div 2"] = round(r["div_a"], 2) if r["div_a"] is not None else ""
        else:
            row["Réf 1"] = "—"
            row["Réf X"] = "—"
            row["Réf 2"] = "—"
            row["Div 1"] = "—"
            row["Div X"] = "—"
            row["Div 2"] = "—"
        detail_rows.append(row)

    if detail_rows:
        st.dataframe(pd.DataFrame(detail_rows), hide_index=True, use_container_width=True, height=500)

    st.markdown("---")
    st.subheader("📈 Distribution des divergences")
    if bt_metrics.get("n_with_pin"):
        with_pin_results = [r for r in bt_results if r["has_pin"]]
        all_divs_plot = []
        for r in with_pin_results:
            if r["div_h"] is not None:
                all_divs_plot.append({"Issue": "Domicile (1)", "Divergence": r["div_h"]})
            if r["div_d"] is not None:
                all_divs_plot.append({"Issue": "Nul (X)", "Divergence": r["div_d"]})
            if r["div_a"] is not None:
                all_divs_plot.append({"Issue": "Extérieur (2)", "Divergence": r["div_a"]})

        df_divs = pd.DataFrame(all_divs_plot)
        fig_hist = px.histogram(
            df_divs, x="Divergence", color="Issue", nbins=40,
            title="Distribution des divergences V8 − Réf. (en cotes)",
            barmode="overlay", opacity=0.6,
            color_discrete_map={"Domicile (1)": "#2196F3", "Nul (X)": "#FF9800", "Extérieur (2)": "#4CAF50"},
        )
        fig_hist.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Aligné")
        fig_hist.update_layout(height=400, xaxis_title="Divergence (cote V8 − cote Réf.)", yaxis_title="Nombre d'issues")
        st.plotly_chart(fig_hist, use_container_width=True)
        st.caption("La ligne rouge représente l'alignement parfait. Une distribution centrée sur 0 signifie que V8 ne sur- ni sous-estime systématiquement par rapport au marché de référence.")

        abs_div_by_delta = []
        for r in with_pin_results:
            avg_abs = np.mean([abs(r["div_h"]), abs(r["div_d"]), abs(r["div_a"])])
            abs_div_by_delta.append({"Δ ELO (absolu)": abs(r["delta"]), "Div. moy. |absolue|": avg_abs})
        df_scatter = pd.DataFrame(abs_div_by_delta)
        fig_scatter = px.scatter(
            df_scatter, x="Δ ELO (absolu)", y="Div. moy. |absolue|",
            title="Divergence vs Δ ELO — Où V8 diverge le plus ?",
        )
        fig_scatter.update_layout(height=400)
        st.plotly_chart(fig_scatter, use_container_width=True)
        st.caption("Plus le Δ ELO est élevé (matchs déséquilibrés), plus V8 tend à diverger du marché. C'est le maillon faible actuel du modèle.")
    else:
        st.info("Aucune cote de référence disponible dans le dataset pour les graphiques de divergence.")

    if not is_preset:
        st.markdown("---")
        st.info(
            "💡 **Paramètres modifiés** — Les deltas affichés (↑↓ en vert/rouge) comparent vos paramètres actuels "
            "aux paramètres V8 par défaut. Vert = amélioration, Rouge = dégradation."
        )

    if use_dynamic_elo and _final_elo:
        st.markdown("---")
        st.subheader("📈 ELO Dynamiques — Classement final")
        st.caption("ELO après mise à jour match par match sur l'ensemble du backtest. Reflète la trajectoire historique de chaque équipe.")

        sorted_elo = sorted(_final_elo.items(), key=lambda x: -x[1])
        elo_rows = []
        for rank, (team, elo) in enumerate(sorted_elo[:40], 1):
            elo_rows.append({"#": rank, "Équipe": team, "ELO dynamique": round(elo, 1)})
        import pandas as pd
        _elo_c1, _elo_c2 = st.columns(2)
        half = len(elo_rows) // 2
        _elo_c1.dataframe(pd.DataFrame(elo_rows[:half]), hide_index=True, use_container_width=True)
        _elo_c2.dataframe(pd.DataFrame(elo_rows[half:]), hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
elif page == "📊 Suivi des paris":
    from bet_tracker import (
        load_bets, add_bet, update_bet_result, update_bet_closing_odds,
        delete_bet, compute_clv,
        load_bankroll_config, save_bankroll_config, get_stats as bt_get_stats,
        kelly_stake as bt_kelly,
    )
    import plotly.graph_objects as _go_tracker

    st.header("📊 Suivi des paris — CDM 2026")
    st.caption(
        "Tracker de paris avec gestion de bankroll Kelly et CLV vs Pinnacle."
    )

    stats = bt_get_stats()
    bk_cfg = load_bankroll_config()

    with st.expander("⚙️ Configuration bankroll", expanded=False):
        cfg_c1, cfg_c2, cfg_c3, cfg_c4 = st.columns(4)
        new_initial = cfg_c1.number_input(
            "Bankroll initiale", value=float(bk_cfg["initial"]),
            min_value=1.0, step=10.0, key="cfg_initial"
        )
        new_unit = cfg_c2.text_input("Devise", value=bk_cfg.get("unit", "€"), key="cfg_unit")
        new_kelly = cfg_c3.number_input(
            "Kelly fraction", value=float(bk_cfg["kelly_fraction"]),
            min_value=0.05, max_value=1.0, step=0.05, key="cfg_kelly"
        )
        new_max_pct = cfg_c4.number_input(
            "Mise max (%)", value=float(bk_cfg["max_stake_pct"]),
            min_value=1.0, max_value=20.0, step=0.5, key="cfg_maxpct"
        )
        if st.button("💾 Sauvegarder config", key="save_cfg"):
            save_bankroll_config({
                "initial": new_initial,
                "unit": new_unit,
                "kelly_fraction": new_kelly,
                "max_stake_pct": new_max_pct,
                "min_stake": bk_cfg.get("min_stake", 1.0),
            })
            st.success("Configuration sauvegardée !")
            st.rerun()

    u = stats["unit"]
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    mc1.metric("Bankroll", f"{stats['current_bankroll']:.0f}{u}",
               f"{stats['total_profit']:+.1f}{u}")
    mc2.metric("Paris", f"{stats['total_bets']}",
               f"{stats['pending']} en cours")
    mc3.metric("Bilan", f"{stats['wins']}W / {stats['losses']}L",
               f"{stats['win_rate']:.0f}% win rate" if stats['settled'] > 0 else "—")
    mc4.metric("ROI", f"{stats['roi']:+.1f}%" if stats['settled'] > 0 else "—",
               f"sur {stats['total_staked']:.0f}{u} misés")
    clv_display = f"{stats['avg_clv']:+.2f}%" if stats['avg_clv'] is not None else "—"
    clv_detail = f"{stats['clv_positive']}/{stats['clv_count']} positives" if stats['clv_count'] > 0 else "—"
    mc5.metric("CLV moy.", clv_display, clv_detail)
    mc6.metric("Disponible", f"{stats['available']:.0f}{u}",
               f"-{stats['pending_exposure']:.0f}{u} en jeu" if stats['pending_exposure'] > 0 else "—")

    st.markdown("---")

    with st.expander("➕ Ajouter un pari", expanded=True):
        ac1, ac2 = st.columns(2)
        with ac1:
            new_match = st.text_input("Match", placeholder="France vs Allemagne", key="new_match")
            new_side = st.selectbox("Pari", ["1 (Domicile)", "X (Nul)", "2 (Extérieur)"], key="new_side")
        with ac2:
            new_odds = st.number_input("Cote prise", min_value=1.01, value=2.00, step=0.01, key="new_odds")
            new_stake = st.number_input(
                f"Mise ({u})", min_value=0.5, value=float(bk_cfg.get("min_stake", 1.0)),
                step=0.5, key="new_stake"
            )
        ac3, ac4 = st.columns(2)
        with ac3:
            new_odds_v8 = st.number_input("Cote V8", min_value=0.0, value=0.0, step=0.01, key="new_odds_v8",
                                          help="Optionnel — cote modèle V8 pour ce pari")
        with ac4:
            new_notes = st.text_input("Notes", placeholder="Opening Pinnacle, value sur le nul", key="new_notes")

        if st.button("✅ Enregistrer le pari", key="add_bet", type="primary"):
            if new_match.strip():
                side_map = {"1 (Domicile)": "1", "X (Nul)": "X", "2 (Extérieur)": "2"}
                add_bet(
                    match=new_match.strip(),
                    side=side_map[new_side],
                    odds=new_odds,
                    stake=new_stake,
                    odds_v8=new_odds_v8 if new_odds_v8 > 0 else None,
                    notes=new_notes,
                )
                st.success(f"Pari enregistré : {new_match} — {side_map[new_side]} @ {new_odds:.2f}")
                st.rerun()
            else:
                st.error("Le nom du match est requis.")

    st.markdown("---")

    all_bets = load_bets()
    if all_bets:
        pending_bets = [b for b in all_bets if b["result"] == "pending"]
        settled_bets = [b for b in all_bets if b["result"] != "pending"]

        if pending_bets:
            st.markdown("#### ⏳ Paris en cours")
            for b in pending_bets:
                with st.container():
                    bc1, bc2, bc3, bc4, bc5 = st.columns([3, 1, 1, 1, 2])
                    bc1.markdown(f"**{b['match']}** — {b['side']}")
                    bc2.markdown(f"Cote **{b['odds']:.2f}**")
                    bc3.markdown(f"Mise **{b['stake']:.1f}{u}**")
                    gain_pot = b['stake'] * (b['odds'] - 1)
                    bc4.markdown(f"Gain pot. **{gain_pot:.1f}{u}**")
                    with bc5:
                        rc1, rc2, rc3, rc4 = st.columns(4)
                        if rc1.button("✅", key=f"win_{b['id']}", help="Gagné"):
                            update_bet_result(b["id"], "won")
                            st.rerun()
                        if rc2.button("❌", key=f"lose_{b['id']}", help="Perdu"):
                            update_bet_result(b["id"], "lost")
                            st.rerun()
                        if rc3.button("↩️", key=f"void_{b['id']}", help="Annulé"):
                            update_bet_result(b["id"], "void")
                            st.rerun()
                        if rc4.button("🗑️", key=f"del_{b['id']}", help="Supprimer"):
                            delete_bet(b["id"])
                            st.rerun()
                    info_parts = []
                    if b.get("odds_v8"):
                        info_parts.append(f"Cote V8: {b['odds_v8']:.2f}")
                    if b.get("notes"):
                        info_parts.append(f"📝 {b['notes']}")
                    if info_parts:
                        st.caption(" · ".join(info_parts))

                    cl_col1, cl_col2 = st.columns([2, 3])
                    with cl_col1:
                        cl_odds = st.number_input(
                            "Cote clôture Pin.", min_value=0.0, value=float(b.get("closing_odds_pin", 0) or 0),
                            step=0.01, key=f"closing_{b['id']}", label_visibility="collapsed",
                        )
                    with cl_col2:
                        if st.button("📌 Sauver clôture", key=f"save_cl_{b['id']}"):
                            if cl_odds > 1:
                                update_bet_closing_odds(b["id"], cl_odds)
                                st.rerun()
                    st.markdown("---")

        if settled_bets:
            st.markdown("#### 📋 Historique des paris")

            hist_rows = []
            running_profit = 0
            for b in settled_bets:
                profit = b.get("profit", 0)
                running_profit += profit
                result_icon = {"won": "✅", "lost": "❌", "void": "↩️"}.get(b["result"], "?")
                profit_fmt = f"<span style='color:{'green' if profit > 0 else 'red' if profit < 0 else '#888'}'>{profit:+.1f}{u}</span>"
                cumul_fmt = f"<span style='color:{'green' if running_profit > 0 else 'red' if running_profit < 0 else '#888'}'>{running_profit:+.1f}{u}</span>"

                clv = compute_clv(b["odds"], b.get("closing_odds_pin"))
                if clv is not None:
                    clv_color = "green" if clv > 0 else "red"
                    clv_fmt = f"<span style='color:{clv_color}'>{clv:+.1f}%</span>"
                else:
                    clv_fmt = "—"

                row = {
                    "Date": b.get("date", ""),
                    "Match": b["match"],
                    "Pari": b["side"],
                    "Cote": f"{b['odds']:.2f}",
                    "Cote V8": f"{b['odds_v8']:.2f}" if b.get("odds_v8") else "—",
                    "Clôt. Pin.": f"{b['closing_odds_pin']:.2f}" if b.get("closing_odds_pin") else "—",
                    "CLV": clv_fmt,
                    "Mise": f"{b['stake']:.1f}{u}",
                    "": result_icon,
                    "P&L": profit_fmt,
                    "Cumul": cumul_fmt,
                }
                hist_rows.append(row)

            hist_rows.reverse()
            st.markdown(
                pd.DataFrame(hist_rows).to_html(escape=False, index=False),
                unsafe_allow_html=True,
            )

        if settled_bets and len(settled_bets) >= 3:
            st.markdown("#### 📈 Évolution de la bankroll")
            bank_vals = [stats["initial_bankroll"]]
            running = stats["initial_bankroll"]
            for b in settled_bets:
                running += b.get("profit", 0)
                bank_vals.append(running)
            fig_bank = _go_tracker.Figure()
            fig_bank.add_trace(_go_tracker.Scatter(
                x=list(range(len(bank_vals))), y=bank_vals,
                mode="lines+markers", name="Bankroll",
                line=dict(color="green" if bank_vals[-1] >= bank_vals[0] else "red", width=2),
                fill="tozeroy", fillcolor="rgba(0,200,0,0.1)" if bank_vals[-1] >= bank_vals[0] else "rgba(200,0,0,0.1)",
            ))
            fig_bank.add_hline(y=stats["initial_bankroll"], line_dash="dash",
                               line_color="gray", annotation_text="Bankroll initiale")
            fig_bank.update_layout(
                xaxis_title="Paris réglés",
                yaxis_title=f"Bankroll ({u})",
                height=350,
                margin=dict(l=0, r=20, t=20, b=40),
            )
            st.plotly_chart(fig_bank, use_container_width=True)
    else:
        st.info("Aucun pari enregistré. Utilisez le formulaire ci-dessus pour commencer le suivi.")


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
                width="stretch",
            )

            submitted = st.form_submit_button(
                "💾 Valider la sélection",
                type="primary",
                width="content",
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

    def _render_nation_content(nation, code, selected_fr, key_prefix):
        live_entry = cache_status.get(code, {})
        has_live_cache = bool(live_entry and live_entry.get("valid"))

        if has_live_cache:
            from squad_scraper import _load_cache as _sc_load
            players_raw = _sc_load().get(code, {}).get("players", [])
            data_source = "live"
        else:
            players_raw = get_static_squad(code)
            data_source = "static" if players_raw else "none"

        refresh_btn = st.button(
            "🔄 Rafraîchir depuis TM",
            key=f"btn_{key_prefix}_{code}",
            help="Scrape Transfermarkt en direct (~3-5 min)",
        )

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

        if players_raw:
            _show_squad_editor(players_raw, code)

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
                            width="stretch",
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

    _linked_nation = get_nation_by_code(_nav_nation) if _nav_nation else None

    if _linked_nation:
        st.markdown(f"### 📌 {_linked_nation['fr']}")
        if st.button("← Retour à tous les effectifs"):
            st.query_params.clear()
            st.rerun()
        _render_nation_content(
            _linked_nation, _linked_nation["code"],
            _linked_nation["fr"], key_prefix="linked",
        )
    else:
        conf_keys = list(WC2026_NATIONS.keys())
        tab_labels = [f"{CONF_LABELS[c]} ({CONF_COUNTS[c]})" for c in conf_keys]
        tabs = st.tabs(tab_labels)

        for tab, conf in zip(tabs, conf_keys):
            with tab:
                nations = WC2026_NATIONS[conf]
                nation_names_fr = [n["fr"] for n in nations]

                col_sel, col_btn = st.columns([3, 1])
                with col_sel:
                    selected_fr = st.selectbox(
                        "Sélectionner une nation",
                        nation_names_fr,
                        key=f"sel_{conf}",
                    )
                nation = next((n for n in nations if n["fr"] == selected_fr), nations[0])
                code = nation["code"]

                with col_btn:
                    st.markdown("<br>", unsafe_allow_html=True)

                _render_nation_content(nation, code, selected_fr, key_prefix=conf)

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
