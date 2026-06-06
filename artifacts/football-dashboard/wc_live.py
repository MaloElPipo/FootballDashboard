"""Verrouillage EN DIRECT des résultats réels de la Coupe du Monde 2026.

Récupère les rencontres/résultats réels depuis l'API BSD (league 27) et convertit
les matchs TERMINÉS en la structure ``locked_results`` consommée par
``wc_simulator.simulate_tournament`` / ``simulate_bracket_mc``.

Pendant la compétition, cela fige les issues réelles (poules + élimination
directe) tout en laissant le reste du tableau être simulé en Monte-Carlo : la
simulation et le bracket reflètent ainsi les vrais qualifiés au fil des matchs.

Avant le coup d'envoi (ou si l'API est indisponible), ``build_locked_results``
renvoie des dictionnaires vides → comportement Monte-Carlo inchangé.
"""
from __future__ import annotations

import os
import unicodedata

import requests
import streamlit as st

from nations_data import WC2026_NATIONS

BSD_BASE_URL = "https://sports.bzzoiro.com/api"
WC_LEAGUE_ID = 27
WC_DATE_FROM = "2026-06-11"
WC_DATE_TO = "2026-07-19"

# Rounds BSD : 1/2/3 = journées de poule ; 5=quarts, 6=8es, 27=demies,
# 28/29=finale, 50=match pour la 3e place.
GROUP_ROUNDS = {1, 2, 3}
KO_ROUNDS = {5, 6, 27, 28, 29, 50}


def _norm(s: str) -> str:
    """Minuscule, sans accents, espaces normalisés — pour matcher les noms."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


# Noms BSD qui diffèrent des noms internes (nations_data) → code FIFA.
_ALIASES = {
    "usa": "USA", "united states": "USA", "united states of america": "USA",
    "south korea": "KOR", "korea republic": "KOR", "korea south": "KOR",
    "republic of korea": "KOR",
    "turkiye": "TUR", "turkey": "TUR",
    "czechia": "CZE", "czech republic": "CZE",
    "bosnia & herzegovina": "BIH", "bosnia and herzegovina": "BIH",
    "bosnia-herzegovina": "BIH", "bosnia": "BIH",
    "ivory coast": "CIV", "cote d'ivoire": "CIV", "cote divoire": "CIV",
    "dr congo": "COD", "congo dr": "COD", "democratic republic of congo": "COD",
    "cape verde": "CPV", "cabo verde": "CPV",
    "curacao": "CUW",
    "south africa": "RSA",
    "saudi arabia": "KSA",
    "new zealand": "NZL",
    "iran": "IRN", "ir iran": "IRN",
}


def _build_name_code_map() -> dict:
    m = {}
    for _conf, nations in WC2026_NATIONS.items():
        for n in nations:
            code = n["code"]
            m[_norm(n["name"])] = code
            m[_norm(n.get("fr", ""))] = code
            m[_norm(code)] = code
    m.update(_ALIASES)
    m.pop("", None)
    return m


_NAME_CODE = _build_name_code_map()


def bsd_name_to_code(name: str):
    """Nom d'équipe BSD → code FIFA 3 lettres, ou None si non résolu."""
    return _NAME_CODE.get(_norm(name))


@st.cache_data(ttl=60, show_spinner=False)
def fetch_wc_events() -> list:
    """Récupère tous les events CDM 2026 depuis BSD (paginé).

    TTL court (60 s) pour un suivi quasi temps réel. Renvoie [] en cas d'erreur
    ou d'absence de clé API (jamais d'exception : le verrouillage est best-effort).
    """
    key = os.environ.get("BSD_API_KEY", "")
    if not key:
        return []
    headers = {"Authorization": f"Token {key}"}
    all_events: list = []
    offset, limit = 0, 50
    for _ in range(20):  # garde-fou : max 1000 events
        try:
            r = requests.get(
                f"{BSD_BASE_URL}/events/",
                params={
                    "league": WC_LEAGUE_ID,
                    "date_from": WC_DATE_FROM,
                    "date_to": WC_DATE_TO,
                    "limit": limit,
                    "offset": offset,
                },
                headers=headers,
                timeout=30,
            )
            if r.status_code != 200:
                break
            data = r.json()
            results = data.get("results", [])
            if not results:
                break
            all_events.extend(results)
            total = data.get("count", 0) or 0
            if len(all_events) >= total or len(results) < limit:
                break
            offset += limit
        except Exception:
            break
    return all_events


def _ko_winner(ev: dict, hc: str, ac: str, hs: int, as_: int):
    """Détermine le vainqueur d'un match KO terminé.

    Temps réglementaire/prolongation d'abord, puis tirs au but via plusieurs
    noms de champ possibles, enfin un éventuel champ ``winner`` explicite.
    Renvoie None si indéterminable (on ne fige alors PAS le match).
    """
    if hs > as_:
        return hc
    if as_ > hs:
        return ac
    # Égalité → tirs au but (champs variables selon l'API)
    for hk, ak in (
        ("home_score_penalties", "away_score_penalties"),
        ("home_penalties", "away_penalties"),
        ("penalties_home", "penalties_away"),
        ("home_pens", "away_pens"),
        ("home_shootout", "away_shootout"),
    ):
        ph, pa = ev.get(hk), ev.get(ak)
        if isinstance(ph, (int, float)) and isinstance(pa, (int, float)) and ph != pa:
            return hc if ph > pa else ac
    # Champ vainqueur explicite éventuel
    for wk in ("winner", "winner_team", "winner_code", "winner_name"):
        w = ev.get(wk)
        if isinstance(w, str) and w:
            wc = bsd_name_to_code(w)
            if wc in (hc, ac):
                return wc
    return None


def build_locked_results(events: list) -> dict:
    """Convertit les events BSD TERMINÉS en ``locked_results``.

    Renvoie ``{"group": {(home_code, away_code): "H"/"D"/"A"},
              "ko": {frozenset({A, B}): winner_code}}``.

    Les matchs dont les équipes ne se résolvent pas en codes FIFA, sans score,
    ou dont le vainqueur KO est indéterminable, sont ignorés (best-effort).
    """
    group: dict = {}
    ko: dict = {}
    for ev in events or []:
        if ev.get("status") != "finished":
            continue
        hc = bsd_name_to_code(ev.get("home_team", ""))
        ac = bsd_name_to_code(ev.get("away_team", ""))
        if not hc or not ac or hc == ac:
            continue
        hs = ev.get("home_score")
        as_ = ev.get("away_score")
        if not isinstance(hs, (int, float)) or not isinstance(as_, (int, float)):
            continue
        rnd = ev.get("round_number")
        if rnd in GROUP_ROUNDS:
            if hs > as_:
                group[(hc, ac)] = "H"
            elif hs < as_:
                group[(hc, ac)] = "A"
            else:
                group[(hc, ac)] = "D"
        elif rnd in KO_ROUNDS:
            w = _ko_winner(ev, hc, ac, int(hs), int(as_))
            if w:
                ko[frozenset((hc, ac))] = w
    return {"group": group, "ko": ko}


def locked_cache_key(locked: dict):
    """Clé hashable et stable pour ``st.cache_data`` à partir d'un locked dict."""
    grp = tuple(sorted(
        (f"{h}>{a}", r) for (h, a), r in locked.get("group", {}).items()
    ))
    ko = tuple(sorted(
        (tuple(sorted(fs)), w) for fs, w in locked.get("ko", {}).items()
    ))
    return (grp, ko)


def locked_from_key(key):
    """Reconstruit le locked dict depuis la clé produite par ``locked_cache_key``."""
    if not key:
        return {"group": {}, "ko": {}}
    grp_items, ko_items = key
    group = {}
    for gk, r in grp_items:
        h, a = gk.split(">")
        group[(h, a)] = r
    ko = {}
    for pair, w in ko_items:
        ko[frozenset(pair)] = w
    return {"group": group, "ko": ko}
