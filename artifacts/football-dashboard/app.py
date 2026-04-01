import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os
import anthropic

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


@st.cache_data(ttl=3600)
def get_all_matches_for_competition(competition_id):
    """Fetch ALL finished matches for a competition across all pages (for ELO/prediction)."""
    all_matches = []
    for page in range(1, 60):
        params = {"competition_id": competition_id, "per_page": 50, "page": page, "status": "finished"}
        try:
            data = fetch("matches", params)
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


@st.cache_data(ttl=3600)
def get_all_national_matches():
    """Aggregate ALL finished matches from every national team competition."""
    seen = set()
    combined = []
    for comp_id in ALL_NATIONAL_IDS:
        for m in get_all_matches_for_competition(comp_id):
            mid = m.get("id")
            if mid not in seen:
                seen.add(mid)
                combined.append(m)
    return combined


@st.cache_data(ttl=3600)
def get_scheduled_matches_for_competition(competition_id):
    """Fetch upcoming scheduled matches for a competition."""
    all_matches = []
    for page in range(1, 10):
        params = {"competition_id": competition_id, "per_page": 50, "page": page, "status": "scheduled"}
        try:
            data = fetch("matches", params)
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


@st.cache_data(ttl=3600)
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

page = st.sidebar.radio(
    "Section",
    ["🗓️ Match Results", "👤 Players", "🏅 Classement ELO", "🎯 Prédiction de Matchs", "💰 Comparaison de Cotes", "🤖 Assistant IA"],
    label_visibility="visible",
)

active_competitions = ALL_CURATED
selected_group = "Toutes les compétitions"

if page != "🤖 Assistant IA":
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

    if not all_finished:
        st.warning("Aucun match terminé trouvé pour cette compétition.")
    else:
        elo_ratings, elo_history = compute_elo(
            all_finished, k_base=k_factor, home_advantage=home_adv, base_ratings=base_ratings
        )
        n_matches = len(all_finished)
        n_teams = len(elo_ratings)

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

        if base_ratings:
            st.info(
                f"📡 Base EloRating.net chargée ({len(elorating_base)} équipes). "
                "Les ratings de départ sont ceux de EloRating.net, puis ajustés avec les matchs récents de l'API."
            )

        st.markdown("---")
        tab_rank, tab_hist, tab_h2h = st.tabs(["🏆 Classement", "📈 Évolution ELO", "⚔️ Tête-à-tête"])

        ref_line = round(sum(base_ratings.values()) / len(base_ratings)) if base_ratings else 1500
        ref_label = f"Médiane EloRating.net ({ref_line})" if base_ratings else "Base 1500"

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

            col_a, col_b = st.columns([1, 1])
            with col_a:
                fig = px.bar(
                    rank_df, x="ELO ajusté", y="Équipe", orientation="h",
                    color="ELO ajusté", color_continuous_scale="RdYlGn",
                    title=f"Top {top_n} — Rating ELO ajusté",
                    labels={"ELO ajusté": "Rating ELO"},
                )
                fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
                fig.add_vline(x=ref_line, line_dash="dash", line_color="gray", annotation_text=ref_label)
                st.plotly_chart(fig, width="stretch")
            with col_b:
                if base_ratings:
                    st.dataframe(
                        rank_df[["Rang", "Équipe", "ELO ajusté", "Base EloRating.net", "Variation"]],
                        width="stretch", hide_index=True
                    )
                else:
                    st.dataframe(rank_df[["Rang", "Équipe", "ELO ajusté", "Écart vs base"]], width="stretch", hide_index=True)

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
                default_b = all_team_names_sorted[1] if len(all_team_names_sorted) > 1 else all_team_names_sorted[0]
                team_b = st.selectbox("Équipe B", all_team_names_sorted, index=1, key="h2h_b")

            if team_a and team_b and team_a != team_b:
                ra = elo_ratings.get(team_a, ref_line)
                rb = elo_ratings.get(team_b, ref_line)
                rank_a = sorted(elo_ratings.keys(), key=lambda t: -elo_ratings[t]).index(team_a) + 1
                rank_b = sorted(elo_ratings.keys(), key=lambda t: -elo_ratings[t]).index(team_b) + 1

                ra_home = ra + home_adv
                ea = 1 / (1 + 10 ** ((rb - ra_home) / 400))
                eb = 1 - ea

                if base_ratings:
                    base_a = base_ratings.get(resolve_team_elo_name(team_a, base_ratings), ref_line) if resolve_team_elo_name(team_a, base_ratings) else ref_line
                    base_b = base_ratings.get(resolve_team_elo_name(team_b, base_ratings), ref_line) if resolve_team_elo_name(team_b, base_ratings) else ref_line
                    delta_a = f"{ra - base_a:+.0f} vs base"
                    delta_b = f"{rb - base_b:+.0f} vs base"
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric(f"ELO ajusté {team_a}", f"{ra:.0f}", delta_a)
                    mc2.metric(f"ELO ajusté {team_b}", f"{rb:.0f}", delta_b)
                    mc3.metric("Différence", f"{abs(ra - rb):.0f} pts", f"{'Avantage ' + team_a if ra > rb else 'Avantage ' + team_b}")
                    st.caption(f"Base EloRating.net → {team_a}: **{base_a:.0f}** | {team_b}: **{base_b:.0f}**")
                else:
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric(f"ELO {team_a}", f"{ra:.0f}", f"#{rank_a}")
                    mc2.metric(f"ELO {team_b}", f"{rb:.0f}", f"#{rank_b}")
                    mc3.metric("Différence", f"{abs(ra - rb):.0f} pts", f"{'Avantage ' + team_a if ra > rb else 'Avantage ' + team_b}")

                st.markdown(f"**Si {team_a} joue à domicile contre {team_b} :**")
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
                st.dataframe(
                    pred_df.style.background_gradient(subset=["% Victoire dom.", "% Victoire ext."], cmap="RdYlGn"),
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
                st.markdown("#### Saisie des cotes bookmaker")
                st.caption("Entre les cotes décimales de ton bookmaker (ex: 2.10, 3.20, 3.80)")
                b1, b2, b3 = st.columns(3)
                with b1:
                    bk_home = st.number_input(f"Cote {home_cotes}", min_value=1.01, max_value=100.0,
                                               value=float(fo_home) if fo_home else 2.0, step=0.05, format="%.2f", key="bk_home")
                with b2:
                    bk_draw = st.number_input("Cote Nul", min_value=1.01, max_value=100.0,
                                               value=float(fo_draw) if fo_draw else 3.0, step=0.05, format="%.2f", key="bk_draw")
                with b3:
                    bk_away = st.number_input(f"Cote {away_cotes}", min_value=1.01, max_value=100.0,
                                               value=float(fo_away) if fo_away else 4.0, step=0.05, format="%.2f", key="bk_away")

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
