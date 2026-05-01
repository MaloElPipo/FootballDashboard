"""
Liste maître des championnats et sélections nationales scrapés
pour le portail GitHub Pages auto-actualisé.

Structure :
    LEAGUES = liste de dicts { code_tm, slug, nom, pays, region, tier }
    NATIONAL_TEAMS = liste de dicts { code_tm, nom, pays, region }

Source : liste fournie par l'utilisateur (78 lignes brutes), nettoyée des doublons
et alignée sur les codes Transfermarkt officiels :
- 41 ligues européennes D1
- 6 ligues européennes D2 (GB2, IT2, ES2, FR2, L2, PT2)
- 5 ligues européennes D3 (GB3, IT3, ES3, FR3, L3)
- 9 ligues Amériques
- 5 ligues Asie / Océanie
- 3 ligues Afrique
Total : 69 ligues uniques.

Pour les sélections nationales du Mondial 2026 (48 équipes), on récupère
seulement les 4 dernières saisons (2022 → 2025). Le tirage final n'étant
pas encore arrêté, on prend les confirmées + qualifiées attendues.
"""

# ============================================================
# CHAMPIONNATS DE CLUBS
# ============================================================
LEAGUES: list[dict] = [
    # ----- Europe D1 (41) -----
    {"code_tm": "L1",   "slug": "1-bundesliga",                "nom": "Bundesliga",                      "pays": "Allemagne",        "region": "Europe", "tier": 1},
    {"code_tm": "ES1",  "slug": "laliga",                      "nom": "LaLiga",                          "pays": "Espagne",          "region": "Europe", "tier": 1},
    {"code_tm": "GB1",  "slug": "premier-league",              "nom": "Premier League",                  "pays": "Angleterre",       "region": "Europe", "tier": 1},
    {"code_tm": "IT1",  "slug": "serie-a",                     "nom": "Serie A",                         "pays": "Italie",           "region": "Europe", "tier": 1},
    {"code_tm": "FR1",  "slug": "ligue-1",                     "nom": "Ligue 1",                         "pays": "France",           "region": "Europe", "tier": 1},
    {"code_tm": "NL1",  "slug": "eredivisie",                  "nom": "Eredivisie",                      "pays": "Pays-Bas",         "region": "Europe", "tier": 1},
    {"code_tm": "PO1",  "slug": "liga-portugal",               "nom": "Liga Portugal",                   "pays": "Portugal",         "region": "Europe", "tier": 1},
    {"code_tm": "BE1",  "slug": "jupiler-pro-league",          "nom": "Jupiler Pro League",              "pays": "Belgique",         "region": "Europe", "tier": 1},
    {"code_tm": "TR1",  "slug": "super-lig",                   "nom": "Süper Lig",                       "pays": "Turquie",          "region": "Europe", "tier": 1},
    {"code_tm": "GR1",  "slug": "super-league-1",              "nom": "Super League 1",                  "pays": "Grèce",            "region": "Europe", "tier": 1},
    {"code_tm": "SC1",  "slug": "scottish-premiership",        "nom": "Scottish Premiership",            "pays": "Écosse",           "region": "Europe", "tier": 1},
    {"code_tm": "RU1",  "slug": "premier-liga",                "nom": "Premier Liga",                    "pays": "Russie",           "region": "Europe", "tier": 1},
    {"code_tm": "UKR1", "slug": "premier-liga",                "nom": "Premier Liga",                    "pays": "Ukraine",          "region": "Europe", "tier": 1},
    {"code_tm": "DK1",  "slug": "superligaen",                 "nom": "Superligaen",                     "pays": "Danemark",         "region": "Europe", "tier": 1},
    {"code_tm": "A1",   "slug": "bundesliga",                  "nom": "Bundesliga",                      "pays": "Autriche",         "region": "Europe", "tier": 1},
    {"code_tm": "C1",   "slug": "super-league",                "nom": "Super League",                    "pays": "Suisse",           "region": "Europe", "tier": 1},
    {"code_tm": "PL1",  "slug": "ekstraklasa",                 "nom": "Ekstraklasa",                     "pays": "Pologne",          "region": "Europe", "tier": 1},
    {"code_tm": "SE1",  "slug": "allsvenskan",                 "nom": "Allsvenskan",                     "pays": "Suède",            "region": "Europe", "tier": 1},
    {"code_tm": "NO1",  "slug": "eliteserien",                 "nom": "Eliteserien",                     "pays": "Norvège",          "region": "Europe", "tier": 1},
    {"code_tm": "TS1",  "slug": "chance-liga",                 "nom": "Chance Liga",                     "pays": "Tchéquie",         "region": "Europe", "tier": 1},
    {"code_tm": "KR1",  "slug": "supersport-hnl",              "nom": "SuperSport HNL",                  "pays": "Croatie",          "region": "Europe", "tier": 1},
    {"code_tm": "SER1", "slug": "super-liga",                  "nom": "Super Liga",                      "pays": "Serbie",           "region": "Europe", "tier": 1},
    {"code_tm": "RO1",  "slug": "superliga",                   "nom": "Superliga",                       "pays": "Roumanie",         "region": "Europe", "tier": 1},
    {"code_tm": "HU1",  "slug": "nemzeti-bajnoksag",           "nom": "Nemzeti Bajnokság I",             "pays": "Hongrie",          "region": "Europe", "tier": 1},
    {"code_tm": "IS1",  "slug": "besta-deild-karla",           "nom": "Besta deild karla",               "pays": "Islande",          "region": "Europe", "tier": 1},
    {"code_tm": "IR1",  "slug": "premier-division",            "nom": "Premier Division",                "pays": "Irlande",          "region": "Europe", "tier": 1},
    {"code_tm": "BG1",  "slug": "first-league",                "nom": "First League",                    "pays": "Bulgarie",         "region": "Europe", "tier": 1},
    {"code_tm": "CY1",  "slug": "first-division",              "nom": "First Division",                  "pays": "Chypre",           "region": "Europe", "tier": 1},
    {"code_tm": "LT1",  "slug": "a-lyga",                      "nom": "A Lyga",                          "pays": "Lituanie",         "region": "Europe", "tier": 1},
    {"code_tm": "LV1",  "slug": "virsliga",                    "nom": "Virsliga",                        "pays": "Lettonie",         "region": "Europe", "tier": 1},
    {"code_tm": "EST1", "slug": "meistriliiga",                "nom": "Meistriliiga",                    "pays": "Estonie",          "region": "Europe", "tier": 1},
    {"code_tm": "AL1",  "slug": "kategoria-superiore",         "nom": "Kategoria Superiore",             "pays": "Albanie",          "region": "Europe", "tier": 1},
    {"code_tm": "AZ1",  "slug": "premier-league",              "nom": "Premier League",                  "pays": "Azerbaïdjan",      "region": "Europe", "tier": 1},
    {"code_tm": "BH1",  "slug": "premijer-liga",               "nom": "Premier League",                  "pays": "Bosnie-Herzégovine","region": "Europe", "tier": 1},
    {"code_tm": "MAL1", "slug": "premier-league",              "nom": "Premier League",                  "pays": "Malte",            "region": "Europe", "tier": 1},
    {"code_tm": "FN1",  "slug": "veikkausliiga",               "nom": "Veikkausliiga",                   "pays": "Finlande",         "region": "Europe", "tier": 1},
    {"code_tm": "GE1",  "slug": "erovnuli-liga",               "nom": "Erovnuli Liga",                   "pays": "Géorgie",          "region": "Europe", "tier": 1},
    {"code_tm": "NI1",  "slug": "premiership",                 "nom": "Premiership",                     "pays": "Irlande du Nord",  "region": "Europe", "tier": 1},
    {"code_tm": "ISR1", "slug": "ligat-haal",                  "nom": "Ligat Ha'AL",                     "pays": "Israël",           "region": "Europe", "tier": 1},
    {"code_tm": "LUX1", "slug": "national-division",           "nom": "National Division",               "pays": "Luxembourg",       "region": "Europe", "tier": 1},
    {"code_tm": "WAL1", "slug": "cymru-premier",               "nom": "Cymru Premier",                   "pays": "Pays de Galles",   "region": "Europe", "tier": 1},
    {"code_tm": "SK1",  "slug": "fortuna-liga",                "nom": "Fortuna Liga",                    "pays": "Slovaquie",        "region": "Europe", "tier": 1},
    {"code_tm": "SLO1", "slug": "prvaliga",                    "nom": "PrvaLiga",                        "pays": "Slovénie",         "region": "Europe", "tier": 1},

    # ----- Europe D2 (6) -----
    {"code_tm": "GB2",  "slug": "championship",                "nom": "EFL Championship",                "pays": "Angleterre",       "region": "Europe", "tier": 2},
    {"code_tm": "IT2",  "slug": "serie-b",                     "nom": "Serie B",                         "pays": "Italie",           "region": "Europe", "tier": 2},
    {"code_tm": "ES2",  "slug": "laliga2",                     "nom": "Segunda División",                "pays": "Espagne",          "region": "Europe", "tier": 2},
    {"code_tm": "FR2",  "slug": "ligue-2",                     "nom": "Ligue 2",                         "pays": "France",           "region": "Europe", "tier": 2},
    {"code_tm": "L2",   "slug": "2-bundesliga",                "nom": "2. Bundesliga",                   "pays": "Allemagne",        "region": "Europe", "tier": 2},
    {"code_tm": "PT2",  "slug": "liga-portugal-2",             "nom": "Liga Portugal 2",                 "pays": "Portugal",         "region": "Europe", "tier": 2},

    # ----- Europe D3 (5) -----
    {"code_tm": "GB3",  "slug": "league-one",                  "nom": "EFL League One",                  "pays": "Angleterre",       "region": "Europe", "tier": 3},
    {"code_tm": "IT3",  "slug": "serie-c",                     "nom": "Serie C",                         "pays": "Italie",           "region": "Europe", "tier": 3},
    {"code_tm": "ES3",  "slug": "primera-federacion",          "nom": "Primera Federación",              "pays": "Espagne",          "region": "Europe", "tier": 3},
    {"code_tm": "FR3",  "slug": "national",                    "nom": "Championnat National",            "pays": "France",           "region": "Europe", "tier": 3},
    {"code_tm": "L3",   "slug": "3-liga",                      "nom": "3. Liga",                         "pays": "Allemagne",        "region": "Europe", "tier": 3},

    # ----- Amériques (9) -----
    {"code_tm": "BRA1", "slug": "campeonato-brasileiro-serie-a","nom": "Brasileirão Série A",             "pays": "Brésil",           "region": "Amériques", "tier": 1},
    {"code_tm": "ARG1", "slug": "liga-profesional-de-futbol",  "nom": "Primera División",                "pays": "Argentine",        "region": "Amériques", "tier": 1},
    {"code_tm": "MLS1", "slug": "major-league-soccer",         "nom": "MLS",                             "pays": "États-Unis",       "region": "Amériques", "tier": 1},
    {"code_tm": "MEX1", "slug": "liga-mx-clausura",            "nom": "Liga MX",                         "pays": "Mexique",          "region": "Amériques", "tier": 1},
    {"code_tm": "COL1", "slug": "liga-betplay-dimayor",        "nom": "Liga BetPlay",                    "pays": "Colombie",         "region": "Amériques", "tier": 1},
    {"code_tm": "PR1A", "slug": "primera-division-apertura",   "nom": "Primera División Apertura",       "pays": "Paraguay",         "region": "Amériques", "tier": 1},
    {"code_tm": "CLPD", "slug": "primera-division-de-chile",   "nom": "Primera División",                "pays": "Chili",            "region": "Amériques", "tier": 1},
    {"code_tm": "EC1N", "slug": "ligapro-serie-a",             "nom": "LigaPro Serie A",                 "pays": "Équateur",         "region": "Amériques", "tier": 1},
    {"code_tm": "BRA2", "slug": "campeonato-brasileiro-serie-b","nom": "Brasileirão Série B",             "pays": "Brésil",           "region": "Amériques", "tier": 2},

    # ----- Asie / Océanie (5) -----
    {"code_tm": "SA1",  "slug": "saudi-pro-league",            "nom": "Saudi Pro League",                "pays": "Arabie Saoudite",  "region": "Asie/Océanie", "tier": 1},
    {"code_tm": "JAP1", "slug": "j1-league",                   "nom": "J1 League",                       "pays": "Japon",            "region": "Asie/Océanie", "tier": 1},
    {"code_tm": "RSK1", "slug": "k-league-1",                  "nom": "K League 1",                      "pays": "Corée du Sud",     "region": "Asie/Océanie", "tier": 1},
    {"code_tm": "AUS1", "slug": "a-league",                    "nom": "A-League",                        "pays": "Australie",        "region": "Asie/Océanie", "tier": 1},
    {"code_tm": "CSL",  "slug": "chinese-super-league",        "nom": "Chinese Super League",            "pays": "Chine",            "region": "Asie/Océanie", "tier": 1},

    # ----- Afrique (3) -----
    {"code_tm": "MAR1", "slug": "botola-pro",                  "nom": "Botola Pro",                      "pays": "Maroc",            "region": "Afrique", "tier": 1},
    {"code_tm": "ALG1", "slug": "ligue-professionnelle-1",     "nom": "Ligue Professionnelle 1",         "pays": "Algérie",          "region": "Afrique", "tier": 1},
    {"code_tm": "SFA1", "slug": "betway-premiership",          "nom": "Premier Division",                "pays": "Afrique du Sud",   "region": "Afrique", "tier": 1},
]

# ============================================================
# SÉLECTIONS NATIONALES — Coupe du Monde 2026 (48 équipes)
# ============================================================
# Codes équipe TM (team_id) — à vérifier manuellement avant scraping.
# Pour le MVP du portail, on déclare la liste; le scraping sera implémenté
# dans une étape ultérieure (besoin d'un endpoint dédié sélections).
NATIONAL_TEAMS: list[dict] = [
    # Hôtes (3)
    {"code_tm": "USA",  "nom": "États-Unis",       "region": "CONCACAF",   "qualif": "hôte"},
    {"code_tm": "CAN",  "nom": "Canada",           "region": "CONCACAF",   "qualif": "hôte"},
    {"code_tm": "MEX",  "nom": "Mexique",          "region": "CONCACAF",   "qualif": "hôte"},
    # UEFA — qualifiés probables (16 places)
    {"code_tm": "FRA",  "nom": "France",           "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "ESP",  "nom": "Espagne",          "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "ENG",  "nom": "Angleterre",       "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "GER",  "nom": "Allemagne",        "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "ITA",  "nom": "Italie",           "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "POR",  "nom": "Portugal",         "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "NED",  "nom": "Pays-Bas",         "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "BEL",  "nom": "Belgique",         "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "CRO",  "nom": "Croatie",          "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "DEN",  "nom": "Danemark",         "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "SUI",  "nom": "Suisse",           "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "AUT",  "nom": "Autriche",         "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "POL",  "nom": "Pologne",          "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "TUR",  "nom": "Turquie",          "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "SRB",  "nom": "Serbie",           "region": "UEFA",       "qualif": "qualifié"},
    {"code_tm": "NOR",  "nom": "Norvège",          "region": "UEFA",       "qualif": "qualifié"},
    # CONMEBOL (6 places)
    {"code_tm": "ARG",  "nom": "Argentine",        "region": "CONMEBOL",   "qualif": "qualifié"},
    {"code_tm": "BRA",  "nom": "Brésil",           "region": "CONMEBOL",   "qualif": "qualifié"},
    {"code_tm": "URU",  "nom": "Uruguay",          "region": "CONMEBOL",   "qualif": "qualifié"},
    {"code_tm": "COL",  "nom": "Colombie",         "region": "CONMEBOL",   "qualif": "qualifié"},
    {"code_tm": "ECU",  "nom": "Équateur",         "region": "CONMEBOL",   "qualif": "qualifié"},
    {"code_tm": "PAR",  "nom": "Paraguay",         "region": "CONMEBOL",   "qualif": "qualifié"},
    # CONCACAF supplémentaires (3 places hors hôtes)
    {"code_tm": "PAN",  "nom": "Panama",           "region": "CONCACAF",   "qualif": "à confirmer"},
    {"code_tm": "CRC",  "nom": "Costa Rica",       "region": "CONCACAF",   "qualif": "à confirmer"},
    {"code_tm": "JAM",  "nom": "Jamaïque",         "region": "CONCACAF",   "qualif": "à confirmer"},
    # CAF (9 places)
    {"code_tm": "MAR",  "nom": "Maroc",            "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "ALG",  "nom": "Algérie",          "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "TUN",  "nom": "Tunisie",          "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "EGY",  "nom": "Égypte",           "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "SEN",  "nom": "Sénégal",          "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "CIV",  "nom": "Côte d'Ivoire",    "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "NGA",  "nom": "Nigeria",          "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "GHA",  "nom": "Ghana",            "region": "CAF",        "qualif": "qualifié"},
    {"code_tm": "RSA",  "nom": "Afrique du Sud",   "region": "CAF",        "qualif": "qualifié"},
    # AFC (8 places)
    {"code_tm": "JPN",  "nom": "Japon",            "region": "AFC",        "qualif": "qualifié"},
    {"code_tm": "KOR",  "nom": "Corée du Sud",     "region": "AFC",        "qualif": "qualifié"},
    {"code_tm": "AUS",  "nom": "Australie",        "region": "AFC",        "qualif": "qualifié"},
    {"code_tm": "IRN",  "nom": "Iran",             "region": "AFC",        "qualif": "qualifié"},
    {"code_tm": "KSA",  "nom": "Arabie Saoudite",  "region": "AFC",        "qualif": "qualifié"},
    {"code_tm": "QAT",  "nom": "Qatar",            "region": "AFC",        "qualif": "à confirmer"},
    {"code_tm": "UZB",  "nom": "Ouzbékistan",      "region": "AFC",        "qualif": "à confirmer"},
    {"code_tm": "JOR",  "nom": "Jordanie",         "region": "AFC",        "qualif": "à confirmer"},
    # OFC (1 place)
    {"code_tm": "NZL",  "nom": "Nouvelle-Zélande", "region": "OFC",        "qualif": "à confirmer"},
    # Barrages intercontinentaux (à confirmer)
    {"code_tm": "BOL",  "nom": "Bolivie",          "region": "CONMEBOL",   "qualif": "barrage"},
    {"code_tm": "IRQ",  "nom": "Irak",             "region": "AFC",        "qualif": "barrage"},
]

# Sanity checks — utiles si on importe ce module en console.
assert len(LEAGUES) == 71, f"Attendu 71 ligues, trouvé {len(LEAGUES)}"
assert len(NATIONAL_TEAMS) == 48, f"Attendu 48 sélections, trouvé {len(NATIONAL_TEAMS)}"
assert len({l["code_tm"] for l in LEAGUES}) == 71, "Doublon de code_tm dans LEAGUES"
assert len({t["code_tm"] for t in NATIONAL_TEAMS}) == 48, "Doublon de code_tm dans NATIONAL_TEAMS"


def get_all_targets() -> list[dict]:
    """Retourne la liste unifiée ligues + sélections, avec champ 'kind'."""
    out = []
    for l in LEAGUES:
        out.append({**l, "kind": "league"})
    for t in NATIONAL_TEAMS:
        out.append({**t, "kind": "national_team", "tier": 0, "slug": t["code_tm"].lower(),
                    "pays": t["nom"]})
    return out


if __name__ == "__main__":
    print(f"Ligues:     {len(LEAGUES)}")
    print(f"Sélections: {len(NATIONAL_TEAMS)}")
    print(f"Total:      {len(get_all_targets())} datasets")
    by_region: dict[str, int] = {}
    for l in LEAGUES:
        by_region[l["region"]] = by_region.get(l["region"], 0) + 1
    print("Par région (ligues) :", by_region)
