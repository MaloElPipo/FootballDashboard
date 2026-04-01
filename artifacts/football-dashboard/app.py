import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import os

API_BASE = os.environ.get("STATS_API_URL", "https://api.thestatsapi.com/api")
API_KEY = os.environ.get("STATS_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

st.set_page_config(
    page_title="Football Analytics Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

COMPETITION_GROUPS = {
    "UEFA Club Competitions": [
        {"id": "comp_3498",   "name": "UEFA Champions League",    "region": "Europe"},
        {"id": "comp_7739",   "name": "UEFA Europa League",       "region": "Europe"},
        {"id": "comp_408698", "name": "UEFA Conference League",   "region": "Europe"},
        {"id": "comp_6694",   "name": "UEFA Women's Champions League", "region": "Europe"},
    ],
    "International National Teams": [
        {"id": "comp_574977", "name": "UEFA Nations League",              "region": "Europe"},
        {"id": "comp_5749",   "name": "Copa América",                     "region": "South America"},
        {"id": "comp_1554",   "name": "Africa Cup of Nations",            "region": "Africa"},
        {"id": "comp_1376",   "name": "CONCACAF Gold Cup",                "region": "N&C America"},
        {"id": "comp_193547", "name": "CONCACAF Nations League",          "region": "N&C America"},
        {"id": "comp_29967",  "name": "International Friendly Games",     "region": "World"},
    ],
    "World Cup Qualifiers": [
        {"id": "comp_2954",   "name": "WC Qual. — UEFA (Europe)",         "region": "Europe"},
        {"id": "comp_8973",   "name": "WC Qual. — AFC (Asia)",            "region": "Asia"},
        {"id": "comp_4682",   "name": "WC Qual. — CONMEBOL (S. America)", "region": "South America"},
        {"id": "comp_5720",   "name": "WC Qual. — CAF (Africa)",          "region": "Africa"},
        {"id": "comp_7363",   "name": "WC Qual. — OFC (Oceania)",         "region": "Oceania"},
        {"id": "comp_0836",   "name": "WC Qual. — CONCACAF (N&C America)","region": "N&C America"},
    ],
    "Continental Club Competitions": [
        {"id": "comp_0499",   "name": "CONMEBOL Libertadores",    "region": "South America"},
        {"id": "comp_1615",   "name": "CONMEBOL Sudamericana",    "region": "South America"},
        {"id": "comp_08478",  "name": "CAF Champions League",     "region": "Africa"},
        {"id": "comp_8649",   "name": "CONCACAF Champions Cup",   "region": "N&C America"},
    ],
    "Top Domestic Leagues": [
        {"id": "comp_3039",   "name": "Premier League",           "region": "England"},
        {"id": "comp_4643",   "name": "Bundesliga",               "region": "Germany"},
        {"id": "comp_0256",   "name": "Ligue 1",                  "region": "France"},
        {"id": "comp_5840",   "name": "Serie A",                  "region": "Italy"},
        {"id": "comp_0406",   "name": "2. Bundesliga",            "region": "Germany"},
    ],
}

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


st.title("⚽ Football Analytics Dashboard")
st.caption("International competitions & top leagues — powered by TheStatsAPI")

st.sidebar.header("Filters")

page = st.sidebar.radio(
    "Section",
    ["🗓️ Match Results", "🏟️ Teams", "👤 Players"],
    label_visibility="visible",
)

st.sidebar.markdown("---")
st.sidebar.subheader("Competition Category")

group_options = ["All International & Top Leagues"] + list(COMPETITION_GROUPS.keys())
selected_group = st.sidebar.radio("Competition Category", group_options, label_visibility="collapsed")

if selected_group == "All International & Top Leagues":
    active_competitions = ALL_CURATED
else:
    active_competitions = COMPETITION_GROUPS[selected_group]

comp_by_name = {c["name"]: c for c in active_competitions}
comp_by_id = {c["id"]: c for c in active_competitions}

st.sidebar.markdown("---")
st.sidebar.caption("Data refreshes every 5 minutes.")

if page == "🗓️ Match Results":
    st.header("🗓️ Match Results")

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:
        comp_choices = ["All selected competitions"] + [c["name"] for c in active_competitions]
        selected_comp_name = st.selectbox("Competition", comp_choices)

    with col2:
        status_filter = st.selectbox("Status", ["All", "finished", "scheduled", "in_progress"])

    with col3:
        page_num = st.number_input("Page", min_value=1, max_value=500, value=1)

    selected_comp_id = None
    if selected_comp_name != "All selected competitions":
        selected_comp_id = comp_by_name[selected_comp_name]["id"]

    status = None if status_filter == "All" else status_filter

    if selected_comp_id:
        with st.spinner(f"Loading matches for {selected_comp_name}..."):
            matches, meta = get_matches(competition_id=selected_comp_id, status=status, per_page=50, page=page_num)

        if matches:
            df = pd.DataFrame(matches)
            df["home_team_name"] = df["home_team"].apply(lambda x: x.get("name", "") if isinstance(x, dict) else "")
            df["away_team_name"] = df["away_team"].apply(lambda x: x.get("name", "") if isinstance(x, dict) else "")
            df["home_score"] = df["score"].apply(lambda x: x.get("home", 0) if isinstance(x, dict) else 0)
            df["away_score"] = df["score"].apply(lambda x: x.get("away", 0) if isinstance(x, dict) else 0)
            df["total_goals"] = df["home_score"] + df["away_score"]
            df["date"] = pd.to_datetime(df["utc_date"]).dt.date

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Matches", meta.get("total", len(df)))
            c2.metric("Shown", len(df))
            if status == "finished":
                c3.metric("Avg Goals/Match", f"{df['total_goals'].mean():.1f}")
                c4.metric("High-scoring (4+ goals)", int((df["total_goals"] >= 4).sum()))

            st.markdown("---")

            if status == "finished" and not df.empty:
                tab1, tab2 = st.tabs(["📊 Analysis", "📋 Match List"])

                with tab1:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        goals_dist = df["total_goals"].value_counts().sort_index().reset_index()
                        goals_dist.columns = ["Total Goals", "Matches"]
                        fig = px.bar(
                            goals_dist, x="Total Goals", y="Matches",
                            color="Matches", color_continuous_scale="Reds",
                            title="Goals per Match Distribution",
                        )
                        fig.update_layout(showlegend=False)
                        st.plotly_chart(fig, width="stretch")

                    with col_b:
                        df["result"] = df.apply(
                            lambda r: "Home Win" if r["home_score"] > r["away_score"]
                            else ("Away Win" if r["away_score"] > r["home_score"] else "Draw"),
                            axis=1,
                        )
                        result_counts = df["result"].value_counts().reset_index()
                        result_counts.columns = ["Result", "Count"]
                        fig = px.pie(
                            result_counts, names="Result", values="Count",
                            title="Match Outcomes", hole=0.4,
                            color_discrete_map={"Home Win": "#22c55e", "Away Win": "#ef4444", "Draw": "#f59e0b"},
                        )
                        st.plotly_chart(fig, width="stretch")

                    goals_by_day = df.groupby("date")["total_goals"].mean().reset_index()
                    goals_by_day.columns = ["Date", "Avg Goals"]
                    if len(goals_by_day) > 1:
                        fig = px.line(
                            goals_by_day, x="Date", y="Avg Goals",
                            title="Average Goals per Match over Time", markers=True,
                        )
                        st.plotly_chart(fig, width="stretch")

                with tab2:
                    _display(df)
            else:
                _display(df)
        else:
            st.info("No matches found for the selected filters.")
    else:
        st.info("Please select a specific competition from the dropdown above to browse matches.")
        st.markdown("### Curated Competitions in This Group")
        rows = []
        for c in active_competitions:
            rows.append({"Competition": c["name"], "Region": c["region"]})
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


elif page == "🏟️ Teams":
    st.header("🏟️ Teams")

    comp_choices = [c["name"] for c in active_competitions]
    selected_comp_name = st.selectbox("Select a competition to explore its teams", comp_choices)
    selected_comp_id = comp_by_name[selected_comp_name]["id"]

    with st.spinner(f"Loading teams for {selected_comp_name}..."):
        teams, meta = get_teams(competition_id=selected_comp_id, per_page=50)

    if teams:
        teams_df = pd.DataFrame(teams)
        st.write(f"**{meta.get('total', len(teams))} teams** in {selected_comp_name}")

        country_team_counts = teams_df["country"].value_counts().reset_index()
        country_team_counts.columns = ["Country", "Teams"]

        if len(country_team_counts) > 1:
            col1, col2 = st.columns(2)
            with col1:
                fig = px.bar(
                    country_team_counts.head(20),
                    x="Teams", y="Country", orientation="h",
                    color="Teams", color_continuous_scale="Greens",
                    title="Teams by Nation",
                )
                fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
                st.plotly_chart(fig, width="stretch")
            with col2:
                fig = px.pie(
                    country_team_counts.head(10),
                    names="Country", values="Teams",
                    title="Top 10 Nations (by team count)", hole=0.4,
                )
                st.plotly_chart(fig, width="stretch")

        st.markdown("---")
        st.subheader("All Teams")
        cols_available = [c for c in ["name", "short_name", "country"] if c in teams_df.columns]
        st.dataframe(
            teams_df[cols_available].rename(columns={"name": "Team", "short_name": "Short Name", "country": "Country"}),
            width="stretch", hide_index=True,
        )
    else:
        st.info("No team data available for this competition.")


elif page == "👤 Players":
    st.header("👤 Player Explorer")

    col_left, col_right = st.columns([1, 3])

    with col_left:
        st.subheader("Filter")

        comp_choices = [c["name"] for c in active_competitions]
        selected_comp_name = st.selectbox("Competition (for team list)", comp_choices)
        selected_comp_id = comp_by_name[selected_comp_name]["id"]

        with st.spinner("Loading teams..."):
            teams, _ = get_teams(competition_id=selected_comp_id, per_page=50)

        team_options = {"All teams in competition": None}
        team_options.update({t["name"]: t["id"] for t in teams})

        selected_team_name = st.selectbox("Select team", list(team_options.keys()))
        selected_team_id = team_options[selected_team_name]
        page_num = st.number_input("Page", min_value=1, max_value=100, value=1)

    with st.spinner("Loading players..."):
        players, meta = get_players(team_id=selected_team_id, per_page=50, page=page_num)

    if players:
        df = pd.DataFrame(players)
        df["position_label"] = df["position"].apply(pos_label)
        df["age"] = pd.to_numeric(df["age"], errors="coerce")
        df["height_cm"] = pd.to_numeric(df["height_cm"], errors="coerce").replace(0, pd.NA)

        with col_right:
            st.metric("Players Found", meta.get("total", len(df)))

        st.markdown("---")
        col1, col2, col3 = st.columns(3)

        with col1:
            pos_counts = df["position_label"].value_counts().reset_index()
            pos_counts.columns = ["Position", "Count"]
            fig = px.pie(pos_counts, names="Position", values="Count", title="By Position", hole=0.4)
            st.plotly_chart(fig, width="stretch")

        with col2:
            age_df = df.dropna(subset=["age"])
            if not age_df.empty:
                fig = px.histogram(
                    age_df, x="age", nbins=20, title="Age Distribution",
                    color_discrete_sequence=["#3b82f6"],
                )
                st.plotly_chart(fig, width="stretch")

        with col3:
            nat_counts = df["nationality"].value_counts().reset_index().head(10)
            nat_counts.columns = ["Nationality", "Players"]
            fig = px.bar(
                nat_counts, x="Players", y="Nationality", orientation="h",
                color="Players", color_continuous_scale="Purples", title="Top Nationalities",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
            st.plotly_chart(fig, width="stretch")

        height_df = df.dropna(subset=["height_cm", "age"])
        if not height_df.empty and len(height_df) > 5:
            st.markdown("---")
            fig = px.scatter(
                height_df, x="age", y="height_cm", color="position_label",
                hover_data=["name", "nationality"],
                labels={"age": "Age", "height_cm": "Height (cm)", "position_label": "Position"},
                title="Height vs. Age by Position",
            )
            st.plotly_chart(fig, width="stretch")

        st.markdown("---")
        display_df = df[["name", "position_label", "age", "height_cm", "nationality"]].copy()
        display_df.columns = ["Name", "Position", "Age", "Height (cm)", "Nationality"]
        st.dataframe(display_df, width="stretch", hide_index=True)
    else:
        st.warning("No players found.")
