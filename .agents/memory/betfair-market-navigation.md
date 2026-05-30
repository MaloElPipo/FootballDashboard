---
name: Betfair Exchange — scraping des marchés secondaires
description: Pourquoi le scraper Betfair doit naviguer marché-par-marché pour BTTS/O-U, et la limite de navigations.
---

# Betfair Exchange — page "plus" ne rend qu'un marché à la fois

La page `https://www.betfair.com/exchange/plus/...` (page match) ne rend plus
**que le marché Match Odds (1X2)** avec ses cotes back/lay. Tous les autres
marchés (Over/Under, Both Teams To Score, O/U par équipe, etc.) ne sont qu'une
**liste de liens de navigation** : on a les noms, pas les cotes. Chaque marché a
sa propre URL `…/exchange/plus/football/market/<id>`, et l'ancre `<a>` du nom de
marché porte `href="football/market/<id>"`.

**Conséquence scraping :** pour récupérer O/U 2.5, BTTS, O/U 0.5, il faut, après
avoir parsé le 1X2 sur la page match, lire la carte nom→href (anchors contenant
`/market/`), puis **naviguer vers l'URL de chaque marché** et parser le bloc
rendu (ancré sur « Back all », puis nom de sélection + 3 back + 3 lay).

**Why:** un parseur qui lit seulement `document.body.innerText` de la page match
ne trouvera jamais les cotes des marchés secondaires (seulement leurs noms) → ils
remontent vides alors que le 1X2 marche.

**How to apply / pièges :**
- Limiter le nombre de navigations successives : au-delà de ~5-6 chargements
  rapides, Betfair ferme la page (« Target page, context or browser has been
  closed »). On se limite donc aux marchés réellement consommés.
- Côté `football-dashboard`, la section Garantie 2+ n'utilise QUE 1X2 +
  O/U 2.5 + BTTS (getters `get_1x2_mids` / `get_ou25_both_mids` /
  `get_btts_both_mids`). Les marchés O/U 0.5 par équipe ne sont consommés nulle
  part → ne pas les scraper (latence + risque de fermeture pour rien).
- Matcher les marchés par libellé **normalisé** (minuscules, sans ponctuation),
  pas par égalité stricte : Betfair fait varier casse/ponctuation.
- Reproduction locale possible en DEV : les secrets `BETFAIR_PROXY_URL` /
  `WEBSHARE_PROXY_URL` sont configurés ; sans proxy, `_parse_proxy()` renvoie
  None et le scrape échoue d'emblée.
