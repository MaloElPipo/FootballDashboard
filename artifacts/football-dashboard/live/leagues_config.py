"""Registre central des compétitions supportées par le pipeline générique.

Source unique de vérité pour le mapping multi-source :
    BSD id  ←→  StatsHub uTID  ←→  TheOddsAPI key  ←→  Betclic slug

Étendu au-delà du Top 5 pour supporter UCL/UEL/UECL et ~25 ligues domestiques.
Voir `.local/notes/statshub-mapping-2026-04-27.md` pour la cartographie complète.

Garde-fous :
- Aucun import de modules `predict_today` / `g2_engine` (évite cycles).
- READ-ONLY : ce fichier décrit, il n'agit pas.
- Tier 1 = activé par défaut dans le pipeline ; Tier 2 = backup (données limitées).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LeagueConfig:
    slug: str
    name: str
    region: str          # "uefa" | "top5" | "europe_other" | "americas" | "asia_middle_east" | "africa"
    country: str
    flag: str            # emoji
    bsd_id: Optional[int]
    statshub_utid: Optional[int]
    theoddsapi_key: Optional[str]
    betclic_slug: Optional[str]      # ex: "champions-league-s15" ou None
    betclic_sport_prefix: Optional[str] = "football-s1"
    betclic_comp_id: Optional[str] = None
    tier: int = 1                    # 1 = active, 2 = backup
    is_uefa: bool = False
    is_cup: bool = False
    label: str = ""                  # affichage UI (rempli auto si vide)

    def display_label(self) -> str:
        return self.label or f"{self.flag} {self.name}".strip()


# === Registre 30 compétitions ===========================================
# IDs vérifiés via mcpBSD_listLeagues le 27/04/2026 + StatsHub
# /api/player/{id}/tournaments-and-seasons
LEAGUES: dict[str, LeagueConfig] = {
    # --- UEFA (Tier 1) ----------------------------------------------------
    "champions_league": LeagueConfig(
        slug="champions_league", name="Champions League", region="uefa",
        country="Europe", flag="🇪🇺",
        bsd_id=7, statshub_utid=7,
        theoddsapi_key="soccer_uefa_champs_league",
        betclic_slug="champions-league-s15", betclic_comp_id="8",
        is_uefa=True,
    ),
    "europa_league": LeagueConfig(
        slug="europa_league", name="Europa League", region="uefa",
        country="Europe", flag="🇪🇺",
        bsd_id=8, statshub_utid=679,
        theoddsapi_key="soccer_uefa_europa_league",
        betclic_slug="ligue-europa-s3453", betclic_comp_id="3453",
        is_uefa=True,
    ),
    "conference_league": LeagueConfig(
        slug="conference_league", name="Conference League", region="uefa",
        country="Europe", flag="🇪🇺",
        bsd_id=None, statshub_utid=17015,        # absente BSD, présente StatsHub
        theoddsapi_key="soccer_uefa_europa_conference_league",
        betclic_slug=None,                        # à confirmer via scrape exploratoire
        is_uefa=True,
    ),

    # --- Top 5 (Tier 1) ---------------------------------------------------
    "premier_league": LeagueConfig(
        slug="premier_league", name="Premier League", region="top5",
        country="England", flag="🇬🇧",
        bsd_id=1, statshub_utid=17,
        theoddsapi_key="soccer_epl",
        betclic_slug="premier-league-s3", betclic_comp_id="3",
    ),
    "la_liga": LeagueConfig(
        slug="la_liga", name="La Liga", region="top5",
        country="Spain", flag="🇪🇸",
        bsd_id=3, statshub_utid=8,
        theoddsapi_key="soccer_spain_la_liga",
        betclic_slug="laliga-s7", betclic_comp_id="7",
    ),
    "serie_a": LeagueConfig(
        slug="serie_a", name="Serie A", region="top5",
        country="Italy", flag="🇮🇹",
        bsd_id=4, statshub_utid=23,
        theoddsapi_key="soccer_italy_serie_a",
        betclic_slug="serie-a-s6", betclic_comp_id="6",
    ),
    "bundesliga": LeagueConfig(
        slug="bundesliga", name="Bundesliga", region="top5",
        country="Germany", flag="🇩🇪",
        bsd_id=5, statshub_utid=35,
        theoddsapi_key="soccer_germany_bundesliga",
        betclic_slug="bundesliga-s5", betclic_comp_id="5",
    ),
    "ligue_1": LeagueConfig(
        slug="ligue_1", name="Ligue 1", region="top5",
        country="France", flag="🇫🇷",
        bsd_id=6, statshub_utid=34,
        theoddsapi_key="soccer_france_ligue_one",
        betclic_slug="ligue-1-s4", betclic_comp_id="4",
    ),

    # --- Europe (autres) (Tier 1) -----------------------------------------
    "eredivisie": LeagueConfig(
        slug="eredivisie", name="Eredivisie", region="europe_other",
        country="Netherlands", flag="🇳🇱",
        bsd_id=10, statshub_utid=37,
        theoddsapi_key="soccer_netherlands_eredivisie",
        betclic_slug=None,
    ),
    "liga_portugal": LeagueConfig(
        slug="liga_portugal", name="Liga Portugal", region="europe_other",
        country="Portugal", flag="🇵🇹",
        bsd_id=2, statshub_utid=238,
        theoddsapi_key="soccer_portugal_primeira_liga",
        betclic_slug=None,
    ),
    "pro_league": LeagueConfig(
        slug="pro_league", name="Pro League", region="europe_other",
        country="Belgium", flag="🇧🇪",
        bsd_id=14, statshub_utid=38,
        theoddsapi_key="soccer_belgium_first_div",
        betclic_slug=None,
    ),
    "super_lig": LeagueConfig(
        slug="super_lig", name="Süper Lig", region="europe_other",
        country="Turkey", flag="🇹🇷",
        bsd_id=11, statshub_utid=52,
        theoddsapi_key="soccer_turkey_super_league",
        betclic_slug=None,
    ),
    "championship": LeagueConfig(
        slug="championship", name="Championship", region="europe_other",
        country="England", flag="🇬🇧",
        bsd_id=12, statshub_utid=18,
        theoddsapi_key="soccer_efl_champ",
        betclic_slug=None,
    ),
    "scottish_premiership": LeagueConfig(
        slug="scottish_premiership", name="Scottish Premiership",
        region="europe_other",
        country="Scotland", flag="🇸🇨",
        bsd_id=13, statshub_utid=46,
        theoddsapi_key="soccer_spl",
        betclic_slug=None,
    ),
    "segunda_division": LeagueConfig(
        slug="segunda_division", name="Segunda División",
        region="europe_other",
        country="Spain", flag="🇪🇸",
        bsd_id=38, statshub_utid=54,
        theoddsapi_key="soccer_spain_segunda_division",
        betclic_slug=None,
    ),
    "allsvenskan": LeagueConfig(
        slug="allsvenskan", name="Allsvenskan", region="europe_other",
        country="Sweden", flag="🇸🇪",
        bsd_id=26, statshub_utid=40,
        theoddsapi_key="soccer_sweden_allsvenskan",
        betclic_slug=None,
    ),
    "ekstraklasa": LeagueConfig(
        slug="ekstraklasa", name="Ekstraklasa", region="europe_other",
        country="Poland", flag="🇵🇱",
        bsd_id=25, statshub_utid=202,
        theoddsapi_key="soccer_poland_ekstraklasa",
        betclic_slug=None,
    ),
    "greek_super_league": LeagueConfig(
        slug="greek_super_league", name="Greek Super League",
        region="europe_other",
        country="Greece", flag="🇬🇷",
        bsd_id=24, statshub_utid=185,
        theoddsapi_key="soccer_greece_super_league",
        betclic_slug=None,
    ),
    "swiss_super_league": LeagueConfig(
        slug="swiss_super_league", name="Swiss Super League",
        region="europe_other",
        country="Switzerland", flag="🇨🇭",
        bsd_id=15, statshub_utid=215,
        theoddsapi_key="soccer_switzerland_superleague",
        betclic_slug=None,
    ),

    # --- Amériques (Tier 1) -----------------------------------------------
    "mls": LeagueConfig(
        slug="mls", name="MLS", region="americas",
        country="USA", flag="🇺🇸",
        bsd_id=18, statshub_utid=242,
        theoddsapi_key="soccer_usa_mls",
        betclic_slug=None,
    ),
    "liga_mx_apertura": LeagueConfig(
        slug="liga_mx_apertura", name="Liga MX (Apertura)", region="americas",
        country="Mexico", flag="🇲🇽",
        bsd_id=19, statshub_utid=11621,
        theoddsapi_key="soccer_mexico_ligamx",
        betclic_slug=None,
    ),
    "liga_mx_clausura": LeagueConfig(
        slug="liga_mx_clausura", name="Liga MX (Clausura)", region="americas",
        country="Mexico", flag="🇲🇽",
        bsd_id=20, statshub_utid=11620,
        theoddsapi_key="soccer_mexico_ligamx",
        betclic_slug=None,
    ),
    "brasileirao_a": LeagueConfig(
        slug="brasileirao_a", name="Brasileirão Serie A", region="americas",
        country="Brazil", flag="🇧🇷",
        bsd_id=9, statshub_utid=325,
        theoddsapi_key="soccer_brazil_campeonato",
        betclic_slug=None,
    ),
    "copa_libertadores": LeagueConfig(
        slug="copa_libertadores", name="Copa Libertadores", region="americas",
        country="South America", flag="🌎",
        bsd_id=32, statshub_utid=384,
        theoddsapi_key="soccer_conmebol_copa_libertadores",
        betclic_slug=None,
        is_cup=True,
    ),
    "copa_sudamericana": LeagueConfig(
        slug="copa_sudamericana", name="Copa Sudamericana", region="americas",
        country="South America", flag="🌎",
        bsd_id=33, statshub_utid=480,
        theoddsapi_key="soccer_conmebol_copa_sudamericana",
        betclic_slug=None,
        is_cup=True,
    ),

    # --- Asie / Moyen-Orient (Tier 1) -------------------------------------
    "saudi_pro": LeagueConfig(
        slug="saudi_pro", name="Saudi Pro League", region="asia_middle_east",
        country="Saudi Arabia", flag="🇸🇦",
        bsd_id=17, statshub_utid=955,
        theoddsapi_key="soccer_saudi_arabia_pro_league",
        betclic_slug=None,
    ),
    "j1_league": LeagueConfig(
        slug="j1_league", name="J1 League", region="asia_middle_east",
        country="Japan", flag="🇯🇵",
        bsd_id=49, statshub_utid=196,
        theoddsapi_key="soccer_japan_j_league",
        betclic_slug=None,
    ),
    "k_league_1": LeagueConfig(
        slug="k_league_1", name="K League 1", region="asia_middle_east",
        country="South Korea", flag="🇰🇷",
        bsd_id=50, statshub_utid=752,
        theoddsapi_key="soccer_korea_kleague1",
        betclic_slug=None,
    ),

    # --- Afrique (Tier 1) -------------------------------------------------
    "caf_champions_league": LeagueConfig(
        slug="caf_champions_league", name="CAF Champions League",
        region="africa",
        country="Africa", flag="🌍",
        bsd_id=29, statshub_utid=320,
        theoddsapi_key=None,
        betclic_slug=None,
        is_cup=True,
    ),

    # --- Tier 2 (backup, données limitées) --------------------------------
    "brasileirao_b": LeagueConfig(
        slug="brasileirao_b", name="Brasileirão Serie B", region="americas",
        country="Brazil", flag="🇧🇷",
        bsd_id=34, statshub_utid=390,
        theoddsapi_key="soccer_brazil_serie_b",
        betclic_slug=None,
        tier=2,
    ),
}


# === Région → libellé UI ================================================
REGION_LABELS: dict[str, str] = {
    "uefa": "🌍 Compétitions UEFA",
    "top5": "⭐ Top 5 ligues",
    "europe_other": "🇪🇺 Autres ligues européennes",
    "americas": "🌎 Amériques",
    "asia_middle_east": "🌏 Asie / Moyen-Orient",
    "africa": "🌍 Afrique",
}

REGION_ORDER: list[str] = [
    "uefa", "top5", "europe_other",
    "americas", "asia_middle_east", "africa",
]


# === Helpers de lecture =================================================

def get_active_leagues(include_tier2: bool = False) -> list[LeagueConfig]:
    """Liste des ligues activées dans le pipeline."""
    return [
        cfg for cfg in LEAGUES.values()
        if cfg.tier == 1 or (include_tier2 and cfg.tier == 2)
    ]


def get_by_slug(slug: str) -> LeagueConfig | None:
    return LEAGUES.get(slug)


def get_by_bsd_id(bsd_id: int) -> LeagueConfig | None:
    for cfg in LEAGUES.values():
        if cfg.bsd_id == bsd_id:
            return cfg
    return None


def group_by_region(include_tier2: bool = False) -> dict[str, list[LeagueConfig]]:
    """Retourne un dict {region: [LeagueConfig...]} pour la sidebar Flashscore."""
    groups: dict[str, list[LeagueConfig]] = {}
    for cfg in get_active_leagues(include_tier2=include_tier2):
        groups.setdefault(cfg.region, []).append(cfg)
    # Tri par nom dans chaque région (Top 5 garde l'ordre EPL/LaLiga/Serie A/Bundesliga/L1)
    top5_order = {"premier_league": 0, "la_liga": 1, "serie_a": 2, "bundesliga": 3, "ligue_1": 4}
    uefa_order = {"champions_league": 0, "europa_league": 1, "conference_league": 2}
    for region, leagues in groups.items():
        if region == "top5":
            leagues.sort(key=lambda c: top5_order.get(c.slug, 99))
        elif region == "uefa":
            leagues.sort(key=lambda c: uefa_order.get(c.slug, 99))
        else:
            leagues.sort(key=lambda c: c.name)
    return groups


def league_labels_dict() -> dict[str, str]:
    """Renvoie {slug: 'flag name'} compatible avec ui.py LEAGUE_LABELS legacy."""
    return {cfg.slug: f"{cfg.flag} {cfg.name}" for cfg in LEAGUES.values()}
