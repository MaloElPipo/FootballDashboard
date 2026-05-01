"""
Construit le site GitHub Pages (index.html + ZIPs téléchargeables) à partir
des CSV présents dans `live/data/tm_career/` (full) et
`live/data/tm_career_current/` (saison en cours).

Sortie : dossier `gh_pages_build/` contenant :
  - index.html   (page d'accueil avec tableau de tous les championnats)
  - data/{code}_all.zip       (4 CSV : summary, career, matches, competitions_seen)
  - data/{code}_current.zip   (2 CSV : career_current, matches_current)

Le déploiement vers la branche `gh-pages` est fait par GitHub Actions.
"""

from __future__ import annotations

import csv
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_FULL = REPO_ROOT / "live" / "data" / "tm_career"
SRC_CURRENT = REPO_ROOT / "live" / "data" / "tm_career_current"
OUT_DIR = REPO_ROOT / "gh_pages_build"
OUT_DATA = OUT_DIR / "data"

# Mapping pays → emoji drapeau (par code TM ou nom). Cosmétique.
FLAGS = {
    "Allemagne": "🇩🇪", "Espagne": "🇪🇸", "Angleterre": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Italie": "🇮🇹",
    "France": "🇫🇷", "Pays-Bas": "🇳🇱", "Portugal": "🇵🇹", "Belgique": "🇧🇪",
    "Turquie": "🇹🇷", "Grèce": "🇬🇷", "Écosse": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Russie": "🇷🇺",
    "Ukraine": "🇺🇦", "Danemark": "🇩🇰", "Autriche": "🇦🇹", "Suisse": "🇨🇭",
    "Pologne": "🇵🇱", "Suède": "🇸🇪", "Norvège": "🇳🇴", "Tchéquie": "🇨🇿",
    "Croatie": "🇭🇷", "Serbie": "🇷🇸", "Roumanie": "🇷🇴", "Hongrie": "🇭🇺",
    "Islande": "🇮🇸", "Irlande": "🇮🇪", "Bulgarie": "🇧🇬", "Chypre": "🇨🇾",
    "Lituanie": "🇱🇹", "Lettonie": "🇱🇻", "Estonie": "🇪🇪", "Albanie": "🇦🇱",
    "Azerbaïdjan": "🇦🇿", "Bosnie-Herzégovine": "🇧🇦", "Malte": "🇲🇹",
    "Finlande": "🇫🇮", "Géorgie": "🇬🇪", "Irlande du Nord": "🏴",
    "Israël": "🇮🇱", "Luxembourg": "🇱🇺", "Pays de Galles": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "Slovaquie": "🇸🇰", "Slovénie": "🇸🇮", "Brésil": "🇧🇷", "Argentine": "🇦🇷",
    "États-Unis": "🇺🇸", "Mexique": "🇲🇽", "Colombie": "🇨🇴", "Paraguay": "🇵🇾",
    "Chili": "🇨🇱", "Équateur": "🇪🇨", "Arabie Saoudite": "🇸🇦", "Japon": "🇯🇵",
    "Corée du Sud": "🇰🇷", "Australie": "🇦🇺", "Chine": "🇨🇳", "Maroc": "🇲🇦",
    "Algérie": "🇩🇿", "Afrique du Sud": "🇿🇦",
}


def get_leagues_config() -> list[dict]:
    """Charge la config maître via import dynamique."""
    sys.path.insert(0, str(REPO_ROOT))
    from live.leagues_master import LEAGUES, NATIONAL_TEAMS  # type: ignore
    out = []
    for l in LEAGUES:
        out.append({**l, "kind": "league"})
    for t in NATIONAL_TEAMS:
        out.append({
            **t, "kind": "national_team", "tier": 0,
            "slug": t["code_tm"].lower(), "pays": t["nom"],
        })
    return out


def file_mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as f:
        return sum(1 for _ in f) - 1  # -1 pour le header


def build_zip(zip_path: Path, files: list[Path]) -> int:
    """Crée un ZIP avec compression. Retourne taille en octets."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for fp in files:
            if fp.exists():
                zf.write(fp, arcname=fp.name)
    return zip_path.stat().st_size


def build_dataset_assets(target: dict) -> dict:
    """Pour un championnat ou une sélection, construit les ZIPs disponibles
    et retourne les méta-données pour la page."""
    code = target["code_tm"]
    code_l = code.lower()

    summary_p = SRC_FULL / f"{code_l}_summary.csv"
    career_p = SRC_FULL / f"{code_l}_career.csv"
    matches_p = SRC_FULL / f"{code_l}_matches.csv"
    comps_p = SRC_FULL / f"{code_l}_competitions_seen.csv"

    career_cur_p = SRC_CURRENT / f"{code_l}_career.csv"
    matches_cur_p = SRC_CURRENT / f"{code_l}_matches.csv"

    has_full = summary_p.exists() and career_p.exists()
    has_current = career_cur_p.exists()

    meta: dict = {
        **target,
        "has_full": has_full,
        "has_current": has_current,
        "n_players": csv_row_count(summary_p) if has_full else 0,
        "n_career_rows": csv_row_count(career_p) if has_full else 0,
        "n_matches_rows": csv_row_count(matches_p) if has_full else 0,
        "all_zip_size": 0,
        "current_zip_size": 0,
        "last_update": None,
    }

    if has_full:
        all_zip = OUT_DATA / f"{code_l}_all.zip"
        meta["all_zip_size"] = build_zip(all_zip, [summary_p, career_p, matches_p, comps_p])
        meta["all_zip_path"] = f"data/{all_zip.name}"
        mt = file_mtime(career_p)
        if mt:
            meta["last_update"] = mt

    if has_current:
        cur_zip = OUT_DATA / f"{code_l}_current.zip"
        meta["current_zip_size"] = build_zip(cur_zip, [career_cur_p, matches_cur_p])
        meta["current_zip_path"] = f"data/{cur_zip.name}"

    return meta


def fmt_bytes(n: int) -> str:
    if n == 0:
        return ""
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} Ko"
    return f"{n / (1024 * 1024):.2f} Mo"


def fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def freshness_badge(dt: datetime | None) -> tuple[str, str]:
    """Retourne (label, classe CSS) selon la fraîcheur des données."""
    if dt is None:
        return ("Jamais", "badge stale")
    age_days = (datetime.now(tz=timezone.utc) - dt).days
    if age_days <= 8:
        return (f"{age_days} j", "badge fresh")
    if age_days <= 30:
        return (f"{age_days} j", "badge medium")
    return (f"{age_days} j", "badge old")


def render_html(metas: list[dict]) -> str:
    """Génère index.html à partir des métadonnées de chaque dataset."""
    now = datetime.now(tz=timezone.utc)

    # Group par région puis par tier
    groups: dict[str, list[dict]] = {}
    for m in metas:
        if m["kind"] == "national_team":
            key = f"Sélections nationales — Mondial 2026 ({m['region']})"
        else:
            key = f"{m['region']} — {'D' + str(m['tier']) if m['tier'] else 'Sélection'}"
        groups.setdefault(key, []).append(m)

    n_total = len(metas)
    n_with_data = sum(1 for m in metas if m["has_full"])
    total_size = sum(m["all_zip_size"] + m["current_zip_size"] for m in metas)

    sections_html = []
    for group_name in sorted(groups.keys()):
        rows = groups[group_name]
        rows_html = []
        for m in sorted(rows, key=lambda x: (-x["has_full"], x["pays"], x["nom"] if "nom" in x else "")):
            flag = FLAGS.get(m["pays"], "🏳️")
            label = m.get("nom") or m.get("pays")
            country = m.get("pays", "")
            tier_txt = "" if not m.get("tier") else f"D{m['tier']}"
            badge_text, badge_class = freshness_badge(m.get("last_update"))
            update_str = fmt_date(m.get("last_update"))

            n_players = m["n_players"]
            stats_str = (
                f"{n_players} joueurs · {m['n_career_rows']} lignes career · "
                f"{m['n_matches_rows']} matchs"
                if m["has_full"] else "<em>Pas encore scrapé</em>"
            )

            if m["has_full"]:
                btn_all = (
                    f'<a class="btn btn-primary" href="{m["all_zip_path"]}" download>'
                    f'⬇️ Tout télécharger '
                    f'<span class="size">({fmt_bytes(m["all_zip_size"])})</span>'
                    f'</a>'
                )
            else:
                btn_all = '<span class="btn btn-disabled">⏳ À venir</span>'

            if m["has_current"]:
                btn_cur = (
                    f'<a class="btn btn-secondary" href="{m["current_zip_path"]}" download>'
                    f'🔄 Mise à jour saison '
                    f'<span class="size">({fmt_bytes(m["current_zip_size"])})</span>'
                    f'</a>'
                )
            else:
                btn_cur = '<span class="btn btn-disabled">—</span>'

            rows_html.append(f"""
                <tr>
                  <td class="cell-name">
                    <span class="flag">{flag}</span>
                    <span class="league-name">{label}</span>
                    <span class="country-tier">{country}{(' · ' + tier_txt) if tier_txt else ''}</span>
                  </td>
                  <td class="cell-stats">{stats_str}</td>
                  <td class="cell-update">
                    <div class="update-date">{update_str}</div>
                    <span class="{badge_class}">{badge_text}</span>
                  </td>
                  <td class="cell-actions">
                    {btn_all}
                    {btn_cur}
                  </td>
                </tr>
            """)

        sections_html.append(f"""
          <section>
            <h2>{group_name} <span class="count">({len(rows)})</span></h2>
            <table>
              <thead>
                <tr>
                  <th>Championnat</th>
                  <th>Contenu</th>
                  <th>Dernière mise à jour</th>
                  <th>Téléchargement</th>
                </tr>
              </thead>
              <tbody>
                {''.join(rows_html)}
              </tbody>
            </table>
          </section>
        """)

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Football Career Data — Portail CSV</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0; padding: 0; background: #f7f8fa; color: #1a1a1a;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
    header {{ background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); color: white; padding: 40px 24px; }}
    header h1 {{ margin: 0 0 8px 0; font-size: 28px; }}
    header p {{ margin: 4px 0; opacity: 0.9; font-size: 14px; }}
    .stats-bar {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px; margin: 24px 0;
    }}
    .stat-card {{ background: white; padding: 16px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
    .stat-card .num {{ font-size: 24px; font-weight: 700; color: #1e3a8a; }}
    .stat-card .lbl {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 4px; }}
    section {{ background: white; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin: 16px 0; padding: 20px 24px; }}
    section h2 {{ margin: 0 0 16px 0; font-size: 18px; color: #1e3a8a; padding-bottom: 12px; border-bottom: 2px solid #e5e7eb; }}
    section h2 .count {{ color: #999; font-weight: 400; font-size: 14px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{ text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #666; padding: 8px 12px; border-bottom: 1px solid #e5e7eb; }}
    td {{ padding: 14px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; font-size: 14px; }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover {{ background: #fafbfc; }}
    .cell-name {{ display: flex; flex-direction: column; gap: 2px; }}
    .flag {{ font-size: 20px; margin-right: 6px; display: inline; }}
    .league-name {{ font-weight: 600; color: #111; }}
    .country-tier {{ font-size: 12px; color: #888; }}
    .cell-stats {{ font-size: 13px; color: #555; }}
    .update-date {{ font-size: 12px; color: #555; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; margin-top: 4px; }}
    .badge.fresh {{ background: #dcfce7; color: #166534; }}
    .badge.medium {{ background: #fef3c7; color: #854d0e; }}
    .badge.old {{ background: #fee2e2; color: #991b1b; }}
    .badge.stale {{ background: #f3f4f6; color: #6b7280; }}
    .cell-actions {{ display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }}
    .btn {{
      display: inline-block; padding: 6px 12px; border-radius: 6px;
      font-size: 12px; font-weight: 500; text-decoration: none; white-space: nowrap;
    }}
    .btn-primary {{ background: #1e3a8a; color: white; }}
    .btn-primary:hover {{ background: #1e40af; }}
    .btn-secondary {{ background: #e5e7eb; color: #1e3a8a; }}
    .btn-secondary:hover {{ background: #d1d5db; }}
    .btn-disabled {{ background: #f3f4f6; color: #9ca3af; cursor: not-allowed; }}
    .size {{ opacity: 0.7; font-size: 11px; }}
    footer {{ text-align: center; padding: 24px; color: #888; font-size: 13px; }}
    footer a {{ color: #1e3a8a; }}
  </style>
</head>
<body>
  <header>
    <div class="container">
      <h1>⚽ Football Career Data — Portail CSV</h1>
      <p>Données de carrière des joueurs actifs des championnats trackés par <strong>V-Pin FR</strong>.</p>
      <p>Source : Transfermarkt (endpoint ceapi). Mise à jour hebdomadaire automatique tous les <strong>mardis matin</strong>.</p>
    </div>
  </header>

  <div class="container">
    <div class="stats-bar">
      <div class="stat-card"><div class="num">{n_with_data}/{n_total}</div><div class="lbl">Datasets disponibles</div></div>
      <div class="stat-card"><div class="num">{sum(m['n_players'] for m in metas)}</div><div class="lbl">Joueurs trackés</div></div>
      <div class="stat-card"><div class="num">{sum(m['n_career_rows'] for m in metas)}</div><div class="lbl">Lignes career totales</div></div>
      <div class="stat-card"><div class="num">{fmt_bytes(total_size)}</div><div class="lbl">Volume total</div></div>
    </div>

    <section style="background: #fff7ed; border-left: 4px solid #f97316;">
      <h2 style="border: none; padding: 0; color: #9a3412;">📖 Comment ça marche ?</h2>
      <p style="margin: 8px 0; font-size: 14px; line-height: 1.6;">
        Pour chaque championnat, deux téléchargements sont proposés :
      </p>
      <ul style="font-size: 14px; line-height: 1.7;">
        <li><strong>⬇️ Tout télécharger</strong> — ZIP des 4 CSV complets : <code>summary</code> (1 ligne/joueur, totaux carrière), <code>career</code> (1 ligne par saison × compétition × club), <code>matches</code> (10 derniers matchs ou 3 derniers mois), <code>competitions_seen</code> (référentiel des codes compétitions rencontrés). Idéal pour une analyse complète.</li>
        <li><strong>🔄 Mise à jour saison</strong> — ZIP léger contenant uniquement les lignes de la <strong>saison en cours</strong> (career + matches). À télécharger chaque semaine pour suivre l'actualité sans tout retéléverser.</li>
      </ul>
    </section>

    {''.join(sections_html)}
  </div>

  <footer>
    Page générée le {now.strftime("%Y-%m-%d %H:%M UTC")} ·
    <a href="https://github.com/MaloElPipo/FootballDashboard">Code source</a>
  </footer>
</body>
</html>
"""
    return html


def main() -> int:
    print("[INFO] Préparation du dossier de sortie")
    if OUT_DIR.exists():
        # Nettoyage des anciens fichiers (mais on garde le dossier pour gh-pages)
        for p in OUT_DIR.rglob("*"):
            if p.is_file():
                p.unlink()
    OUT_DATA.mkdir(parents=True, exist_ok=True)

    print("[INFO] Chargement de la config maître")
    targets = get_leagues_config()
    print(f"       {len(targets)} datasets déclarés")

    print("[INFO] Construction des ZIPs et collecte des métadonnées")
    metas = []
    for t in targets:
        meta = build_dataset_assets(t)
        metas.append(meta)
        if meta["has_full"]:
            sizes = (
                f"all={fmt_bytes(meta['all_zip_size']):>10}  "
                f"current={fmt_bytes(meta['current_zip_size']):>10}"
            )
            print(f"  [OK]  {t['code_tm']:6s} {sizes}")

    print("[INFO] Génération du HTML")
    html = render_html(metas)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")

    # Fichier .nojekyll pour s'assurer que GitHub Pages traite le HTML brut
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")

    n_ok = sum(1 for m in metas if m["has_full"])
    print()
    print(f"[FIN] {n_ok}/{len(targets)} datasets avec données")
    print(f"      Sortie : {OUT_DIR}")
    print(f"      Page : {OUT_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
