import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from functools import lru_cache

API_BASE = os.environ.get("STATS_API_URL", "https://api.thestatsapi.com/api")
API_KEY = os.environ.get("STATS_API_KEY", "")

HEADERS = {"Authorization": f"Bearer {API_KEY}"}

st.set_page_config(
    page_title="Football Analytics Dashboard",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_data(ttl=300)
def fetch(endpoint, params=None):
    url = f"{API_BASE}/football/{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params or {}, timeout=15)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=300)
def get_competitions(per_page=100):
    data = fetch("competitions", {"per_page": per_page})
    return data.get("data", [])


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


POSITION_MAP = {
    "GK": "Goalkeeper",
    "D": "Defender",
    "M": "Midfielder",
    "F": "Forward",
    "0": "Unknown",
}


def pos_label(code):
    return POSITION_MAP.get(code, code or "Unknown")


st.title("⚽ Football Analytics Dashboard")
st.caption("Live data powered by TheStatsAPI")

page = st.sidebar.radio(
    "Navigate",
    ["🏟️ Competitions & Teams", "👤 Player Explorer", "🗓️ Match Results"],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.markdown("**Data refreshes every 5 minutes.**")

if page == "🏟️ Competitions & Teams":
    st.header("🏟️ Competitions & Teams")

    with st.spinner("Loading competitions..."):
        competitions = get_competitions(per_page=100)

    comps_df = pd.DataFrame(competitions)
    country_counts = comps_df["country"].value_counts().reset_index()
    country_counts.columns = ["Country", "Competitions"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Competitions", len(comps_df))
    col2.metric("Countries", comps_df["country"].nunique())
    col3.metric("With Team Stats", int(comps_df.get("has_team_stats", pd.Series()).sum()))

    st.markdown("---")

    tab1, tab2 = st.tabs(["📊 Competitions by Country", "🔍 Team Explorer"])

    with tab1:
        top_n = st.slider("Show top N countries", 5, 30, 15)
        top_countries = country_counts.head(top_n)

        fig = px.bar(
            top_countries,
            x="Competitions",
            y="Country",
            orientation="h",
            color="Competitions",
            color_continuous_scale="Blues",
            title=f"Top {top_n} Countries by Number of Competitions",
            labels={"Competitions": "Number of Competitions"},
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False, height=500)
        st.plotly_chart(fig, use_container_width=True)

        has_stats = comps_df[comps_df["has_team_stats"] == True]["country"].value_counts().reset_index()
        has_stats.columns = ["Country", "Count"]
        if not has_stats.empty:
            fig2 = px.pie(
                has_stats.head(10),
                names="Country",
                values="Count",
                title="Competitions with Team Stats — by Country",
                hole=0.4,
            )
            st.plotly_chart(fig2, use_container_width=True)

    with tab2:
        country_list = sorted(comps_df["country"].unique())
        selected_country = st.selectbox("Filter by country", ["All"] + country_list)

        filtered_comps = comps_df if selected_country == "All" else comps_df[comps_df["country"] == selected_country]
        comp_options = {row["name"]: row["id"] for _, row in filtered_comps.iterrows()}

        if comp_options:
            selected_comp_name = st.selectbox("Select a competition", list(comp_options.keys()))
            selected_comp_id = comp_options[selected_comp_name]

            with st.spinner(f"Loading teams for {selected_comp_name}..."):
                teams, meta = get_teams(competition_id=selected_comp_id, per_page=50)

            if teams:
                teams_df = pd.DataFrame(teams)
                st.write(f"**{meta.get('total', len(teams))} teams** in {selected_comp_name}")

                country_team_counts = teams_df["country"].value_counts().reset_index()
                country_team_counts.columns = ["Country", "Teams"]

                if len(country_team_counts) > 1:
                    fig = px.bar(
                        country_team_counts,
                        x="Country",
                        y="Teams",
                        color="Teams",
                        color_continuous_scale="Greens",
                        title="Team Nationalities in This Competition",
                    )
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)

                st.dataframe(
                    teams_df[["name", "short_name", "country"]].rename(columns={"name": "Team", "short_name": "Short Name", "country": "Country"}),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No team data available for this competition.")
        else:
            st.info("No competitions found for the selected country.")


elif page == "👤 Player Explorer":
    st.header("👤 Player Explorer")

    col_left, col_right = st.columns([1, 2])

    with col_left:
        st.subheader("Filters")

        with st.spinner("Loading teams..."):
            teams, _ = get_teams(per_page=50)

        team_options = {"All teams (sample)": None}
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
            st.metric("Total Players Found", meta.get("total", len(df)))

        st.markdown("---")

        col1, col2, col3 = st.columns(3)

        with col1:
            pos_counts = df["position_label"].value_counts().reset_index()
            pos_counts.columns = ["Position", "Count"]
            fig = px.pie(pos_counts, names="Position", values="Count", title="Players by Position", hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            age_df = df.dropna(subset=["age"])
            if not age_df.empty:
                fig = px.histogram(
                    age_df, x="age", nbins=20, title="Age Distribution",
                    color_discrete_sequence=["#3b82f6"],
                    labels={"age": "Age", "count": "Players"},
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No age data available.")

        with col3:
            nat_counts = df["nationality"].value_counts().reset_index().head(10)
            nat_counts.columns = ["Nationality", "Players"]
            fig = px.bar(
                nat_counts, x="Players", y="Nationality", orientation="h",
                color="Players", color_continuous_scale="Purples",
                title="Top Nationalities",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

        height_df = df.dropna(subset=["height_cm", "age"])
        if not height_df.empty and len(height_df) > 5:
            st.markdown("---")
            st.subheader("Height vs. Age by Position")
            fig = px.scatter(
                height_df,
                x="age", y="height_cm",
                color="position_label",
                hover_data=["name", "nationality"],
                labels={"age": "Age", "height_cm": "Height (cm)", "position_label": "Position"},
                title="Player Height vs. Age",
            )
            fig.update_layout(legend_title="Position")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader("Player List")
        display_df = df[["name", "position_label", "age", "height_cm", "nationality"]].copy()
        display_df.columns = ["Name", "Position", "Age", "Height (cm)", "Nationality"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.warning("No players found.")


elif page == "🗓️ Match Results":
    st.header("🗓️ Match Results")

    with st.spinner("Loading competitions..."):
        competitions = get_competitions(per_page=100)

    comps_df = pd.DataFrame(competitions)
    comp_options = {"All competitions": None}
    comp_options.update({c["name"]: c["id"] for c in competitions})

    col1, col2, col3 = st.columns(3)
    with col1:
        selected_comp_name = st.selectbox("Competition", list(comp_options.keys()))
        selected_comp_id = comp_options[selected_comp_name]
    with col2:
        status_filter = st.selectbox("Status", ["All", "finished", "scheduled", "in_progress"])
    with col3:
        page_num = st.number_input("Page", min_value=1, max_value=500, value=1)

    status = None if status_filter == "All" else status_filter

    with st.spinner("Loading matches..."):
        matches, meta = get_matches(competition_id=selected_comp_id, status=status, per_page=50, page=page_num)

    if matches:
        df = pd.DataFrame(matches)
        df["home_team_name"] = df["home_team"].apply(lambda x: x.get("name", "") if isinstance(x, dict) else "")
        df["away_team_name"] = df["away_team"].apply(lambda x: x.get("name", "") if isinstance(x, dict) else "")
        df["home_score"] = df["score"].apply(lambda x: x.get("home", 0) if isinstance(x, dict) else 0)
        df["away_score"] = df["score"].apply(lambda x: x.get("away", 0) if isinstance(x, dict) else 0)
        df["total_goals"] = df["home_score"] + df["away_score"]
        df["date"] = pd.to_datetime(df["utc_date"]).dt.date

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Matches Found", meta.get("total", len(df)))
        col2.metric("Shown on this Page", len(df))
        if status == "finished":
            col3.metric("Avg Goals/Match", f"{df['total_goals'].mean():.1f}")
            high_scoring = df[df["total_goals"] >= 4]
            col4.metric("High-scoring (4+ goals)", len(high_scoring))

        st.markdown("---")

        if status == "finished" and len(df) > 0:
            tab1, tab2 = st.tabs(["📊 Goal Analysis", "📋 Match List"])

            with tab1:
                col1, col2 = st.columns(2)

                with col1:
                    goals_dist = df["total_goals"].value_counts().sort_index().reset_index()
                    goals_dist.columns = ["Total Goals", "Matches"]
                    fig = px.bar(
                        goals_dist, x="Total Goals", y="Matches",
                        color="Matches", color_continuous_scale="Reds",
                        title="Distribution of Goals per Match",
                    )
                    fig.update_layout(showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)

                with col2:
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
                    st.plotly_chart(fig, use_container_width=True)

                goals_by_day = df.groupby("date")["total_goals"].mean().reset_index()
                goals_by_day.columns = ["Date", "Avg Goals"]
                if len(goals_by_day) > 1:
                    fig = px.line(
                        goals_by_day, x="Date", y="Avg Goals",
                        title="Average Goals per Match over Time",
                        markers=True,
                    )
                    st.plotly_chart(fig, use_container_width=True)

            with tab2:
                display_cols = ["date", "home_team_name", "home_score", "away_score", "away_team_name", "status", "matchday"]
                display = df[display_cols].copy()
                display.columns = ["Date", "Home Team", "Home", "Away", "Away Team", "Status", "Matchday"]
                st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            display_cols = ["date", "home_team_name", "home_score", "away_score", "away_team_name", "status", "matchday"]
            display = df[display_cols].copy()
            display.columns = ["Date", "Home Team", "Home", "Away", "Away Team", "Status", "Matchday"]
            st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No matches found for the selected filters.")
