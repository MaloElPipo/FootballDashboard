"""
Script de pre-population du fichier squads_static.json
Exécuté une seule fois pour remplir la base statique.
"""
import sys, json, time, os

STATIC_FILE = os.path.join(os.path.dirname(__file__), 'squads_static.json')

from squad_scraper import build_squad
from nations_data import get_all_nations

try:
    with open(STATIC_FILE) as f:
        static_db = json.load(f)
    print(f"Fichier existant: {len(static_db)} nations", flush=True)
except Exception:
    static_db = {}

nations = get_all_nations()

for i, nation in enumerate(nations):
    code = nation['code']
    name = nation['fr']
    existing = static_db.get(code, {}).get('players', [])
    if existing:
        print(f"[{i+1}/{len(nations)}] {name} — déjà OK ({len(existing)} joueurs)", flush=True)
        continue
    if not nation.get('tm_id'):
        print(f"[{i+1}/{len(nations)}] {name} — pas d'ID TM", flush=True)
        static_db[code] = {'players': [], 'fr': name}
        continue
    
    print(f"[{i+1}/{len(nations)}] Scraping {name}...", flush=True)
    try:
        squad = build_squad(nation, n_matches=5)
        static_db[code] = {
            'players': squad,
            'fr': name,
            'conf': nation.get('conf',''),
            'scraped_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'n_players': len(squad),
        }
        total_val = sum(p.get('market_value_eur',0) for p in squad)
        print(f"  → {len(squad)} joueurs, {total_val//1_000_000}M €", flush=True)
    except Exception as e:
        print(f"  → ERREUR: {e}", flush=True)
        static_db[code] = {'players': [], 'fr': name, 'error': str(e)}
    
    with open(STATIC_FILE, 'w', encoding='utf-8') as f:
        json.dump(static_db, f, ensure_ascii=False, indent=2)

print(f"\nTerminé! {len(static_db)} nations")
