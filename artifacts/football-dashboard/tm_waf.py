"""
Contournement du challenge AWS WAF Bot Control de Transfermarkt.

Contexte
--------
Transfermarkt place son site derrière AWS WAF (CloudFront). Toute requête
HTTP « nue » (urllib / requests / cloudscraper) depuis une IP datacenter
(GitHub Actions, Replit) reçoit une réponse `202` avec le header
`x-amzn-waf-action: challenge` et un corps vide : le WAF exige la résolution
d'un challenge JavaScript qu'aucun client HTTP simple ne sait exécuter.

Solution
--------
Un vrai navigateur (Chromium piloté par Playwright) charge la home TM, exécute
le challenge JS, et obtient un cookie `aws-waf-token`. Ce cookie, réinjecté
dans les requêtes HTTP classiques (rapides), débloque *tous* les endpoints TM
(pages HTML `kader`/`leistungsdaten` et API `ceapi`) tant qu'il reste valide.

Architecture retenue : **1 navigateur au démarrage → token → puis HTTP rapide.**
On ne pilote donc PAS le navigateur pour chaque requête (trop lent) ; on ne
l'utilise que pour (ré)obtenir le cookie.

Le module est thread-safe : le token est partagé entre workers et son
(ré)obtention est sérialisée par un verrou.

Variables d'environnement
-------------------------
- ``TM_CHROMIUM_PATH`` (optionnel) : chemin explicite vers un binaire Chromium.
  Sur Replit, pointer vers le Chromium Nix. Sur GitHub Actions (ubuntu-latest),
  laisser vide : Playwright utilise son propre Chromium installé via
  ``playwright install chromium``.
- ``TM_WAF_DISABLE`` (optionnel) : si ``1``, désactive complètement le
  mécanisme (utile pour un runner résidentiel où le WAF ne bloque pas).
"""

from __future__ import annotations

import os
import shutil
import threading
import time

# Home TM à charger pour déclencher la résolution du challenge JS.
_TM_HOME = "https://www.transfermarkt.com/"

# User-Agent cohérent entre le navigateur (obtention du cookie) et les requêtes
# HTTP (réutilisation du cookie). Le WAF lie le token à l'empreinte du client :
# un UA divergent invaliderait le cookie.
WAF_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

_lock = threading.Lock()
_token: str | None = None
_disabled = os.environ.get("TM_WAF_DISABLE", "") == "1"

# Abandon après N échecs consécutifs de lancement navigateur, pour éviter que
# des centaines de requêtes ne re-tentent chacune un lancement Chromium (~10s)
# lorsque Playwright est cassé — ce qui saturerait le budget temps de la ligue.
# Le compteur est par-processus : chaque ligue est une invocation séparée, donc
# une ligue « abandonnée » n'empêche pas la suivante de retenter à neuf.
_MAX_CONSECUTIVE_FAILURES = 3
_consecutive_failures = 0
_gave_up = False


def _resolve_chromium_path() -> str | None:
    """Retourne un chemin Chromium explicite, ou None pour laisser Playwright choisir.

    Priorité :
      1. ``TM_CHROMIUM_PATH`` (override explicite).
      2. None si Playwright a son propre Chromium (cas GitHub Actions).
         On tente d'abord None au lancement ; le fallback ci-dessous n'est
         utilisé qu'en cas d'échec.
    """
    explicit = os.environ.get("TM_CHROMIUM_PATH", "").strip()
    if explicit:
        return explicit
    return None


def _launch_and_get_token(timeout_ms: int = 45000, settle_ms: int = 6000) -> str | None:
    """Lance Chromium, charge la home TM, résout le challenge, extrait le token.

    Retourne la valeur du cookie ``aws-waf-token`` ou None en cas d'échec.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("   ! tm_waf: playwright non installé — impossible d'obtenir le token WAF",
              flush=True)
        return None

    launch_args = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]

    # Candidats de binaire : d'abord le chemin résolu (ou None = défaut Playwright),
    # puis un Chromium système trouvé sur le PATH en dernier recours.
    candidates: list[str | None] = []
    resolved = _resolve_chromium_path()
    candidates.append(resolved)
    if resolved is None:
        sys_chromium = shutil.which("chromium") or shutil.which("chromium-browser")
        if sys_chromium:
            candidates.append(sys_chromium)

    last_err: str | None = None
    for exe in candidates:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=exe,  # None → Chromium fourni par Playwright
                    headless=True,
                    args=launch_args,
                )
                try:
                    ctx = browser.new_context(
                        user_agent=WAF_USER_AGENT,
                        locale="fr-FR",
                        viewport={"width": 1366, "height": 768},
                    )
                    page = ctx.new_page()
                    page.goto(_TM_HOME, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(settle_ms)  # laisse le challenge JS s'exécuter
                    for c in ctx.cookies():
                        if c["name"] == "aws-waf-token":
                            return c["value"]
                    last_err = "cookie aws-waf-token absent après chargement"
                finally:
                    browser.close()
        except Exception as e:  # noqa: BLE001 — on veut essayer le candidat suivant
            last_err = f"{type(e).__name__}: {e}"
            continue

    print(f"   ! tm_waf: échec obtention token WAF ({last_err})", flush=True)
    return None


def get_waf_token(force_refresh: bool = False, stale: str | None = None) -> str | None:
    """Retourne le token WAF courant, en l'obtenant/rafraîchissant si besoin.

    Thread-safe : l'obtention est sérialisée par ``_lock``.

    - ``force_refresh`` : force un nouveau lancement navigateur (challenge détecté).
    - ``stale`` : token que l'appelant vient d'utiliser sans succès. Si, une fois
      le verrou acquis, ``_token`` a déjà changé (un autre worker a rafraîchi),
      on renvoie le token courant SANS relancer un navigateur — évite le
      « thundering herd » où N workers relancent chacun Chromium simultanément.
    """
    global _token, _consecutive_failures, _gave_up
    if _disabled:
        return None
    if _token is not None and not force_refresh:
        return _token
    with _lock:
        # Un thread concurrent a peut-être déjà (ra)fraîchi pendant l'attente.
        if _token is not None and not force_refresh:
            return _token
        if force_refresh and stale is not None and _token != stale:
            # Un autre worker a déjà remplacé le token périmé : on l'utilise.
            return _token
        if _gave_up:
            # Playwright durablement cassé sur ce processus : on n'insiste plus.
            return _token
        token_before = _token
        new = _launch_and_get_token()
        if new is not None:
            _token = new
            _consecutive_failures = 0
        else:
            _consecutive_failures += 1
            if _consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                _gave_up = True
                print(
                    f"   ! tm_waf: abandon après {_consecutive_failures} échecs "
                    f"consécutifs de lancement navigateur",
                    flush=True,
                )
            # Échec : on garde l'ancien token s'il existe (mieux que rien).
            if force_refresh and token_before is not None:
                _token = token_before
        return _token


def cookie_header(existing: str | None = None) -> str | None:
    """Construit la valeur d'un header ``Cookie`` incluant le token WAF.

    ``existing`` : cookies déjà présents à préserver (rare ici). Retourne None
    si aucun token n'est disponible (mécanisme désactivé ou échec).
    """
    token = get_waf_token()
    if not token:
        return existing
    waf = f"aws-waf-token={token}"
    if existing:
        return f"{existing}; {waf}"
    return waf


def is_challenge_response(status: int | None, body_len: int, waf_header: str | None) -> bool:
    """Heuristique : la réponse est-elle un challenge WAF (à retenter après refresh) ?

    Un challenge se manifeste par ``x-amzn-waf-action: challenge`` et/ou un
    statut 202 avec un corps minuscule (page de challenge ~2.4KB ou vide).
    """
    if waf_header and "challenge" in waf_header.lower():
        return True
    if status == 202 and body_len < 5000:
        return True
    return False


def warm_up() -> bool:
    """Pré-obtient le token au démarrage. Retourne True si un token est dispo."""
    if _disabled:
        print("   • tm_waf désactivé (TM_WAF_DISABLE=1)", flush=True)
        return False
    t0 = time.time()
    tok = get_waf_token()
    if tok:
        print(f"   ✓ tm_waf: token WAF obtenu en {time.time() - t0:.1f}s", flush=True)
        return True
    print("   ! tm_waf: aucun token WAF disponible — les requêtes risquent d'être bloquées",
          flush=True)
    return False
