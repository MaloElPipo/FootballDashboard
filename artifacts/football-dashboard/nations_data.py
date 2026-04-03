"""
Configuration des 48 nations qualifiées pour la Coupe du Monde 2026.
TM IDs vérifiés via transfermarkt.fr spielplandatum pages.
Nations avec tm_id=None : ID Transfermarkt non encore trouvé.
"""

WC2026_NATIONS = {
    "UEFA": [
        {"code": "FRA", "name": "France",             "fr": "France",              "tm_id": 3377, "slug": "frankreich"},
        {"code": "ESP", "name": "Spain",               "fr": "Espagne",             "tm_id": 3375, "slug": "spanien"},
        {"code": "GER", "name": "Germany",             "fr": "Allemagne",           "tm_id": 3262, "slug": "deutschland"},
        {"code": "ENG", "name": "England",             "fr": "Angleterre",          "tm_id": 3299, "slug": "england"},
        {"code": "POR", "name": "Portugal",            "fr": "Portugal",            "tm_id": 3300, "slug": "portugal"},
        {"code": "NED", "name": "Netherlands",         "fr": "Pays-Bas",            "tm_id": 3379, "slug": "niederlande"},
        {"code": "BEL", "name": "Belgium",             "fr": "Belgique",            "tm_id": 3382, "slug": "belgien"},
        {"code": "CRO", "name": "Croatia",             "fr": "Croatie",             "tm_id": 3556, "slug": "kroatien"},
        {"code": "AUT", "name": "Austria",             "fr": "Autriche",            "tm_id": 3383, "slug": "oesterreich"},
        {"code": "SUI", "name": "Switzerland",         "fr": "Suisse",              "tm_id": 3384, "slug": "schweiz"},
        {"code": "NOR", "name": "Norway",              "fr": "Norvège",             "tm_id": 3440, "slug": "norwegen"},
        {"code": "SWE", "name": "Sweden",              "fr": "Suède",               "tm_id": 3557, "slug": "schweden"},
        {"code": "CZE", "name": "Czech Republic",      "fr": "Rép. Tchèque",        "tm_id": 3445, "slug": "tschechien"},
        {"code": "TUR", "name": "Turkey",              "fr": "Turquie",             "tm_id": 3381, "slug": "turkei"},
        {"code": "SCO", "name": "Scotland",            "fr": "Écosse",              "tm_id": 3380, "slug": "schottland"},
        {"code": "BIH", "name": "Bosnia-Herzegovina",  "fr": "Bosnie-Herzégovine",  "tm_id": 3446, "slug": "bosnien-herzegowina"},
    ],
    "CONMEBOL": [
        {"code": "ARG", "name": "Argentina",           "fr": "Argentine",           "tm_id": 3437, "slug": "argentinien"},
        {"code": "BRA", "name": "Brazil",              "fr": "Brésil",              "tm_id": 3439, "slug": "brasilien"},
        {"code": "COL", "name": "Colombia",            "fr": "Colombie",            "tm_id": 3816, "slug": "kolumbien"},
        {"code": "URU", "name": "Uruguay",             "fr": "Uruguay",             "tm_id": 3449, "slug": "uruguay"},
        {"code": "ECU", "name": "Ecuador",             "fr": "Équateur",            "tm_id": 5750, "slug": "ecuador"},
        {"code": "PAR", "name": "Paraguay",            "fr": "Paraguay",            "tm_id": 3581, "slug": "paraguay"},
    ],
    "CONCACAF": [
        {"code": "USA", "name": "United States",       "fr": "États-Unis",          "tm_id": 3505, "slug": "vereinigte-staaten"},
        {"code": "MEX", "name": "Mexico",              "fr": "Mexique",             "tm_id": 6303, "slug": "mexiko"},
        {"code": "CAN", "name": "Canada",              "fr": "Canada",              "tm_id": 3510, "slug": "kanada"},
        {"code": "PAN", "name": "Panama",              "fr": "Panama",              "tm_id": 3577, "slug": "panama"},
        {"code": "CUW", "name": "Curacao",             "fr": "Curaçao",             "tm_id": 32364,"slug": "curacao"},
        {"code": "HAI", "name": "Haiti",               "fr": "Haïti",               "tm_id": 14161,"slug": "haiti"},
    ],
    "AFC": [
        {"code": "JPN", "name": "Japan",               "fr": "Japon",               "tm_id": 3435, "slug": "japan"},
        {"code": "KOR", "name": "South Korea",         "fr": "Corée du Sud",        "tm_id": 3589, "slug": "sudkorea"},
        {"code": "IRN", "name": "Iran",                "fr": "Iran",                "tm_id": 3582, "slug": "iran"},
        {"code": "KSA", "name": "Saudi Arabia",        "fr": "Arabie Saoudite",     "tm_id": 3807, "slug": "saudi-arabien"},
        {"code": "AUS", "name": "Australia",           "fr": "Australie",           "tm_id": 3433, "slug": "australien"},
        {"code": "QAT", "name": "Qatar",               "fr": "Qatar",               "tm_id": 14162,"slug": "katar"},
        {"code": "IRQ", "name": "Iraq",                "fr": "Irak",                "tm_id": 3560,  "slug": "irak"},
        {"code": "JOR", "name": "Jordan",              "fr": "Jordanie",            "tm_id": 15737,"slug": "jordanien"},
        {"code": "UZB", "name": "Uzbekistan",          "fr": "Ouzbékistan",         "tm_id": 3563, "slug": "usbekistan"},
    ],
    "CAF": [
        {"code": "MAR", "name": "Morocco",             "fr": "Maroc",               "tm_id": 3575, "slug": "marokko"},
        {"code": "SEN", "name": "Senegal",             "fr": "Sénégal",             "tm_id": 3499, "slug": "senegal"},
        {"code": "EGY", "name": "Egypt",               "fr": "Égypte",              "tm_id": 3672, "slug": "agypten"},
        {"code": "ALG", "name": "Algeria",             "fr": "Algérie",             "tm_id": 3614, "slug": "algerien"},
        {"code": "TUN", "name": "Tunisia",             "fr": "Tunisie",             "tm_id": 3670, "slug": "tunesien"},
        {"code": "CIV", "name": "Ivory Coast",         "fr": "Côte d'Ivoire",       "tm_id": 3591, "slug": "elfenbeinkuste"},
        {"code": "GHA", "name": "Ghana",               "fr": "Ghana",               "tm_id": 3441,  "slug": "ghana"},
        {"code": "COD", "name": "DR Congo",            "fr": "RD Congo",            "tm_id": 3854, "slug": "demokratische-republik-kongo"},
        {"code": "RSA", "name": "South Africa",        "fr": "Afrique du Sud",      "tm_id": 3806, "slug": "sudafrika"},
        {"code": "CPV", "name": "Cape Verde",          "fr": "Cap-Vert",            "tm_id": 4311, "slug": "kap-verde"},
    ],
    "OFC": [
        {"code": "NZL", "name": "New Zealand",         "fr": "Nouvelle-Zélande",    "tm_id": 9171, "slug": "neuseeland"},
    ],
}

CONF_LABELS = {
    "UEFA":     "🇪🇺 UEFA",
    "CONMEBOL": "🌎 CONMEBOL",
    "CONCACAF": "🌍 CONCACAF",
    "AFC":      "🌏 AFC",
    "CAF":      "🌍 CAF",
    "OFC":      "🌊 OFC",
}

CONF_COUNTS = {
    "UEFA": 16, "CONMEBOL": 6, "CONCACAF": 6,
    "AFC": 9,   "CAF": 10,    "OFC": 1,
}


def get_all_nations():
    """Return flat list of all 48 nations with conf key."""
    result = []
    for conf, nations in WC2026_NATIONS.items():
        for n in nations:
            result.append({**n, "conf": conf})
    return result


FIFA_TO_ISO = {
    "FRA": "fr", "ESP": "es", "GER": "de", "ENG": "gb-eng", "POR": "pt",
    "NED": "nl", "BEL": "be", "CRO": "hr", "AUT": "at", "SUI": "ch",
    "NOR": "no", "SWE": "se", "CZE": "cz", "TUR": "tr", "SCO": "gb-sct",
    "BIH": "ba", "ARG": "ar", "BRA": "br", "COL": "co", "URU": "uy",
    "ECU": "ec", "PAR": "py", "USA": "us", "MEX": "mx", "CAN": "ca",
    "PAN": "pa", "CUW": "cw", "HAI": "ht", "JPN": "jp", "KOR": "kr",
    "IRN": "ir", "KSA": "sa", "AUS": "au", "QAT": "qa", "IRQ": "iq",
    "JOR": "jo", "UZB": "uz", "MAR": "ma", "SEN": "sn", "EGY": "eg",
    "ALG": "dz", "TUN": "tn", "CIV": "ci", "GHA": "gh", "COD": "cd",
    "RSA": "za", "CPV": "cv", "NZL": "nz",
}


def flag_url(fifa_code, size="24x18"):
    iso = FIFA_TO_ISO.get(fifa_code, fifa_code.lower())
    return f"https://flagcdn.com/{size}/{iso}.png"


def flag_img(fifa_code, size="24x18"):
    url = flag_url(fifa_code, size)
    return f"<img src='{url}' style='vertical-align:middle'>"


def get_nation_by_code(code):
    for conf, nations in WC2026_NATIONS.items():
        for n in nations:
            if n["code"] == code:
                return {**n, "conf": conf}
    return None
