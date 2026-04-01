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
    ["🗓️ Match Results", "🏟️ Teams", "👤 Players", "🤖 Assistant IA"],
    label_visibility="visible",
)

active_competitions = ALL_CURATED
selected_group = "All International & Top Leagues"

if page != "🤖 Assistant IA":
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
