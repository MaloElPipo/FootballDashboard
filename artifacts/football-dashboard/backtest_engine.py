import json
import math
import numpy as np
from pathlib import Path

HIST_ODDS_PATH = Path(__file__).parent / "historical_odds.json"
SCRAPED_ODDS_PATH = Path(__file__).parent / "scraped_odds.json"
IMPLIED_ELO_PATH = Path(__file__).parent / "implied_elo.json"

TEAM_NAME_TO_ELO_KEY = {
    "Afghanistan": "AFG", "Albania": "ALB", "Algeria": "ALG",
    "Andorra": "AND", "Angola": "ANG", "Anguilla": "AIA",
    "Antigua and Barbuda": "ATG", "Argentina": "ARG", "Armenia": "ARM",
    "Aruba": "ARU", "Australia": "AUS", "Austria": "AUT",
    "Azerbaijan": "AZE", "Bahamas": "BAH", "Bahrain": "BHR",
    "Bangladesh": "BAN", "Barbados": "BRB", "Belarus": "BLR",
    "Belgium": "BEL", "Belize": "BLZ", "Benin": "BEN",
    "Bermuda": "BER", "Bhutan": "BHU", "Bolivia": "BOL",
    "Bosnia & Herzegovina": "BIH", "Botswana": "BOT", "Brazil": "BRA",
    "British Virgin Islands": "VGB", "Brunei": "BRU", "Bulgaria": "BUL",
    "Burkina Faso": "BFA", "Burundi": "BDI", "Cambodia": "CAM",
    "Cameroon": "CMR", "Canada": "CAN", "Cape Verde": "CPV",
    "Cayman Islands": "CAY", "Central Africa": "CTA",
    "Chad": "CHA", "Chile": "CHI", "China": "CHN",
    "Chinese Taipei": "TPE", "Colombia": "COL", "Comoros": "COM",
    "Congo": "CGO", "Costa Rica": "CRC", "Croatia": "CRO",
    "Cuba": "CUB", "Curacao": "CUW", "Cyprus": "CYP",
    "Czech Republic": "CZE", "D.R. Congo": "COD",
    "Denmark": "DEN", "Djibouti": "DJI", "Dominican Republic": "DOM",
    "Ecuador": "ECU", "Egypt": "EGY", "El Salvador": "SLV",
    "England": "ENG", "Equatorial Guinea": "EQG", "Eritrea": "ERI",
    "Estonia": "EST", "Eswatini": "SWZ", "Ethiopia": "ETH",
    "Faroe Islands": "FRO", "Finland": "FIN", "France": "FRA",
    "Gabon": "GAB", "Gambia": "GAM", "Georgia": "GEO",
    "Germany": "GER", "Ghana": "GHA", "Gibraltar": "GIB",
    "Greece": "GRE", "Grenada": "GRN", "Guadeloupe": "GLP",
    "Guatemala": "GUA", "Guinea": "GUI", "Guinea Bissau": "GNB",
    "Guyana": "GUY", "Haiti": "HAI", "Honduras": "HON",
    "Hong Kong": "HKG", "Hungary": "HUN", "Iceland": "ISL",
    "India": "IND", "Indonesia": "IDN", "Iran": "IRN",
    "Iraq": "IRQ", "Ireland": "IRL", "Israel": "ISR",
    "Italy": "ITA", "Ivory Coast": "CIV", "Jamaica": "JAM",
    "Japan": "JPN", "Jordan": "JOR", "Kazakhstan": "KAZ",
    "Kenya": "KEN", "Kosovo": "KVX", "Kuwait": "KUW",
    "Kyrgyzstan": "KGZ", "Latvia": "LVA", "Lebanon": "LBN",
    "Lesotho": "LES", "Liberia": "LBR", "Libya": "LBY",
    "Liechtenstein": "LIE", "Lithuania": "LTU", "Luxembourg": "LUX",
    "Macau": "MAC", "Madagascar": "MAD", "Malawi": "MWI",
    "Malaysia": "MAS", "Maldives": "MDV", "Mali": "MLI",
    "Malta": "MLT", "Martinique": "MTQ", "Mauritania": "MTN",
    "Mauritius": "MRI", "Mexico": "MEX", "Moldova": "MDA",
    "Mongolia": "MNG", "Montenegro": "MNE", "Montserrat": "MSR",
    "Morocco": "MAR", "Mozambique": "MOZ", "Myanmar": "MYA",
    "Namibia": "NAM", "Nepal": "NEP", "Netherlands": "NED",
    "New Caledonia": "NCL", "Nicaragua": "NCA", "Niger": "NIG",
    "Nigeria": "NGA", "North Korea": "PRK", "North Macedonia": "MKD",
    "Northern Ireland": "NIR", "Norway": "NOR", "Oman": "OMA",
    "Pakistan": "PAK", "Palestine": "PLE", "Panama": "PAN",
    "Paraguay": "PAR", "Peru": "PER", "Philippines": "PHI",
    "Poland": "POL", "Portugal": "POR", "Puerto Rico": "PUR",
    "Qatar": "QAT", "Romania": "ROU", "Russia": "RUS",
    "Rwanda": "RWA", "Saint Kitts and Nevis": "SKN",
    "Saint Lucia": "LCA", "Saint Vincent and the Grenadines": "VIN",
    "San Marino": "SMR", "Sao Tome and Principe": "STP",
    "Saudi Arabia": "KSA", "Scotland": "SCO", "Senegal": "SEN",
    "Serbia": "SRB", "Seychelles": "SEY", "Sierra Leone": "SLE",
    "Singapore": "SIN", "Slovakia": "SVK", "Slovenia": "SVN",
    "Somalia": "SOM", "South Africa": "RSA", "South Korea": "KOR",
    "Korea Republic": "KOR", "South Sudan": "SSD", "Spain": "ESP",
    "Sri Lanka": "SRI", "Sudan": "SDN", "Suriname": "SUR",
    "Sweden": "SWE", "Switzerland": "SUI", "Syria": "SYR",
    "Tanzania": "TAN", "Togo": "TOG",
    "Trinidad & Tobago": "TRI", "Tunisia": "TUN", "Turkey": "TUR",
    "USA": "USA", "United States": "USA",
    "Uganda": "UGA", "Ukraine": "UKR", "United Arab Emirates": "UAE",
    "Uruguay": "URU", "Uzbekistan": "UZB", "Venezuela": "VEN",
    "Vietnam": "VIE", "Wales": "WAL", "Yemen": "YEM",
    "Zambia": "ZAM", "Zimbabwe": "ZIM", "Timor-Leste": "TLS",
}

DEFAULT_ELO = {
    "ESP": 2090, "ARG": 2140, "FRA": 2090, "ENG": 2050, "BRA": 2130,
    "POR": 2040, "COL": 1870, "NED": 2055, "ECU": 1830, "CRO": 1940,
    "GER": 2040, "NOR": 1840, "JPN": 1843, "TUR": 1800, "URU": 1900,
    "SUI": 1915, "SEN": 1811, "BEL": 1920, "MEX": 1810, "PAR": 1730,
    "AUT": 1880, "MAR": 1845, "CAN": 1750, "AUS": 1735, "IRN": 1768,
    "KOR": 1815, "ALG": 1730, "PAN": 1640, "UZB": 1690, "CZE": 1825,
    "SWE": 1830, "JOR": 1580, "EGY": 1700, "COD": 1630, "TUN": 1699,
    "IRQ": 1640, "BIH": 1760, "NZL": 1530, "KSA": 1585, "CPV": 1530,
    "HAI": 1510, "RSA": 1610, "GHA": 1600, "QAT": 1554, "SCO": 1795,
    "CUW": 1350, "CIV": 1750, "USA": 1800, "ITA": 1945, "DEN": 1960,
    "SRB": 1845, "POL": 1830, "HUN": 1855, "SVK": 1770, "ROU": 1785,
    "UKR": 1840, "GEO": 1680, "ALB": 1700, "SVN": 1775, "WAL": 1790,
    "CRC": 1640, "BOL": 1520, "PER": 1740, "CHI": 1810, "VEN": 1750,
    "JAM": 1530, "CMR": 1595,
    "NIR": 1640, "ISL": 1700, "FIN": 1700, "BUL": 1620, "GRE": 1700,
    "ISR": 1680, "IRL": 1720, "MNE": 1660, "ARM": 1560, "KAZ": 1520,
    "LVA": 1490, "LTU": 1490, "LUX": 1490, "EST": 1460, "FRO": 1380,
    "GIB": 1200, "AND": 1270, "SMR": 1100, "LIE": 1350, "MLT": 1370,
    "MDA": 1440, "BLR": 1530, "CYP": 1480, "MKD": 1600, "KVX": 1640,
    "NGA": 1740, "BFA": 1560, "MLI": 1620, "GAB": 1470, "BEN": 1500,
    "GUI": 1480, "MAD": 1400, "MOZ": 1360, "SLE": 1400, "TOG": 1420,
    "TAN": 1400, "UGA": 1400, "NAM": 1350, "ZAM": 1500, "ZIM": 1430,
    "ANG": 1470, "GAM": 1470, "MTN": 1430, "RWA": 1380, "NIG": 1370,
    "EQG": 1410, "LBR": 1380, "COM": 1370, "LBY": 1430, "SDN": 1370,
    "GNB": 1370, "ETH": 1350, "ERI": 1250, "SOM": 1200, "DJI": 1150,
    "SWZ": 1300, "LES": 1280, "BOT": 1370, "CTA": 1300, "CHA": 1250,
    "STP": 1150, "SEY": 1200, "MWI": 1350, "MRI": 1250, "SSD": 1200,
    "HON": 1550, "SLV": 1530, "GUA": 1540, "NCA": 1420, "TRI": 1430,
    "SUR": 1400, "BLZ": 1300, "DOM": 1380, "CUB": 1420, "GUY": 1300,
    "BRB": 1280, "ATG": 1260, "GRN": 1270, "SKN": 1240, "LCA": 1220,
    "VIN": 1230, "AIA": 1100, "MSR": 1100, "VGB": 1100, "BER": 1300,
    "CAY": 1200, "PUR": 1300, "ARU": 1250,
    "CHN": 1560, "IND": 1420, "IDN": 1450, "PHI": 1400, "VIE": 1440,
    "MAS": 1380, "SIN": 1370, "MYA": 1370, "CAM": 1320, "BAN": 1300,
    "NEP": 1290, "MDV": 1260, "SRI": 1250, "PAK": 1250, "MNG": 1250,
    "BHU": 1200, "BRU": 1180, "TLS": 1200, "MAC": 1200, "TPE": 1300,
    "HKG": 1350, "OMA": 1520, "BHR": 1480, "KUW": 1460, "UAE": 1560,
    "LBN": 1430, "SYR": 1470, "PLE": 1420, "YEM": 1280,
    "PRK": 1560, "KGZ": 1440,
    "NCL": 1350, "GLP": 1350, "MTQ": 1350, "BAH": 1250, "AFG": 1300,
    "RUS": 1800, "NOR": 1840,
}

ELO_WC2022 = {
    "QAT": 1554, "ECU": 1833, "ENG": 2035, "IRN": 1768, "SEN": 1811,
    "NED": 2062, "USA": 1799, "WAL": 1790, "ARG": 2143, "KSA": 1585,
    "DEN": 1971, "TUN": 1699, "MEX": 1809, "POL": 1844, "FRA": 2089,
    "AUS": 1735, "MAR": 1753, "CRO": 1945, "GER": 1950, "JPN": 1843,
    "ESP": 2048, "CRC": 1640, "BEL": 1955, "CAN": 1729, "SUI": 1926,
    "CMR": 1595, "URU": 1890, "KOR": 1815, "POR": 2006, "GHA": 1567,
    "BRA": 2169, "SRB": 1849,
}

NTC_WC22 = {
    "Qatar": "QAT", "Ecuador": "ECU", "England": "ENG", "Iran": "IRN",
    "Senegal": "SEN", "Netherlands": "NED", "USA": "USA", "Wales": "WAL",
    "Argentina": "ARG", "Saudi Arabia": "KSA", "Denmark": "DEN", "Tunisia": "TUN",
    "Mexico": "MEX", "Poland": "POL", "France": "FRA", "Australia": "AUS",
    "Morocco": "MAR", "Croatia": "CRO", "Germany": "GER", "Japan": "JPN",
    "Spain": "ESP", "Costa Rica": "CRC", "Belgium": "BEL", "Canada": "CAN",
    "Switzerland": "SUI", "Cameroon": "CMR", "Uruguay": "URU", "South Korea": "KOR",
    "Korea Republic": "KOR", "Portugal": "POR", "Ghana": "GHA", "Brazil": "BRA",
    "Serbia": "SRB",
}

ELO_EURO2024 = {
    "Germany": 2040, "Scotland": 1795, "Hungary": 1855, "Switzerland": 1915,
    "Spain": 2090, "Croatia": 1940, "Italy": 1945, "Albania": 1700,
    "Slovenia": 1775, "Denmark": 1960, "Serbia": 1845, "England": 2050,
    "Poland": 1830, "Netherlands": 2055, "Austria": 1880, "France": 2090,
    "Romania": 1785, "Ukraine": 1840, "Belgium": 1920, "Slovakia": 1770,
    "Turkey": 1800, "Georgia": 1680, "Portugal": 2040, "Czech Republic": 1825,
}

ELO_COPA2024 = {
    "Argentina": 2140, "Canada": 1750, "Peru": 1740, "Chile": 1810,
    "Ecuador": 1830, "Venezuela": 1750, "Mexico": 1810, "Jamaica": 1530,
    "USA": 1800, "Bolivia": 1520, "Uruguay": 1900, "Panama": 1640,
    "Colombia": 1870, "Paraguay": 1730, "Brazil": 2130, "Costa Rica": 1640,
}

PIN_WC2022 = {
    ("QAT", "ECU"): (3.83, 3.18, 2.24), ("ENG", "IRN"): (1.34, 4.9, 13.82),
    ("SEN", "NED"): (7.2, 4.08, 1.56), ("USA", "WAL"): (2.41, 3.13, 3.49),
    ("ARG", "KSA"): (1.17, 7.91, 22.58), ("DEN", "TUN"): (1.49, 4.18, 8.16),
    ("MEX", "POL"): (2.81, 3.08, 2.88), ("FRA", "AUS"): (1.29, 5.79, 11.7),
    ("MAR", "CRO"): (4.1, 3.22, 2.11), ("GER", "JPN"): (1.5, 4.66, 6.67),
    ("ESP", "CRC"): (1.18, 7.48, 19.69), ("BEL", "CAN"): (1.53, 4.48, 6.41),
    ("SUI", "CMR"): (1.75, 3.6, 5.52), ("URU", "KOR"): (1.79, 3.5, 5.37),
    ("POR", "GHA"): (1.38, 4.79, 10.32), ("BRA", "SRB"): (1.48, 4.62, 7.17),
    ("WAL", "IRN"): (2.38, 3.1, 3.38), ("QAT", "SEN"): (3.62, 3.29, 2.18),
    ("NED", "ECU"): (1.62, 3.93, 5.89), ("ENG", "USA"): (1.59, 4.0, 6.08),
    ("TUN", "AUS"): (2.59, 3.14, 2.99), ("POL", "KSA"): (1.61, 3.84, 6.13),
    ("FRA", "DEN"): (2.12, 3.21, 3.9), ("ARG", "MEX"): (1.5, 4.14, 7.26),
    ("JPN", "CRC"): (1.6, 3.86, 6.26), ("BEL", "MAR"): (1.61, 4.05, 5.66),
    ("CRO", "CAN"): (1.74, 3.72, 5.04), ("ESP", "GER"): (2.57, 3.5, 2.75),
    ("CMR", "SRB"): (5.46, 3.63, 1.71), ("KOR", "GHA"): (2.56, 3.04, 3.13),
    ("BRA", "SUI"): (1.46, 4.45, 7.39), ("POR", "URU"): (2.13, 3.41, 3.62),
    ("ECU", "SEN"): (2.71, 3.17, 2.7), ("NED", "QAT"): (1.25, 5.77, 10.98),
    ("WAL", "ENG"): (5.83, 3.84, 1.59), ("IRN", "USA"): (3.84, 3.39, 2.0),
    ("AUS", "DEN"): (6.34, 4.22, 1.5), ("TUN", "FRA"): (10.0, 4.91, 1.32),
    ("POL", "ARG"): (5.18, 3.7, 1.68), ("KSA", "MEX"): (5.3, 3.61, 1.68),
    ("CRO", "BEL"): (3.39, 3.29, 2.19), ("CAN", "MAR"): (3.15, 3.32, 2.29),
    ("CRC", "GER"): (11.11, 5.66, 1.25), ("JPN", "ESP"): (6.27, 4.46, 1.47),
    ("GHA", "URU"): (5.04, 3.49, 1.74), ("KOR", "POR"): (5.53, 4.17, 1.56),
    ("CMR", "BRA"): (12.91, 6.11, 1.22), ("SRB", "SUI"): (2.63, 3.3, 2.69),
    ("NED", "USA"): (2.0, 3.27, 4.47), ("ARG", "AUS"): (1.21, 7.19, 15.7),
    ("FRA", "POL"): (1.3, 5.52, 12.23), ("ENG", "SEN"): (1.52, 4.0, 8.04),
    ("JPN", "CRO"): (4.01, 3.2, 2.14), ("MAR", "ESP"): (6.97, 3.94, 1.58),
    ("BRA", "KOR"): (1.32, 5.39, 10.92), ("POR", "SUI"): (1.93, 3.36, 4.67),
    ("NED", "ARG"): (3.77, 3.21, 2.22), ("ENG", "FRA"): (3.26, 3.28, 2.41),
    ("CRO", "BRA"): (9.08, 4.89, 1.39), ("MAR", "POR"): (5.77, 3.79, 1.7),
    ("ARG", "CRO"): (1.8, 3.43, 5.47), ("FRA", "MAR"): (1.55, 4.0, 7.59),
    ("ARG", "FRA"): (2.74, 3.14, 2.94),
}

RESULTS_WC22_GROUP = {
    ("QAT", "ECU"): "A", ("ENG", "IRN"): "H", ("SEN", "NED"): "A", ("USA", "WAL"): "D",
    ("ARG", "KSA"): "A", ("DEN", "TUN"): "D", ("MEX", "POL"): "D", ("FRA", "AUS"): "H",
    ("MAR", "CRO"): "D", ("GER", "JPN"): "A", ("ESP", "CRC"): "H", ("BEL", "CAN"): "H",
    ("SUI", "CMR"): "H", ("URU", "KOR"): "D", ("POR", "GHA"): "H", ("BRA", "SRB"): "H",
    ("WAL", "IRN"): "A", ("QAT", "SEN"): "A", ("NED", "ECU"): "D", ("ENG", "USA"): "D",
    ("TUN", "AUS"): "A", ("POL", "KSA"): "H", ("FRA", "DEN"): "H", ("ARG", "MEX"): "H",
    ("JPN", "CRC"): "A", ("BEL", "MAR"): "A", ("CRO", "CAN"): "H", ("ESP", "GER"): "D",
    ("CMR", "SRB"): "D", ("KOR", "GHA"): "A", ("BRA", "SUI"): "H", ("POR", "URU"): "H",
    ("ECU", "SEN"): "A", ("NED", "QAT"): "H", ("WAL", "ENG"): "A", ("IRN", "USA"): "A",
    ("AUS", "DEN"): "H", ("TUN", "FRA"): "H", ("POL", "ARG"): "A", ("KSA", "MEX"): "A",
    ("CRO", "BEL"): "D", ("CAN", "MAR"): "A", ("CRC", "GER"): "A", ("JPN", "ESP"): "H",
    ("GHA", "URU"): "D", ("KOR", "POR"): "H", ("CMR", "BRA"): "H", ("SRB", "SUI"): "A",
}

RESULTS_WC22_KO = {
    ("NED", "USA"): "H", ("ARG", "AUS"): "H", ("FRA", "POL"): "H", ("ENG", "SEN"): "H",
    ("JPN", "CRO"): "D", ("BRA", "KOR"): "H", ("MAR", "ESP"): "D", ("POR", "SUI"): "H",
    ("CRO", "BRA"): "D", ("NED", "ARG"): "D", ("MAR", "POR"): "H", ("ENG", "FRA"): "A",
    ("ARG", "CRO"): "H", ("FRA", "MAR"): "H", ("ARG", "FRA"): "D",
}

RESULTS_EURO24_GROUP = {
    ("Germany", "Scotland"): "H", ("Hungary", "Switzerland"): "A",
    ("Germany", "Hungary"): "H", ("Scotland", "Switzerland"): "D",
    ("Switzerland", "Germany"): "D", ("Scotland", "Hungary"): "A",
    ("Spain", "Croatia"): "H", ("Italy", "Albania"): "H",
    ("Croatia", "Albania"): "D", ("Spain", "Italy"): "H",
    ("Albania", "Spain"): "A", ("Croatia", "Italy"): "D",
    ("Slovenia", "Denmark"): "D", ("Serbia", "England"): "A",
    ("Slovenia", "Serbia"): "D", ("Denmark", "England"): "D",
    ("Denmark", "Serbia"): "D", ("England", "Slovenia"): "D",
    ("Poland", "Netherlands"): "A", ("Austria", "France"): "A",
    ("Poland", "Austria"): "A", ("Netherlands", "France"): "D",
    ("Netherlands", "Austria"): "A", ("France", "Poland"): "D",
    ("Romania", "Ukraine"): "H", ("Belgium", "Slovakia"): "A",
    ("Slovakia", "Ukraine"): "A", ("Belgium", "Romania"): "H",
    ("Slovakia", "Romania"): "D", ("Ukraine", "Belgium"): "D",
    ("Turkey", "Georgia"): "H", ("Portugal", "Czech Republic"): "H",
    ("Georgia", "Czech Republic"): "D", ("Turkey", "Portugal"): "A",
    ("Czech Republic", "Turkey"): "A", ("Georgia", "Portugal"): "A",
}

RESULTS_EURO24_KO = {
    ("Switzerland", "Italy"): "H", ("Germany", "Denmark"): "H",
    ("England", "Slovakia"): "D", ("Spain", "Georgia"): "H",
    ("France", "Belgium"): "H", ("Portugal", "Slovenia"): "D",
    ("Romania", "Netherlands"): "A", ("Austria", "Turkey"): "A",
    ("Spain", "Germany"): "D", ("Portugal", "France"): "D",
    ("Netherlands", "Turkey"): "H", ("England", "Switzerland"): "D",
    ("Spain", "France"): "H", ("Netherlands", "England"): "A",
    ("Spain", "England"): "H",
}

RESULTS_COPA24_GROUP = {
    ("Argentina", "Canada"): "H", ("Peru", "Chile"): "D",
    ("Chile", "Argentina"): "A", ("Peru", "Canada"): "A",
    ("Argentina", "Peru"): "H", ("Canada", "Chile"): "D",
    ("Ecuador", "Venezuela"): "D", ("Mexico", "Jamaica"): "H",
    ("Ecuador", "Jamaica"): "H", ("Venezuela", "Mexico"): "H",
    ("Mexico", "Ecuador"): "D", ("Jamaica", "Venezuela"): "A",
    ("USA", "Bolivia"): "H", ("Uruguay", "Panama"): "H",
    ("Panama", "USA"): "H", ("Uruguay", "Bolivia"): "H",
    ("Bolivia", "Panama"): "D", ("USA", "Uruguay"): "A",
    ("Colombia", "Paraguay"): "H", ("Brazil", "Costa Rica"): "D",
    ("Colombia", "Costa Rica"): "H", ("Paraguay", "Brazil"): "A",
    ("Brazil", "Colombia"): "D", ("Costa Rica", "Paraguay"): "A",
}

RESULTS_COPA24_KO = {
    ("Argentina", "Ecuador"): "D", ("Venezuela", "Canada"): "D",
    ("Uruguay", "Brazil"): "D", ("Colombia", "Panama"): "H",
    ("Colombia", "Uruguay"): "H", ("Argentina", "Colombia"): "D",
}

ALL_COMPS = [
    "WC2022", "EURO2024", "COPA2024",
    "QUALIF_WC2026", "NL_2022_23", "NL_2024_25",
    "GOLD_CUP_2025", "CAN2025", "FRIENDLIES", "CONCACAF_NL",
]

COMP_LABELS = {
    "WC2022": "CM 2022",
    "EURO2024": "Euro 2024",
    "COPA2024": "Copa 2024",
    "QUALIF_WC2026": "Qualif. CM 2026",
    "NL_2022_23": "Nations League 22-23",
    "NL_2024_25": "Nations League 24-25",
    "GOLD_CUP_2025": "Gold Cup 2025",
    "CAN2025": "CAN 2025",
    "FRIENDLIES": "Amicaux",
    "CONCACAF_NL": "CONCACAF NL",
}


_IMPLIED_ELO_CACHE = None

def _load_implied_elo():
    global _IMPLIED_ELO_CACHE
    if _IMPLIED_ELO_CACHE is not None:
        return _IMPLIED_ELO_CACHE
    if IMPLIED_ELO_PATH.exists():
        try:
            with open(IMPLIED_ELO_PATH) as f:
                _IMPLIED_ELO_CACHE = json.load(f)
                return _IMPLIED_ELO_CACHE
        except Exception:
            pass
    _IMPLIED_ELO_CACHE = {}
    return _IMPLIED_ELO_CACHE

def _resolve_elo(team_name, comp_elo_dict=None):
    if comp_elo_dict and team_name in comp_elo_dict:
        return comp_elo_dict[team_name]

    implied = _load_implied_elo()
    if team_name in implied:
        return implied[team_name]

    code = TEAM_NAME_TO_ELO_KEY.get(team_name)
    if code and code in DEFAULT_ELO:
        return DEFAULT_ELO[code]

    return 1400


_YOUTH_SUFFIXES = (" U17", " U18", " U19", " U20", " U21", " U23")


def _is_youth_team(name):
    return any(name.endswith(s) for s in _YOUTH_SUFFIXES)


def _load_scraped_matches():
    if not SCRAPED_ODDS_PATH.exists():
        return []
    try:
        with open(SCRAPED_ODDS_PATH) as f:
            raw = json.load(f)
    except Exception:
        return []

    existing_keys = set()
    for (h, a) in RESULTS_WC22_GROUP:
        existing_keys.add((h, a))
    for (h, a) in RESULTS_WC22_KO:
        existing_keys.add((h, a))
    for (h, a) in RESULTS_EURO24_GROUP:
        existing_keys.add((h, a))
    for (h, a) in RESULTS_EURO24_KO:
        existing_keys.add((h, a))
    for (h, a) in RESULTS_COPA24_GROUP:
        existing_keys.add((h, a))
    for (h, a) in RESULTS_COPA24_KO:
        existing_keys.add((h, a))

    matches = []
    seen = set()
    for m in raw:
        if _is_youth_team(m["home"]) or _is_youth_team(m["away"]):
            continue

        if m.get("comp") in ("WC2022", "EURO2024", "COPA2024"):
            if (m["home"], m["away"]) in existing_keys:
                continue

        key = (m["home"], m["away"], m.get("date", ""))
        if key in seen:
            continue
        seen.add(key)

        pin_h = m.get("fair_h", 0)
        pin_d = m.get("fair_d", 0)
        pin_a = m.get("fair_a", 0)

        elo_h = _resolve_elo(m["home"])
        elo_a = _resolve_elo(m["away"])

        matches.append({
            "comp": m["comp"],
            "phase": m.get("phase", "G"),
            "home": m["home"],
            "away": m["away"],
            "result": m["result"],
            "elo_h": elo_h,
            "elo_a": elo_a,
            "pin_h": pin_h,
            "pin_d": pin_d,
            "pin_a": pin_a,
            "ref_book": m.get("ref_book", ""),
            "date": m.get("date", ""),
        })

    return matches


def _sigmoid_custom(delta_elo, scale, draw_base, d_half, power, quality,
                    elo_avg=None, phase="G",
                    db_close=5.0, db_mid=3.0, db_ko=8.0, db_max=10.0,
                    fb_group=5.0, fb_ko=2.0, fav_threshold=300):
    d_half = max(d_half, 1.0)
    draw_adj = draw_base
    if elo_avg is not None:
        draw_adj = draw_base + quality * (elo_avg - 1800) / 100
        draw_adj = max(draw_adj, 5.0)
    draw = draw_adj / (1.0 + (abs(delta_elo) / d_half) ** power)
    draw = max(draw, 0.5)
    sig = 1.0 / (1.0 + 10.0 ** (-delta_elo / scale))
    p1 = (100.0 - draw) * sig
    p2 = (100.0 - draw) * (1.0 - sig)
    p1 = float(np.clip(p1, 0.5, 99.0))
    p2 = float(np.clip(p2, 0.5, 99.0))
    draw = float(np.clip(draw, 0.5, 99.0))
    total = p1 + draw + p2
    p1, px, p2 = p1 / total, draw / total, p2 / total

    abs_d = abs(delta_elo)
    draw_boost = 0.0
    if abs_d < 100:
        draw_boost += db_close / 100.0
    elif abs_d < 200:
        draw_boost += db_mid / 100.0
    if phase == "K":
        draw_boost += db_ko / 100.0
    draw_boost = min(draw_boost, db_max / 100.0)

    fav_boost = 0.0
    if abs_d >= fav_threshold:
        if phase == "K":
            fav_boost = fb_ko / 100.0
        else:
            fav_boost = fb_group / 100.0

    net_draw = draw_boost - fav_boost * 0.7
    net_draw = max(net_draw, 0.0)
    px_new = px + net_draw
    surplus = net_draw
    if p1 + p2 > 0:
        p1_new = p1 - surplus * (p1 / (p1 + p2))
        p2_new = p2 - surplus * (p2 / (p1 + p2))
    else:
        p1_new, p2_new = p1, p2

    if fav_boost > 0:
        if delta_elo >= 0:
            p1_new += fav_boost
            px_new -= fav_boost * 0.7
            p2_new -= fav_boost * 0.3
        else:
            p2_new += fav_boost
            px_new -= fav_boost * 0.7
            p1_new -= fav_boost * 0.3

    p1_new = max(p1_new, 0.005)
    p2_new = max(p2_new, 0.005)
    px_new = max(px_new, 0.005)
    total = p1_new + px_new + p2_new
    return p1_new / total, px_new / total, p2_new / total


def build_backtest_dataset():
    with open(HIST_ODDS_PATH) as f:
        odds_raw = json.load(f)
    euro_odds = {(m["home"], m["away"]): m for m in odds_raw if m["comp"] == "EURO2024"}
    copa_odds = {(m["home"], m["away"]): m for m in odds_raw if m["comp"] == "COPA2024"}

    matches = []

    for (h, a), res in RESULTS_WC22_GROUP.items():
        pin = PIN_WC2022.get((h, a), (0, 0, 0))
        matches.append({
            "comp": "WC2022", "home": h, "away": a, "result": res, "phase": "G",
            "elo_h": ELO_WC2022.get(h, 1500), "elo_a": ELO_WC2022.get(a, 1500),
            "pin_h": pin[0], "pin_d": pin[1], "pin_a": pin[2],
        })
    for (h, a), res in RESULTS_WC22_KO.items():
        pin = PIN_WC2022.get((h, a), (0, 0, 0))
        matches.append({
            "comp": "WC2022", "home": h, "away": a, "result": res, "phase": "K",
            "elo_h": ELO_WC2022.get(h, 1500), "elo_a": ELO_WC2022.get(a, 1500),
            "pin_h": pin[0], "pin_d": pin[1], "pin_a": pin[2],
        })

    for (h, a), res in RESULTS_EURO24_GROUP.items():
        om = euro_odds.get((h, a))
        if not om or om["odds_h"] <= 0:
            continue
        matches.append({
            "comp": "EURO2024", "home": h, "away": a, "result": res, "phase": "G",
            "elo_h": ELO_EURO2024.get(h, 1700), "elo_a": ELO_EURO2024.get(a, 1700),
            "pin_h": om["odds_h"], "pin_d": om["odds_d"], "pin_a": om["odds_a"],
        })
    for (h, a), res in RESULTS_EURO24_KO.items():
        om = euro_odds.get((h, a))
        if not om or om["odds_h"] <= 0:
            continue
        matches.append({
            "comp": "EURO2024", "home": h, "away": a, "result": res, "phase": "K",
            "elo_h": ELO_EURO2024.get(h, 1700), "elo_a": ELO_EURO2024.get(a, 1700),
            "pin_h": om["odds_h"], "pin_d": om["odds_d"], "pin_a": om["odds_a"],
        })

    for (h, a), res in RESULTS_COPA24_GROUP.items():
        om = copa_odds.get((h, a))
        if not om or om["odds_h"] <= 0:
            continue
        matches.append({
            "comp": "COPA2024", "home": h, "away": a, "result": res, "phase": "G",
            "elo_h": ELO_COPA2024.get(h, 1700), "elo_a": ELO_COPA2024.get(a, 1700),
            "pin_h": om["odds_h"], "pin_d": om["odds_d"], "pin_a": om["odds_a"],
        })
    for (h, a), res in RESULTS_COPA24_KO.items():
        om = copa_odds.get((h, a))
        if not om or om["odds_h"] <= 0:
            continue
        matches.append({
            "comp": "COPA2024", "home": h, "away": a, "result": res, "phase": "K",
            "elo_h": ELO_COPA2024.get(h, 1700), "elo_a": ELO_COPA2024.get(a, 1700),
            "pin_h": om["odds_h"], "pin_d": om["odds_d"], "pin_a": om["odds_a"],
        })

    scraped = _load_scraped_matches()
    matches.extend(scraped)

    return matches


def run_backtest(matches, params):
    scale = params["scale"]
    draw_base = params["draw_base"]
    d_half = params["d_half"]
    power = params["power"]
    quality = params["quality"]
    db_close = params["db_close"]
    db_mid = params["db_mid"]
    db_ko = params["db_ko"]
    db_max = params["db_max"]
    fb_group = params["fb_group"]
    fb_ko = params["fb_ko"]
    fav_threshold = params["fav_threshold"]

    results = []
    for m in matches:
        delta = m["elo_h"] - m["elo_a"]
        elo_avg = (m["elo_h"] + m["elo_a"]) / 2
        p1, px, p2 = _sigmoid_custom(
            delta, scale, draw_base, d_half, power, quality,
            elo_avg=elo_avg, phase=m["phase"],
            db_close=db_close, db_mid=db_mid, db_ko=db_ko, db_max=db_max,
            fb_group=fb_group, fb_ko=fb_ko, fav_threshold=fav_threshold,
        )

        v8_h = 1 / p1 if p1 > 0.001 else 999
        v8_d = 1 / px if px > 0.001 else 999
        v8_a = 1 / p2 if p2 > 0.001 else 999

        actual = m["result"]
        actual_vec = [1 if actual == "H" else 0, 1 if actual == "D" else 0, 1 if actual == "A" else 0]
        brier = (p1 - actual_vec[0]) ** 2 + (px - actual_vec[1]) ** 2 + (p2 - actual_vec[2]) ** 2
        eps = 1e-15
        log_loss = -(
            actual_vec[0] * math.log(max(p1, eps))
            + actual_vec[1] * math.log(max(px, eps))
            + actual_vec[2] * math.log(max(p2, eps))
        )

        pin_brier = None
        pin_log_loss = None
        div_h = div_d = div_a = None
        has_pin = m["pin_h"] > 0 and m["pin_d"] > 0 and m["pin_a"] > 0
        if has_pin:
            margin = 1 / m["pin_h"] + 1 / m["pin_d"] + 1 / m["pin_a"]
            pp1 = (1 / m["pin_h"]) / margin
            ppx = (1 / m["pin_d"]) / margin
            pp2 = (1 / m["pin_a"]) / margin
            pin_brier = (pp1 - actual_vec[0]) ** 2 + (ppx - actual_vec[1]) ** 2 + (pp2 - actual_vec[2]) ** 2
            pin_log_loss = -(
                actual_vec[0] * math.log(max(pp1, eps))
                + actual_vec[1] * math.log(max(ppx, eps))
                + actual_vec[2] * math.log(max(pp2, eps))
            )
            div_h = v8_h - m["pin_h"]
            div_d = v8_d - m["pin_d"]
            div_a = v8_a - m["pin_a"]

        correct_side = (
            (actual == "H" and p1 >= px and p1 >= p2)
            or (actual == "D" and px >= p1 and px >= p2)
            or (actual == "A" and p2 >= p1 and p2 >= px)
        )

        results.append({
            "comp": m["comp"], "phase": m["phase"],
            "home": m["home"], "away": m["away"],
            "result": actual,
            "p1": p1, "px": px, "p2": p2,
            "v8_h": v8_h, "v8_d": v8_d, "v8_a": v8_a,
            "pin_h": m["pin_h"], "pin_d": m["pin_d"], "pin_a": m["pin_a"],
            "brier": brier, "log_loss": log_loss,
            "pin_brier": pin_brier, "pin_log_loss": pin_log_loss,
            "div_h": div_h, "div_d": div_d, "div_a": div_a,
            "has_pin": has_pin,
            "correct": correct_side,
            "delta": m["elo_h"] - m["elo_a"],
            "ref_book": m.get("ref_book", ""),
        })

    return results


def compute_metrics(results):
    n = len(results)
    if n == 0:
        return {}

    brier_avg = np.mean([r["brier"] for r in results])
    ll_avg = np.mean([r["log_loss"] for r in results])
    accuracy = sum(1 for r in results if r["correct"]) / n * 100

    with_pin = [r for r in results if r["has_pin"]]
    n_pin = len(with_pin)

    metrics = {
        "n_matches": n,
        "brier_v8": round(brier_avg, 4),
        "log_loss_v8": round(ll_avg, 4),
        "accuracy": round(accuracy, 1),
    }

    if n_pin > 0:
        pin_brier = np.mean([r["pin_brier"] for r in with_pin])
        pin_ll = np.mean([r["pin_log_loss"] for r in with_pin])
        v8_brier_sub = np.mean([r["brier"] for r in with_pin])
        v8_ll_sub = np.mean([r["log_loss"] for r in with_pin])

        all_divs = []
        abs_divs = []
        close_010 = close_020 = close_050 = close_100 = 0
        total_outcomes = 0
        for r in with_pin:
            for dv in [r["div_h"], r["div_d"], r["div_a"]]:
                if dv is not None:
                    all_divs.append(dv)
                    abs_divs.append(abs(dv))
                    total_outcomes += 1
                    if abs(dv) <= 0.10:
                        close_010 += 1
                    if abs(dv) <= 0.20:
                        close_020 += 1
                    if abs(dv) <= 0.50:
                        close_050 += 1
                    if abs(dv) <= 1.00:
                        close_100 += 1

        pct_divs = []
        for r in with_pin:
            if r["pin_h"] > 0:
                pct_divs.append((r["v8_h"] / r["pin_h"] - 1) * 100)
            if r["pin_d"] > 0:
                pct_divs.append((r["v8_d"] / r["pin_d"] - 1) * 100)
            if r["pin_a"] > 0:
                pct_divs.append((r["v8_a"] / r["pin_a"] - 1) * 100)

        metrics.update({
            "n_with_pin": n_pin,
            "brier_pin": round(pin_brier, 4),
            "log_loss_pin": round(pin_ll, 4),
            "brier_v8_sub": round(v8_brier_sub, 4),
            "log_loss_v8_sub": round(v8_ll_sub, 4),
            "div_mean": round(np.mean(all_divs), 3) if all_divs else 0,
            "div_abs_mean": round(np.mean(abs_divs), 3) if abs_divs else 0,
            "div_median": round(np.median(abs_divs), 3) if abs_divs else 0,
            "div_pct_mean": round(np.mean(pct_divs), 2) if pct_divs else 0,
            "div_pct_abs_mean": round(np.mean(np.abs(pct_divs)), 2) if pct_divs else 0,
            "close_010": close_010,
            "close_020": close_020,
            "close_050": close_050,
            "close_100": close_100,
            "total_outcomes": total_outcomes,
        })

    comps_in_data = sorted(set(r["comp"] for r in results))
    by_comp = {}
    for comp in comps_in_data:
        sub = [r for r in results if r["comp"] == comp]
        if not sub:
            continue
        by_comp[comp] = {
            "n": len(sub),
            "brier": round(np.mean([r["brier"] for r in sub]), 4),
            "accuracy": round(sum(1 for r in sub if r["correct"]) / len(sub) * 100, 1),
        }
        sub_pin = [r for r in sub if r["has_pin"]]
        if sub_pin:
            divs = []
            for r in sub_pin:
                for dv in [r["div_h"], r["div_d"], r["div_a"]]:
                    if dv is not None:
                        divs.append(abs(dv))
            by_comp[comp]["div_abs"] = round(np.mean(divs), 3) if divs else 0
            by_comp[comp]["n_with_ref"] = len(sub_pin)

    by_phase = {}
    for phase, label in [("G", "Groupes"), ("Q", "Qualifs"), ("K", "KO")]:
        sub = [r for r in results if r["phase"] == phase]
        if not sub:
            continue
        by_phase[label] = {
            "n": len(sub),
            "brier": round(np.mean([r["brier"] for r in sub]), 4),
            "accuracy": round(sum(1 for r in sub if r["correct"]) / len(sub) * 100, 1),
        }

    metrics["by_comp"] = by_comp
    metrics["by_phase"] = by_phase

    return metrics


DEFAULT_PARAMS = {
    "scale": 431.3,
    "draw_base": 27.9,
    "d_half": 540.0,
    "power": 2.6,
    "quality": -0.70,
    "db_close": 5.0,
    "db_mid": 3.0,
    "db_ko": 8.0,
    "db_max": 10.0,
    "fb_group": 5.0,
    "fb_ko": 2.0,
    "fav_threshold": 300,
}
