"""
Page Roadmap du dashboard — lecture du JSON live/data/roadmap.json.

Le JSON est piloté par l'utilisateur (édité via son outil externe).
Cette page se contente de l'afficher proprement. Aucune écriture côté Python.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import streamlit as st

ROADMAP_PATH = Path(__file__).resolve().parent / "data" / "roadmap.json"

STATUS_LABELS = {
    "todo": "À faire",
    "doing": "En cours",
    "done": "Fait",
    "blocked": "Bloqué",
    "waiting": "En attente",
    "review": "À valider",
}

STATUS_COLORS = {
    "todo":    {"bg": "#e5e7eb", "fg": "#374151", "border": "#9ca3af"},
    "doing":   {"bg": "#fef3c7", "fg": "#92400e", "border": "#f59e0b"},
    "done":    {"bg": "#d1fae5", "fg": "#065f46", "border": "#10b981"},
    "blocked": {"bg": "#fee2e2", "fg": "#991b1b", "border": "#ef4444"},
    "waiting": {"bg": "#dbeafe", "fg": "#1e40af", "border": "#3b82f6"},
    "review":  {"bg": "#ede9fe", "fg": "#5b21b6", "border": "#8b5cf6"},
}

PRIORITY_LABELS = {
    1: ("P1", "#dc2626"),
    2: ("P2", "#ea580c"),
    3: ("P3", "#ca8a04"),
    4: ("P4", "#2563eb"),
    5: ("P5", "#6b7280"),
}


def _load_roadmap() -> dict | None:
    if not ROADMAP_PATH.exists():
        return None
    try:
        with open(ROADMAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Roadmap illisible : {e}")
        return None


def _pill(text: str, status: str) -> str:
    c = STATUS_COLORS.get(status, STATUS_COLORS["todo"])
    return (
        f"<div style='background:{c['bg']};color:{c['fg']};"
        f"border-left:3px solid {c['border']};padding:6px 10px;"
        f"margin:4px 0;border-radius:4px;font-size:13px;line-height:1.3;'>"
        f"{text}</div>"
    )


def _priority_badge(p: int) -> str:
    label, color = PRIORITY_LABELS.get(p, ("P?", "#6b7280"))
    return (
        f"<span style='background:{color};color:white;padding:2px 8px;"
        f"border-radius:10px;font-size:11px;font-weight:600;"
        f"vertical-align:middle;'>{label}</span>"
    )


def _module_progress(module: dict) -> tuple[int, int]:
    """Retourne (n_done_checkpoints, n_total_checkpoints)."""
    cps = module.get("checkpoints", [])
    return sum(1 for c in cps if c.get("done")), len(cps)


def _global_kpis(modules: list[dict]) -> dict:
    n_modules = len(modules)
    all_tasks = [t for m in modules for t in m.get("tasks", [])]
    by_status = {s: 0 for s in STATUS_LABELS}
    for t in all_tasks:
        s = t.get("status", "todo")
        by_status[s] = by_status.get(s, 0) + 1
    all_cps = [c for m in modules for c in m.get("checkpoints", [])]
    cp_done = sum(1 for c in all_cps if c.get("done"))
    return {
        "n_modules": n_modules,
        "n_tasks": len(all_tasks),
        "by_status": by_status,
        "cp_done": cp_done,
        "cp_total": len(all_cps),
    }


def render_roadmap_page() -> None:
    st.header("🗺️ Roadmap projet")
    st.caption("Vue de pilotage — éditée hors application, lue ici en lecture seule.")

    data = _load_roadmap()
    if data is None:
        st.warning(
            f"Aucun fichier roadmap trouvé à `{ROADMAP_PATH.relative_to(ROADMAP_PATH.parents[2])}`.\n\n"
            "Dépose ton JSON exporté à cet emplacement et recharge la page."
        )
        return

    modules = data.get("modules", [])
    if not modules:
        st.info("Roadmap vide.")
        return

    # Tri par priorité (1 = plus prioritaire) puis par titre
    modules = sorted(modules, key=lambda m: (m.get("priority", 99), m.get("title", "")))

    # KPIs globaux
    k = _global_kpis(modules)
    cp_pct = round(100 * k["cp_done"] / k["cp_total"]) if k["cp_total"] else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Modules", k["n_modules"])
    c2.metric("Tâches totales", k["n_tasks"])
    c3.metric("En cours", k["by_status"].get("doing", 0))
    c4.metric("Faites", k["by_status"].get("done", 0))
    c5.metric("Checkpoints", f"{k['cp_done']}/{k['cp_total']}", f"{cp_pct} %")

    # Métadonnée fichier
    mtime = datetime.fromtimestamp(ROADMAP_PATH.stat().st_mtime)
    st.caption(f"Dernière mise à jour du JSON : **{mtime.strftime('%d/%m/%Y %H:%M')}**")

    st.markdown("---")

    # Filtres
    fc1, fc2 = st.columns([1, 2])
    with fc1:
        priorities_present = sorted({m.get("priority", 99) for m in modules})
        sel_prios = st.multiselect(
            "Filtrer par priorité",
            priorities_present,
            default=priorities_present,
            format_func=lambda p: PRIORITY_LABELS.get(p, (f"P{p}", ""))[0],
        )
    with fc2:
        sel_statuses = st.multiselect(
            "N'afficher que les tâches de statut",
            list(STATUS_LABELS.keys()),
            default=[],
            format_func=lambda s: STATUS_LABELS[s],
            help="Vide = afficher tous les statuts.",
        )

    modules_view = [m for m in modules if m.get("priority", 99) in sel_prios]

    # Affichage modules
    for module in modules_view:
        emoji = module.get("emoji", "📦")
        title = module.get("title", "Sans titre")
        prio = module.get("priority", 99)
        notes = module.get("notes", "")

        with st.container(border=True):
            # Header
            header_html = (
                f"<div style='display:flex;align-items:center;gap:10px;"
                f"margin-bottom:6px;'>"
                f"<span style='font-size:22px'>{emoji}</span>"
                f"<span style='font-size:18px;font-weight:600;'>{title}</span>"
                f"{_priority_badge(prio)}"
                f"</div>"
            )
            st.markdown(header_html, unsafe_allow_html=True)
            if notes:
                st.markdown(
                    f"<div style='color:#6b7280;font-style:italic;font-size:13px;"
                    f"margin-bottom:10px;'>{notes}</div>",
                    unsafe_allow_html=True,
                )

            # Barre progression checkpoints
            cp_done, cp_total = _module_progress(module)
            if cp_total:
                pct = cp_done / cp_total
                st.progress(pct, text=f"Checkpoints : {cp_done}/{cp_total}  ({int(pct*100)} %)")

            # Tâches en colonnes par statut
            tasks = module.get("tasks", [])
            if sel_statuses:
                tasks = [t for t in tasks if t.get("status", "todo") in sel_statuses]

            if not tasks:
                st.caption("_Aucune tâche correspondant aux filtres._")
            else:
                # On groupe en 4 colonnes principales : todo / doing / waiting+review / done+blocked
                # Mais comme l'utilisateur n'a que 4 statuts dans son JSON actuel,
                # on affiche dynamiquement les colonnes présentes.
                ordered = ["todo", "doing", "waiting", "review", "done", "blocked"]
                present = [s for s in ordered if any(t.get("status", "todo") == s for t in tasks)]
                cols = st.columns(len(present)) if present else []
                for col, status in zip(cols, present):
                    with col:
                        items = [t for t in tasks if t.get("status", "todo") == status]
                        st.markdown(
                            f"<div style='font-size:12px;font-weight:600;"
                            f"color:{STATUS_COLORS[status]['fg']};"
                            f"text-transform:uppercase;letter-spacing:0.5px;"
                            f"margin-bottom:4px;'>"
                            f"{STATUS_LABELS[status]} · {len(items)}</div>",
                            unsafe_allow_html=True,
                        )
                        for t in items:
                            st.markdown(_pill(t.get("text", "?"), status), unsafe_allow_html=True)

            # Checkpoints en bas
            cps = module.get("checkpoints", [])
            if cps:
                st.markdown(
                    "<div style='font-size:12px;font-weight:600;color:#6b7280;"
                    "text-transform:uppercase;letter-spacing:0.5px;margin-top:12px;"
                    "margin-bottom:4px;'>🎯 Checkpoints</div>",
                    unsafe_allow_html=True,
                )
                for cp in cps:
                    icon = "✅" if cp.get("done") else "⬜"
                    color = "#065f46" if cp.get("done") else "#6b7280"
                    st.markdown(
                        f"<div style='color:{color};font-size:13px;"
                        f"margin:2px 0;'>{icon} {cp.get('text', '')}</div>",
                        unsafe_allow_html=True,
                    )

    st.markdown("---")
    st.caption(
        "ℹ️ Cette page est en lecture seule. Pour modifier la roadmap, édite "
        f"directement `{ROADMAP_PATH.name}` (ré-export depuis ton outil)."
    )
