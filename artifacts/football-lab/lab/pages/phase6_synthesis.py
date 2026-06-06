"""Phase 6 — Synthese + decision GO/NO-GO + plan migration prod."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st


REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


PHASES = [
    {
        "id": 1, "name": "Triple inversion BTTS",
        "report": "01_inversion_btts.md",
        "feature_flag": "INVERSION_METHOD",
        "values": ["double_indep", "triple_dixon_coles"],
        "criteria": [
            "|residuel BTTS| triple < 50 % du double sur >= 80 % des matchs",
            "Log-loss 1X2 triple <= log-loss 1X2 double + 0.002",
            "Taux d'echec optimiseur < 5 %",
        ],
    },
    {
        "id": 2, "name": "Recalibrage Elo via xG",
        "report": "02_elo_xg.md",
        "feature_flag": "ELO_SOURCE",
        "values": ["pin_calibrated", "xg_regression", "blend_50_50"],
        "criteria": [
            "Log-loss Elo_xg <= log-loss Elo_prod + 0.005 sur 100+ matchs",
            "Brier Elo_xg <= Brier Elo_prod + 0.005",
            "ROI cumule >= ROI prod sur PL 24/25 + 25/26",
        ],
    },
    {
        "id": 3, "name": "xG poules CDM + 3emes correle",
        "report": "03_xg_pools_cdm.md",
        "feature_flag": "CDM_THIRDS_METHOD",
        "values": ["independent_poisson", "correlated_form"],
        "criteria": [
            "Convergence boucle B en <= 3 iterations",
            "Distribution meilleurs 3emes : delta P_qualif < 10 pp",
            "Value bets identifiees retrospectivement profitables",
        ],
    },
    {
        "id": 4, "name": "Migration player stats BSD",
        "report": "04_player_stats.md",
        "feature_flag": "PLAYER_STATS_SOURCE",
        "values": ["sofascore_scrape", "bsd_api"],
        "criteria": [
            "Couverture BSD sur forward log >= 90 %",
            "Couverture extension hors top 5 >= 70 %",
            "Taux DISAGREE goals (> 1) <= 10 %",
            "Taux DISAGREE xG (> 0.5) <= 25 %",
        ],
    },
    {
        "id": 5, "name": "Sharp money tracker",
        "report": None,
        "feature_flag": "SHARP_TRACKER",
        "values": ["off", "observation_only", "signal_active"],
        "criteria": [
            "Setup operationnel (cron bi-quotidien)",
            "3 semaines d'historique avant evaluation predictive",
        ],
    },
]


def section_summary():
    st.subheader("Synthese par phase")
    rows = []
    for p in PHASES:
        rpt_path = REPORTS_DIR / p["report"] if p["report"] else None
        rpt_exists = rpt_path.exists() if rpt_path else False
        rows.append({
            "phase": p["id"],
            "feature": p["name"],
            "feature_flag": p["feature_flag"],
            "values": " / ".join(p["values"]),
            "report_dispo": "oui" if rpt_exists else "non",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def section_decision_grid():
    st.subheader("Grille decision GO / SHADOW / NO-GO par phase")
    st.caption("A remplir manuellement apres les backtests de chaque phase.")

    if "decision_grid" not in st.session_state:
        st.session_state["decision_grid"] = {p["id"]: "PENDING" for p in PHASES}

    for p in PHASES:
        with st.expander(f"Phase {p['id']} — {p['name']}", expanded=False):
            st.markdown(f"**Feature flag prod** : `{p['feature_flag']}`")
            st.markdown(f"**Valeurs** : {', '.join(p['values'])}")
            st.markdown("**Criteres go :**")
            for c in p["criteria"]:
                st.markdown(f"- {c}")
            choice = st.radio(
                f"Decision phase {p['id']}",
                ["PENDING", "NO-GO", "SHADOW", "GO blend 20%", "GO blend 50%", "GO 100%"],
                index=0, key=f"decision_{p['id']}", horizontal=True,
            )
            st.session_state["decision_grid"][p["id"]] = choice

    st.divider()
    summary = pd.DataFrame([
        {"phase": p["id"], "feature": p["name"], "decision": st.session_state["decision_grid"][p["id"]]}
        for p in PHASES
    ])
    st.dataframe(summary, hide_index=True, width="stretch")


def section_migration_plan():
    st.subheader("Plan de bascule progressive")
    st.markdown(
        """
**Pour chaque feature qui passe GO en phase de validation :**

1. **Etape 0 — Shadow** (1-2 semaines)
   - Le nouveau modele tourne en parallele du prod, ses outputs sont logges
   - Aucune mise / aucune publication. Comparaison statistique quotidienne.

2. **Etape 1 — Blend 80 / 20** (2 semaines)
   - Les probas publiees sont `0.8 * prod + 0.2 * nouveau`
   - Forward log marque la source (`SOURCE=blend_20`)
   - Si KPI degrade -> rollback feature flag

3. **Etape 2 — Blend 50 / 50** (2 semaines)
   - Verification stabilite (drift Elo, ROI, log-loss)

4. **Etape 3 — Migration 100 %**
   - Feature flag pointe sur la nouvelle valeur
   - L'ancien code reste 30 jours en fallback puis depreciation

**Feature flags a ajouter en prod** :
```python
# artifacts/football-dashboard/feature_flags.py
INVERSION_METHOD = os.getenv("INVERSION_METHOD", "double_indep")
ELO_SOURCE = os.getenv("ELO_SOURCE", "pin_calibrated")
CDM_THIRDS_METHOD = os.getenv("CDM_THIRDS_METHOD", "independent_poisson")
PLAYER_STATS_SOURCE = os.getenv("PLAYER_STATS_SOURCE", "sofascore_scrape")
SHARP_TRACKER = os.getenv("SHARP_TRACKER", "off")
```

Chaque module prod consomme le flag avant d'invoquer l'algo (V1 ou V2).

**Rollback** : il suffit de changer la valeur du flag (env var) puis restart
workflow `artifacts/football-dashboard: web`. Aucune migration de schema, aucune
perte de donnees.
"""
    )


def render():
    st.title("Phase 6 — Synthese & migration prod")
    tab1, tab2, tab3 = st.tabs(["1. Synthese", "2. Grille decision", "3. Plan bascule"])
    with tab1:
        section_summary()
    with tab2:
        section_decision_grid()
    with tab3:
        section_migration_plan()
