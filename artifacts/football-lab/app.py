"""Football Lab — environnement de test isole.

Sandbox pour valider les ameliorations BSD avant push prod :
  Phase 1 — Triple inversion 1X2 + O/U + BTTS
  Phase 2 — Recalibrage Elo via xG getStandings
  Phase 3 — xG totaux poules CDM + meilleurs 3emes
  Phase 4 — Migration player stats BSD
  Phase 5 — Tracker mouvement cotes
  Phase 6 — Synthese & migration

Le labo lit la prod (snapshots dates) mais n'y ecrit jamais.
"""
from __future__ import annotations

import streamlit as st

from lab import snapshots
from lab.calibration import bsd_client
from lab.pages import phase1_btts

st.set_page_config(
    page_title="Football Lab",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("Football Lab")
st.sidebar.caption("Sandbox de test isole — la prod reste intouchee.")

PAGES = {
    "Accueil": "home",
    "Phase 1 — Inversion BTTS": "phase1",
    "Phase 2 — Elo xG": "phase2",
    "Phase 3 — xG Poules CDM": "phase3",
    "Phase 4 — Player Stats": "phase4",
    "Phase 5 — Sharp Tracker": "phase5",
    "Phase 6 — Synthese": "phase6",
    "Admin — Snapshots & Cache": "admin",
}

choice = st.sidebar.radio("Navigation", list(PAGES.keys()), index=0)
page = PAGES[choice]

st.sidebar.divider()
st.sidebar.markdown("**Etat labo**")
try:
    stats = bsd_client.cache_stats()
    st.sidebar.caption(
        f"Cache BSD : {stats['count']} entrees, {stats['size_kb']} ko"
    )
except Exception as e:
    st.sidebar.caption(f"Cache BSD : erreur ({e})")

snap_list = snapshots.list_snapshots()
st.sidebar.caption(f"Snapshots prod : {len(snap_list)}")


# ─────────────────────────────────────────────────────────────────────────────
# Pages
# ─────────────────────────────────────────────────────────────────────────────


def render_home():
    st.title("Football Lab")
    st.markdown(
        """
Bienvenue dans le **labo de validation BSD**. Tout ce qui est teste ici est
isole de la prod (`football-dashboard`). Aucune ecriture vers la prod n'est
realisee depuis ce labo.

**Pipeline de validation en 6 phases :**

1. **Inversion BTTS** — passer de double (1X2+O/U) a triple (1X2+O/U+BTTS) inversion via Dixon-Coles 3 parametres
2. **Elo via xG** — reconstruire les Elo equipes via xGF/xGA 5 saisons des standings BSD
3. **xG poules CDM** — calculer xG totaux par equipe sur phase de poule, recalibrer Elo nation, ameliorer la maille meilleurs 3emes
4. **Player stats** — migrer du scraper Sofascore vers BSD getPlayerStats
5. **Sharp tracker** — tracker SHORTENING/DRIFTING sur compareOdds pour detecter le sharp money
6. **Synthese** — go/no-go feature par feature + plan migration prod

Chaque phase a sa page dediee avec tableaux comparatifs ancien vs nouveau,
metriques, et un report markdown qui acte la decision.
"""
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Phases setup", "0 / 6")
    with c2:
        st.metric("Snapshots prod", len(snap_list))
    with c3:
        try:
            st.metric("Entrees cache BSD", bsd_client.cache_stats()["count"])
        except Exception:
            st.metric("Entrees cache BSD", "?")

    st.divider()
    st.subheader("Prochaine etape")
    st.info(
        "Aller dans **Admin — Snapshots & Cache** pour figer un snapshot prod "
        "de reference. Puis lancer la Phase 1."
    )


def render_placeholder(title: str, desc: str):
    st.title(title)
    st.info(desc)
    st.caption("Cette phase n'est pas encore developpee.")


def render_admin():
    st.title("Admin — Snapshots & Cache")

    st.subheader("Snapshots prod")
    st.caption(
        "Un snapshot copie les fichiers Elo / cotes prod dans `lab/data/snapshots/` "
        "pour reference. Le labo lit ces copies, jamais les originaux."
    )

    col1, col2 = st.columns([1, 3])
    with col1:
        tag = st.text_input("Tag (optionnel)", placeholder="pre_phase1")
        if st.button("Prendre un snapshot maintenant", type="primary"):
            out = snapshots.snapshot_prod(tag or None)
            st.success(f"Snapshot cree : {len(out)} fichiers traites")
            st.json(out)
    with col2:
        st.markdown("**Snapshots existants :**")
        for s in snap_list:
            with st.expander(f"{s['tag']} — pris le {s['taken_at']}"):
                st.json(s["files"])

    st.divider()
    st.subheader("Cache BSD labo")
    try:
        stats = bsd_client.cache_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entrees", stats["count"])
        c2.metric("Taille (ko)", stats["size_kb"])
        c3.metric("Plus ancienne (h)", stats["oldest_hours"])
        c4.metric("Plus recente (h)", stats["newest_hours"])
    except Exception as e:
        st.error(f"Cache stats indisponibles : {e}")

    if st.button("Vider le cache BSD"):
        n = bsd_client.clear_cache()
        st.success(f"{n} entrees supprimees")
        st.rerun()


# Router
if page == "home":
    render_home()
elif page == "phase1":
    phase1_btts.render()
elif page == "phase2":
    render_placeholder(
        "Phase 2 — Recalibrage Elo via xG",
        "Reconstruction Elo equipes depuis getStandings 5 saisons x 7 leagues. "
        "Agregation joueurs vers nations CDM. A developper.",
    )
elif page == "phase3":
    render_placeholder(
        "Phase 3 — xG totaux poules CDM",
        "Calcul xGF/xGA par equipe sur phase poule (model + marche). "
        "Recalibrage Elo nation + amelioration meilleurs 3emes. A developper.",
    )
elif page == "phase4":
    render_placeholder(
        "Phase 4 — Player stats BSD",
        "Wrapper getPlayerStats + comparaison 30 joueurs vs Sofascore. "
        "Test couverture extension hors top 5. A developper.",
    )
elif page == "phase5":
    render_placeholder(
        "Phase 5 — Sharp money tracker",
        "Snapshot bi-quotidien compareOdds avec movement SHORTENING/DRIFTING. "
        "Observation 3 semaines. A developper.",
    )
elif page == "phase6":
    render_placeholder(
        "Phase 6 — Synthese & migration prod",
        "Recap 4 reports + plan feature flags pour bascule progressive en prod. "
        "Sera rempli au fil des phases.",
    )
elif page == "admin":
    render_admin()
