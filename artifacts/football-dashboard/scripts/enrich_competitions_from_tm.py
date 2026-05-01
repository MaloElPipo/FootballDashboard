"""
Enrichit `competitions_vues.csv` en allant chercher sur Transfermarkt
le nom + pays + type de chaque compétition dont la colonne
`connue_dans_master` vaut "non".

Endpoint TM utilisé :
    GET https://www.transfermarkt.com/wettbewerb/startseite/wettbewerb/{CODE}

Pour les coupes, TM redirige vers /pokalwettbewerb/. La page contient :
- <h1> : nom officiel de la compétition
- 1re image flagge avec alt="<Country>" : pays organisateur (en anglais)

Cache : `live/data/portail/_competitions_tm_cache.json`
    {code: {"nom": ..., "pays_en": ..., "type": ..., "slug": ...,
            "fetched_at": ISO8601}}

Usage :
    python3 scripts/enrich_competitions_from_tm.py [--workers 3] [--limit N]
        [--force] [--input PATH]

Ne re-scrappe pas les codes déjà cachés sauf --force.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PORTAL_DIR = ROOT / "live" / "data" / "portail"
INPUT_CSV = PORTAL_DIR / "competitions_vues.csv"
CACHE_PATH = PORTAL_DIR / "_competitions_tm_cache.json"

BASE_URL = "https://www.transfermarkt.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/146.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en;q=0.9,fr;q=0.7",
    "Referer": "https://www.transfermarkt.com/",
}

# Mapping pays anglais (TM) -> pays français (cohérent avec leagues_master).
# Liste minimale : on ajoute au fil des découvertes.
EN_TO_FR = {
    "Albania": "Albanie",
    "Algeria": "Algérie",
    "Argentina": "Argentine",
    "Armenia": "Arménie",
    "Australia": "Australie",
    "Austria": "Autriche",
    "Azerbaijan": "Azerbaïdjan",
    "Belarus": "Biélorussie",
    "Belgium": "Belgique",
    "Bolivia": "Bolivie",
    "Bosnia-Herzegovina": "Bosnie-Herzégovine",
    "Brazil": "Brésil",
    "Bulgaria": "Bulgarie",
    "Burkina Faso": "Burkina Faso",
    "Cameroon": "Cameroun",
    "Canada": "Canada",
    "Chile": "Chili",
    "China": "Chine",
    "Colombia": "Colombie",
    "Costa Rica": "Costa Rica",
    "Croatia": "Croatie",
    "Curacao": "Curaçao",
    "Cyprus": "Chypre",
    "Czech Republic": "République tchèque",
    "Denmark": "Danemark",
    "Ecuador": "Équateur",
    "Egypt": "Égypte",
    "El Salvador": "Salvador",
    "England": "Angleterre",
    "Estonia": "Estonie",
    "Faroe Islands": "Îles Féroé",
    "Finland": "Finlande",
    "France": "France",
    "Gabon": "Gabon",
    "Georgia": "Géorgie",
    "Germany": "Allemagne",
    "Ghana": "Ghana",
    "Greece": "Grèce",
    "Guinea": "Guinée",
    "Haiti": "Haïti",
    "Honduras": "Honduras",
    "Hungary": "Hongrie",
    "Iceland": "Islande",
    "Iran": "Iran",
    "Iraq": "Irak",
    "Ireland": "Irlande",
    "Israel": "Israël",
    "Italy": "Italie",
    "Ivory Coast": "Côte d'Ivoire",
    "Jamaica": "Jamaïque",
    "Japan": "Japon",
    "Jordan": "Jordanie",
    "Kazakhstan": "Kazakhstan",
    "Kosovo": "Kosovo",
    "Kuwait": "Koweït",
    "Latvia": "Lettonie",
    "Lebanon": "Liban",
    "Libya": "Libye",
    "Lithuania": "Lituanie",
    "Luxembourg": "Luxembourg",
    "Mali": "Mali",
    "Malta": "Malte",
    "Mexico": "Mexique",
    "Moldova": "Moldavie",
    "Montenegro": "Monténégro",
    "Morocco": "Maroc",
    "Netherlands": "Pays-Bas",
    "New Zealand": "Nouvelle-Zélande",
    "Nigeria": "Nigeria",
    "Northern Ireland": "Irlande du Nord",
    "North Macedonia": "Macédoine du Nord",
    "Norway": "Norvège",
    "Oman": "Oman",
    "Panama": "Panama",
    "Paraguay": "Paraguay",
    "Peru": "Pérou",
    "Poland": "Pologne",
    "Portugal": "Portugal",
    "Qatar": "Qatar",
    "Romania": "Roumanie",
    "Russia": "Russie",
    "Saudi Arabia": "Arabie Saoudite",
    "Scotland": "Écosse",
    "Senegal": "Sénégal",
    "Serbia": "Serbie",
    "Slovakia": "Slovaquie",
    "Slovenia": "Slovénie",
    "South Africa": "Afrique du Sud",
    "South Korea": "Corée du Sud",
    "Spain": "Espagne",
    "Sweden": "Suède",
    "Switzerland": "Suisse",
    "Syria": "Syrie",
    "Thailand": "Thaïlande",
    "Tunisia": "Tunisie",
    "Turkey": "Turquie",
    "Ukraine": "Ukraine",
    "United Arab Emirates": "Émirats arabes unis",
    "United States": "États-Unis",
    "Uruguay": "Uruguay",
    "Uzbekistan": "Ouzbékistan",
    "Venezuela": "Venezuela",
    "Wales": "Pays de Galles",
    # --- Ajouts post-enrichissement TM ---
    "Andorra": "Andorre",
    "Bangladesh": "Bangladesh",
    "Belize": "Belize",
    "Cambodia": "Cambodge",
    "Chinese Taipei": "Taipei chinois",
    "Dominican Republic": "République dominicaine",
    "Fiji": "Fidji",
    "Gibraltar": "Gibraltar",
    "Guatemala": "Guatemala",
    "Hongkong": "Hong Kong",
    "India": "Inde",
    "Indonesia": "Indonésie",
    "Korea, South": "Corée du Sud",
    "Kyrgyzstan": "Kirghizstan",
    "Liechtenstein": "Liechtenstein",
    "Malaysia": "Malaisie",
    "Mauritania": "Mauritanie",
    "New Caledonia": "Nouvelle-Calédonie",
    "Nicaragua": "Nicaragua",
    "North Korea": "Corée du Nord",
    "Pakistan": "Pakistan",
    "Philippines": "Philippines",
    "Puerto Rico": "Porto Rico",
    "Saint Kitts and Nevis": "Saint-Kitts-et-Nevis",
    "Saint Vincent and the Grenadines": "Saint-Vincent-et-les-Grenadines",
    "San Marino": "Saint-Marin",
    "Singapore": "Singapour",
    "South Sudan": "Soudan du Sud",
    "Tajikistan": "Tadjikistan",
    "Trinidad and Tobago": "Trinité-et-Tobago",
    "Türkiye": "Turquie",
    "Uganda": "Ouganda",
    "Vietnam": "Vietnam",
}


def pays_en_to_fr_smart(pays_en: str) -> str:
    """
    Convertit un pays anglais (TM) en français en gérant les suffixes :
      - "Brazil U17" -> "Brésil U17"
      - "New Caledonia U16/U17" -> "Nouvelle-Calédonie U16/U17"
      - "Hungary Olympic Team" -> "Hongrie - Équipe Olympique"
    Si rien ne matche, renvoie le nom EN tel quel.
    """
    if not pays_en:
        return ""
    if pays_en in EN_TO_FR:
        return EN_TO_FR[pays_en]

    # Suffixe " Olympic Team"
    if pays_en.endswith(" Olympic Team"):
        base = pays_en[: -len(" Olympic Team")].strip()
        base_fr = EN_TO_FR.get(base, base)
        return f"{base_fr} - Équipe Olympique"

    # Suffixe " Uxx" ou " Uxx/Uyy"
    m = re.match(r"^(.*?)( U\d+(?:/U\d+)?)$", pays_en)
    if m:
        base, suffix = m.group(1).strip(), m.group(2)
        base_fr = EN_TO_FR.get(base, base)
        return f"{base_fr}{suffix}"

    return pays_en

# Locks
_lock = threading.Lock()


def _fetch(url: str, timeout: int = 30) -> tuple[str | None, str, int]:
    """Renvoie (html, final_url, status). html=None si erreur. Robust : capte tout."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="replace"), r.url, r.status
    except urllib.error.HTTPError as e:
        return None, url, e.code
    except Exception:
        # URLError, TimeoutError, ConnectionResetError, etc.
        return None, url, 0


def parse_page(html: str, final_url: str) -> dict:
    """Extrait nom, pays_en, type, slug depuis la page TM."""
    out: dict = {"nom": "", "pays_en": "", "type": "", "slug": ""}

    # Type via segment URL
    if "/pokalwettbewerb/" in final_url:
        out["type"] = "cup"
    elif "/wettbewerb/" in final_url:
        out["type"] = "league_or_national"
    # Le slug est le 1er segment du path
    m_slug = re.match(r"https?://[^/]+/([^/]+)/", final_url)
    if m_slug:
        out["slug"] = m_slug.group(1)

    # Nom officiel : <h1 class="data-header__headline-wrapper ...">XXX</h1>
    m_h1 = re.search(
        r'<h1[^>]*class="[^"]*data-header__headline-wrapper[^"]*"[^>]*>(.*?)</h1>',
        html, re.S
    )
    if m_h1:
        txt = re.sub(r"<[^>]+>", " ", m_h1.group(1))
        out["nom"] = re.sub(r"\s+", " ", txt).strip()

    # Pays : 1ère image <img ... src=".../flagge/..." alt="Country">
    m_flag = re.search(
        r'<img[^>]*src="[^"]*/flagge/[^"]*"[^>]*alt="([^"]+)"', html
    )
    if m_flag:
        out["pays_en"] = m_flag.group(1).strip()

    return out


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    PORTAL_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2,
                                     sort_keys=True), encoding="utf-8")


def fetch_one(code: str) -> tuple[str, dict | None]:
    """Worker : fetch + parse pour 1 code. Ne lève jamais."""
    try:
        url = f"{BASE_URL}/wettbewerb/startseite/wettbewerb/{code}"
        html, final_url, status = _fetch(url)
        time.sleep(0.3 + random.random() * 0.4)
        if html is None:
            return code, None
        info = parse_page(html, final_url)
        info["fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        info["status"] = status
        return code, info
    except Exception as e:
        print(f"  [worker error] {code}: {e}")
        return code, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(INPUT_CSV))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0,
                    help="0 = tous les inconnus (défaut)")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch même les codes déjà en cache")
    args = ap.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        print(f"[ERR] Input introuvable : {inp}")
        return 1

    cache = load_cache()
    print(f"[INFO] Cache existant : {len(cache)} codes.")

    # Sélection codes inconnus
    with inp.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    inconnus = [r["code_tm"] for r in rows if r["connue_dans_master"] == "non"]
    print(f"[INFO] Codes inconnus dans {inp.name} : {len(inconnus)}")

    if args.force:
        to_fetch = inconnus
    else:
        to_fetch = [c for c in inconnus if c not in cache]
    if args.limit:
        to_fetch = to_fetch[: args.limit]

    print(f"[INFO] À fetcher : {len(to_fetch)} (workers={args.workers})")

    if to_fetch:
        ok, ko = 0, 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(fetch_one, c): c for c in to_fetch}
            for i, fut in enumerate(as_completed(futs), 1):
                code, info = fut.result()
                if info and info.get("nom"):
                    with _lock:
                        cache[code] = info
                    ok += 1
                    if i <= 10 or i % 25 == 0:
                        print(f"  [{i:>4}/{len(to_fetch)}] {code:8s} -> "
                              f"{info['nom'][:50]:<50s} ({info.get('pays_en') or '?'})")
                else:
                    ko += 1
                    print(f"  [{i:>4}/{len(to_fetch)}] {code:8s} -> ÉCHEC")
                # Sauvegarde intermédiaire toutes les 10
                if i % 10 == 0:
                    save_cache(cache)
        save_cache(cache)
        print(f"\n[INFO] Fetch terminé : {ok} OK / {ko} KO")
    else:
        print("[INFO] Rien à fetcher.")

    # Mise à jour CSV : enrichir les lignes inconnues
    out_rows = []
    n_enriched = 0
    for r in rows:
        code = r["code_tm"]
        if r["connue_dans_master"] == "non" and code in cache:
            info = cache[code]
            r["nom_competition"] = info.get("nom", "")
            pays_en = info.get("pays_en", "")
            r["pays"] = pays_en_to_fr_smart(pays_en)
            ttype = info.get("type", "")
            if ttype == "cup":
                r["type"] = "cup"
            elif ttype == "league_or_national":
                # Heuristique : si nom contient national/qualif/euro/etc.
                r["type"] = "league"
            n_enriched += 1
        out_rows.append(r)

    # Réécrire
    with inp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(out_rows)

    print(f"\n[OK] {n_enriched} lignes enrichies dans {inp}")
    print(f"     Cache total : {len(cache)} codes ({CACHE_PATH.name})")

    # Stats finales
    n_total = len(out_rows)
    n_with_nom = sum(1 for r in out_rows if r["nom_competition"])
    print(f"     Couverture noms : {n_with_nom}/{n_total} "
          f"({100*n_with_nom/n_total:.0f}%)")

    # Lister les pays_en non mappés (pour ajouter à EN_TO_FR plus tard)
    pays_unmapped = set()
    for code, info in cache.items():
        pays_en = info.get("pays_en", "")
        if pays_en and pays_en not in EN_TO_FR:
            pays_unmapped.add(pays_en)
    if pays_unmapped:
        print(f"\n[WARN] Pays anglais non mappés ({len(pays_unmapped)}) : "
              f"{sorted(pays_unmapped)[:15]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
