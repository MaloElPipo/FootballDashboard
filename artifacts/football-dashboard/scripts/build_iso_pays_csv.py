#!/usr/bin/env python3
"""
Génère un CSV référentiel des pays couverts par le portail :
- Pays unique (déduit de LEAGUES + NATIONAL_TEAMS)
- Code ISO 3166-1 alpha-3 et alpha-2
- Code FIFA / IOC (utilisé par Transfermarkt pour les sélections)
- Indique si le pays a une (ou plusieurs) ligue(s) couverte(s) et/ou une sélection
- Codes TM associés

Output : live/data/portail/iso_pays.csv
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live.leagues_master import LEAGUES, NATIONAL_TEAMS  # noqa: E402

OUTPUT = ROOT / "live" / "data" / "portail" / "iso_pays.csv"

# ============================================================
# Référentiel pays FR -> (ISO 3166-1 alpha-3, alpha-2, FIFA/IOC)
# ============================================================
# Notes :
# - ISO 3166-1 = standard officiel des pays (alpha-3 / alpha-2).
# - FIFA = code utilisé pour les sélections nationales par TM/FIFA.
#   Souvent identique à l'ISO mais pas toujours :
#     Allemagne : ISO=DEU, FIFA=GER
#     Pays-Bas  : ISO=NLD, FIFA=NED
#     Suisse    : ISO=CHE, FIFA=SUI
#     Danemark  : ISO=DNK, FIFA=DEN
#     Croatie   : ISO=HRV, FIFA=CRO
#     Portugal  : ISO=PRT, FIFA=POR
# - Pour Angleterre/Écosse/Pays de Galles/Irlande du Nord : ce sont des
#   nations constitutives du Royaume-Uni (ISO 3166-2:GB-ENG/SCT/WLS/NIR),
#   on indique GBR comme alpha-3 et le sous-code régional en plus.
PAYS_REF: dict[str, tuple[str, str, str | None]] = {
    # Format : "Nom FR" -> (alpha-3, alpha-2, code_fifa_si_different_de_alpha3)
    # Europe
    "Albanie":             ("ALB", "AL", "ALB"),
    "Allemagne":           ("DEU", "DE", "GER"),
    "Angleterre":          ("GBR", "GB", "ENG"),  # GB-ENG
    "Arménie":             ("ARM", "AM", "ARM"),
    "Autriche":            ("AUT", "AT", "AUT"),
    "Azerbaïdjan":         ("AZE", "AZ", "AZE"),
    "Belgique":            ("BEL", "BE", "BEL"),
    "Biélorussie":         ("BLR", "BY", "BLR"),
    "Bosnie-Herzégovine":  ("BIH", "BA", "BIH"),
    "Bulgarie":            ("BGR", "BG", "BUL"),
    "Chypre":              ("CYP", "CY", "CYP"),
    "Croatie":             ("HRV", "HR", "CRO"),
    "Danemark":            ("DNK", "DK", "DEN"),
    "Espagne":             ("ESP", "ES", "ESP"),
    "Estonie":             ("EST", "EE", "EST"),
    "Finlande":            ("FIN", "FI", "FIN"),
    "France":              ("FRA", "FR", "FRA"),
    "Grèce":               ("GRC", "GR", "GRE"),
    "Géorgie":             ("GEO", "GE", "GEO"),
    "Hongrie":             ("HUN", "HU", "HUN"),
    "Irlande":             ("IRL", "IE", "IRL"),
    "Irlande du Nord":     ("GBR", "GB", "NIR"),  # GB-NIR
    "Islande":             ("ISL", "IS", "ISL"),
    "Italie":              ("ITA", "IT", "ITA"),
    "Lettonie":            ("LVA", "LV", "LVA"),
    "Lituanie":            ("LTU", "LT", "LTU"),
    "Luxembourg":          ("LUX", "LU", "LUX"),
    "Macédoine du Nord":   ("MKD", "MK", "MKD"),
    "Malte":               ("MLT", "MT", "MLT"),
    "Moldavie":            ("MDA", "MD", "MDA"),
    "Monténégro":          ("MNE", "ME", "MNE"),
    "Norvège":             ("NOR", "NO", "NOR"),
    "Pays de Galles":      ("GBR", "GB", "WAL"),  # GB-WLS
    "Pays-Bas":            ("NLD", "NL", "NED"),
    "Pologne":             ("POL", "PL", "POL"),
    "Portugal":            ("PRT", "PT", "POR"),
    "Roumanie":            ("ROU", "RO", "ROU"),
    "Russie":              ("RUS", "RU", "RUS"),
    "Saint-Marin":         ("SMR", "SM", "SMR"),
    "Serbie":              ("SRB", "RS", "SRB"),
    "Slovaquie":           ("SVK", "SK", "SVK"),
    "Slovénie":            ("SVN", "SI", "SVN"),
    "Suisse":              ("CHE", "CH", "SUI"),
    "Suède":               ("SWE", "SE", "SWE"),
    "Tchéquie":            ("CZE", "CZ", "CZE"),
    "Turquie":             ("TUR", "TR", "TUR"),
    "Ukraine":             ("UKR", "UA", "UKR"),
    "Écosse":              ("GBR", "GB", "SCO"),  # GB-SCT

    # Amériques
    "Argentine":           ("ARG", "AR", "ARG"),
    "Bolivie":             ("BOL", "BO", "BOL"),
    "Brésil":              ("BRA", "BR", "BRA"),
    "Canada":              ("CAN", "CA", "CAN"),
    "Chili":               ("CHL", "CL", "CHI"),
    "Colombie":            ("COL", "CO", "COL"),
    "Costa Rica":          ("CRI", "CR", "CRC"),
    "Équateur":            ("ECU", "EC", "ECU"),
    "États-Unis":          ("USA", "US", "USA"),
    "Jamaïque":            ("JAM", "JM", "JAM"),
    "Mexique":             ("MEX", "MX", "MEX"),
    "Panama":              ("PAN", "PA", "PAN"),
    "Paraguay":            ("PRY", "PY", "PAR"),
    "Pérou":               ("PER", "PE", "PER"),
    "Uruguay":             ("URY", "UY", "URU"),
    "Venezuela":           ("VEN", "VE", "VEN"),

    # Afrique
    "Afrique du Sud":      ("ZAF", "ZA", "RSA"),
    "Algérie":             ("DZA", "DZ", "ALG"),
    "Cameroun":            ("CMR", "CM", "CMR"),
    "Côte d'Ivoire":       ("CIV", "CI", "CIV"),
    "Égypte":              ("EGY", "EG", "EGY"),
    "Ghana":               ("GHA", "GH", "GHA"),
    "Maroc":               ("MAR", "MA", "MAR"),
    "Nigeria":             ("NGA", "NG", "NGA"),
    "Sénégal":             ("SEN", "SN", "SEN"),
    "Tunisie":             ("TUN", "TN", "TUN"),

    # Asie / Océanie
    "Arabie Saoudite":     ("SAU", "SA", "KSA"),
    "Australie":           ("AUS", "AU", "AUS"),
    "Chine":               ("CHN", "CN", "CHN"),
    "Corée du Nord":       ("PRK", "KP", "PRK"),
    "Corée du Sud":        ("KOR", "KR", "KOR"),
    "Émirats arabes unis": ("ARE", "AE", "UAE"),
    "Inde":                ("IND", "IN", "IND"),
    "Indonésie":           ("IDN", "ID", "IDN"),
    "Irak":                ("IRQ", "IQ", "IRQ"),
    "Iran":                ("IRN", "IR", "IRN"),
    "Israël":              ("ISR", "IL", "ISR"),
    "Japon":               ("JPN", "JP", "JPN"),
    "Jordanie":            ("JOR", "JO", "JOR"),
    "Nouvelle-Zélande":    ("NZL", "NZ", "NZL"),
    "Ouzbékistan":         ("UZB", "UZ", "UZB"),
    "Qatar":               ("QAT", "QA", "QAT"),
    "Thaïlande":           ("THA", "TH", "THA"),
}


def main() -> int:
    # Tables de résolution code_tm -> nom complet
    # Pour les ligues : nom de la compétition (ex: "Ligue 1", "Premier League")
    # Pour les sélections : "Sélection <pays>" pour distinguer dans la liste consolidée
    nom_par_code: dict[str, str] = {}
    for L in LEAGUES:
        nom_par_code[L["code_tm"]] = L["nom"]
    for t in NATIONAL_TEAMS:
        nom_par_code[t["code_tm"]] = f"Sélection {t['nom']}"

    # Index : pays_fr -> {ligues: [(code, nom), ...], selection: (code, nom) or None}
    pays_data: dict[str, dict] = {}

    for L in LEAGUES:
        p = L["pays"]
        pays_data.setdefault(p, {"ligues": [], "selection": None})
        pays_data[p]["ligues"].append((L["code_tm"], L["nom"]))

    # Mapping nom_selection FR -> (code_tm, nom_pays)
    for t in NATIONAL_TEAMS:
        nom = t["nom"]
        pays_data.setdefault(nom, {"ligues": [], "selection": None})
        pays_data[nom]["selection"] = (t["code_tm"], f"Sélection {nom}")

    # Vérifier que tous les pays sont dans le ref
    missing = sorted(set(pays_data) - set(PAYS_REF))
    if missing:
        print(f"[ERR] Pays absents du référentiel ISO : {missing}")
        return 1

    # Génération CSV
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "pays_fr",
            "iso_alpha3",
            "iso_alpha2",
            "code_fifa",
            "a_ligue",
            "a_selection",
            "nb_ligues",
            "nb_competitions",                # ligues + sélection (1 si seulement nat, n+1 si ligue+nat)
            "competitions_noms",              # noms complets ex: "Ligue 1;Ligue 2;Ligue 3;Sélection France"
            "competitions_code_nom",          # code=nom ex: "FR1=Ligue 1;FR2=Ligue 2;FRA=Sélection France"
            "codes_tm_competitions",          # codes seuls regroupés ex: "FR1;FR2;FR3;FRA"
            "codes_tm_ligues",                # ligues seules (pour compat)
            "code_tm_selection",              # sélection seule (pour compat)
            "couverture",                     # league_only | national_only | both
        ])

        rows = []
        for pays in sorted(pays_data, key=lambda x: PAYS_REF[x][0]):
            iso3, iso2, fifa = PAYS_REF[pays]
            data = pays_data[pays]
            ligues_tuples = sorted(data["ligues"], key=lambda t: t[0])  # tri par code
            sel_tuple = data["selection"]
            a_ligue = bool(ligues_tuples)
            a_sel = bool(sel_tuple)
            if a_ligue and a_sel:
                cover = "both"
            elif a_ligue:
                cover = "league_only"
            else:
                cover = "national_only"

            # Listes : ligues d'abord (tri par code), sélection en dernier
            all_tuples = list(ligues_tuples)
            if sel_tuple:
                all_tuples.append(sel_tuple)

            codes_only       = [c for c, _ in all_tuples]
            noms_only        = [n for _, n in all_tuples]
            code_nom_pairs   = [f"{c}={n}" for c, n in all_tuples]
            ligue_codes_only = [c for c, _ in ligues_tuples]
            sel_code         = sel_tuple[0] if sel_tuple else ""

            rows.append([
                pays,
                iso3,
                iso2,
                fifa or iso3,
                "oui" if a_ligue else "non",
                "oui" if a_sel else "non",
                len(ligues_tuples),
                len(all_tuples),
                ";".join(noms_only),
                ";".join(code_nom_pairs),
                ";".join(codes_only),
                ";".join(ligue_codes_only),
                sel_code,
                cover,
            ])
        w.writerows(rows)

    # Récap
    n_total = len(rows)
    n_both = sum(1 for r in rows if r[-1] == "both")
    n_league = sum(1 for r in rows if r[-1] == "league_only")
    n_nat = sum(1 for r in rows if r[-1] == "national_only")
    print(f"[OK] {OUTPUT}")
    print(f"     {n_total} pays uniques au total")
    print(f"     - both         : {n_both:3d} (ligue ET sélection)")
    print(f"     - league_only  : {n_league:3d} (ligue de clubs uniquement)")
    print(f"     - national_only: {n_nat:3d} (sélection CDM 2026 uniquement)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
