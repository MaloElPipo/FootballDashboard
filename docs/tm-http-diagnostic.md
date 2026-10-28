# Diagnostic HTTP Transfermarkt — protocole limité

## Extension d'endurance autorisée le 27 octobre 2026

L'utilisateur a explicitement autorisé trois fenêtres, **pas une collecte complète**.
Chaque fenêtre est lancée manuellement ; aucun cron ni relance automatique.
Les fenêtres 2 et 3 sont conditionnées au succès de la précédente, données
inchangées, et à au moins six heures depuis sa fin. Un arrêt annule les
fenêtres restantes : ne pas recommencer sous un autre numéro ou runner.

| Limite | Par fenêtre | Ensemble autorisé |
| --- | --- | --- |
| Joueurs / GET carrière | 120 | 360 |
| Requêtes navigateur | 40 | 120 |
| Total réseau initié maximum | 160 | 480 |
| Durée carrière maximum | 30 min | 90 min |
| Limite du job GitHub, installation comprise | 40 min | 120 min |

Un worker, 10 secondes entre GET, y compris aux paliers 24/60/120.
La durée minimale de pauses pour 120 GET est 19 min 50 s ; les latences
s'ajoutent. Un GET déjà lancé conserve son timeout de 30 secondes.
L'échantillon contient dix identifiants régulièrement espacés dans la liste
triée de chaque ligue, saison maximale, dédupliqués entre ligues.
Les fenêtres peuvent reprendre les mêmes joueurs : 360 GET ne signifie
donc **pas 360 joueurs uniques**. Les sources et sélections sont archivées.
Chaque fenêtre ouvre une seule session ; ce protocole compare plusieurs
horaires, mais ne mesure pas la survie d'une même session pendant douze heures.

Les garde-fous historiques restent actifs : arrêt immédiat au premier
échec, sans retry, sans rafraîchissement de session, sans export ni publication.
Une empreinte de tous les fichiers `live/data` est comparée avant/après.
Les rapports comportent les dates UTC, numéro de fenêtre, limites, nombre
de tentatives/succès, durées, classification et contrôle des données.

### Exécution et preuve

- Sonde historique inchangée : `python tm_http_diagnostic.py`.
- Première fenêtre : `python tm_http_diagnostic.py --window 1`.
- Fenêtre suivante : `python tm_http_diagnostic.py --window 2 --previous-report /chemin/rapport-precedent.json`
  (puis 3). `RUNNER_TEMP` doit désigner un dossier temporaire existant.
- Dans Actions, sélectionner `window` et, pour 2/3, le `previous_run` ;
  son artifact est téléchargé en lecture seule. Le script refuse une preuve
  absente, un échec précédent ou un délai inférieur à six heures.
- Si les effectifs manquent dans le checkout, `--source-root` permet de lire
  une copie temporaire issue d'un commit identifié du dépôt, sans restaurer
  ni modifier les CSV de production. Une erreur de prévalidation avant
  toute ouverture navigateur ne consomme aucune requête Transfermarkt.
- L'opérateur tient le bilan des trois fenêtres et interdit tout doublon :
  le contrôle du rapport précédent n'est pas un registre global anti-rejeu.
- Conserver le JSON après chaque fenêtre, même interrompue, et consigner
  séparément les fenêtres non exécutées. Ne jamais présenter le budget
  autorisé comme un volume effectivement atteint.

La comparaison des horaires n'est possible que si les fenêtres précédentes
réussissent. Un arrêt précoce est un résultat du protocole, **pas une
validation d'endurance**. Aucun succès ici ne justifie à lui seul onze
championnats complets ou trois workers.

### Résultats de l'extension

Le 28 octobre 2026, l'utilisateur a explicitement autorisé d'avancer la
troisième fenêtre, sans attendre les six heures initiales. L'option
`--authorized-early-third-window` ne s'applique qu'à la fenêtre 3, conserve
un minimum de quatre heures et ne contourne aucun contrôle de réussite
précédente. L'intervalle réellement atteint est enregistré dans son rapport.
Le rappel de lancement à six heures a été annulé pour éviter un doublon.
Les budgets de requêtes, pauses et durées restent inchangés.

| Fenêtre | Début / fin UTC | GET carrière réussis / tentés | Durée carrière avec pauses | Bootstrap | Données |
| --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-27 19:25:21 / 19:46:03 | 120 / 120 | 1 226,644 s (20 min 26,6 s) | 8 requêtes, 13,742 s | Inchangées |
| 2 | 2026-10-28 01:46:13 / 02:07:31 | 120 / 120 | 1 224,620 s (20 min 24,6 s) | 8 requêtes, 18,420 s | Inchangées |
| 3 | 2026-10-28 06:23:21 / 06:44:07 | 120 / 120 | 1 226,609 s (20 min 26,6 s) | 8 requêtes, 16,822 s | Inchangées |

Première fenêtre exécutée sur le runner Replit, **pas GitHub Actions** :
HTTP 200 pour les 120 GET, paliers 24/60/120 atteints, aucun déclenchement
du circuit. Latence GET moyenne 0,305 s, maximale 1,385 s.
Bootstrap : 1 × HTTP 202, 7 × HTTP 200, 79 ressources exclues.
Volume effectivement atteint après trois fenêtres : **384 requêtes réseau
initiées**, dont 360 GET carrière, et non les 480 requêtes du budget total.
Il s'agit des **mêmes 120 joueurs uniques** à chaque fenêtre, sur 12 ligues.
Durée cumulée des GET avec pauses : 3 677,873 secondes (61 min 17,9 s),
réparties sur trois sessions distinctes, pas une heure continue.

Preuve : [rapport JSON fenêtre 1](evidence/tm-endurance-window-1.json),
SHA-256 `0c90ea2453ba0108e9428e64fad153d521d54dc2b164580e861380fbf1b80f05`.
Les effectifs proviennent du commit public
`0310737be965236467b9c502936322521d14fcf1`, copiés dans un répertoire
temporaire, avec leurs empreintes dans le rapport. Une première
prévalidation locale avait détecté des CSV manquants : zéro requête
Transfermarkt, aucune ouverture navigateur. Aucun CSV local n'a été restauré.

Deuxième fenêtre sur le même runner Replit : 120 HTTP 200, aucun déclenchement
du circuit, mêmes paliers franchis. Latence GET moyenne 0,288 s, maximale
1,597 s. Bootstrap : 1 × HTTP 202, 7 × HTTP 200, 79 ressources exclues.
Le début intervient plus de six heures après la fin de la première.
Preuve : [rapport JSON fenêtre 2](evidence/tm-endurance-window-2.json),
SHA-256 `b58537479cfeff4d0e47b38430b1ec8558b467d586d02be04a2079aa8eb9c94e`.

Troisième fenêtre dans l'environnement Replit après son redémarrage :
120 HTTP 200, aucun déclenchement du circuit, mêmes paliers franchis.
Latence GET moyenne 0,305 s, maximale 1,760 s.
Bootstrap : 1 × HTTP 202, 7 × HTTP 200, 79 ressources exclues.
Intervalle réel depuis la fin de la deuxième : **15 350,645 s
(4 h 15 min 50,6 s)**, raccourci sur autorisation explicite.
L'identité d'IP n'a pas été mesurée ; ne pas supposer qu'elle a survécu au
redémarrage. Les sources temporaires ont été récupérées depuis le même
commit, puis vérifiées contre les empreintes du rapport précédent.
Preuve : [rapport JSON fenêtre 3](evidence/tm-endurance-window-3.json),
SHA-256 `4ca3aed45c1ef13fec1c34a9f06b3141bd823e6d192c8e39d1105d30c3b295f1`.

**Conclusion :** protocole borné terminé, accès séquentiel réussi pendant
environ vingt minutes à trois horaires distincts. CSV inchangés pour les
trois fenêtres ; aucune construction ni publication du portail.
Les 15 tests hors réseau du diagnostic passent, dont budget 120,
espacement, refus HTTP et autorisation anticipée limitée à la fenêtre 3.
L'endurance sur onze championnats complets, des milliers de joueurs uniques,
plusieurs heures continues, cinq workers ou un runner GitHub reste
**non démontrée**. Aucune collecte intégrale n'est validée.
L'enquête complémentaire et les corrections recommandées figurent dans
[le bilan de fiabilité](tm-collection-reliability-investigation.md).

## Résultat observé le 27 octobre 2026

**36/36 carrières accessibles**, HTTP 200 et structure valide, sur 12 championnats.
Les paliers 6, 18 et 36 ont tous été franchis dans la même session.

| Mesure | Observation |
| --- | --- |
| Initialisation navigateur | 8 requêtes émises ; 79 ressources exclues |
| HTTP initialisation | 1 × 202, 7 × 200 |
| Durée initialisation | 8,298 s |
| GET carrière | 36 × HTTP 200 |
| Durée carrière, pauses comprises | 234,654 s (3 min 55 s) |
| Durée moyenne / maximale par GET carrière | 0,268 s / 0,490 s |
| Déclenchements du circuit pendant les GET carrière | 0 |
| Vérification des données inchangées | Réussie |
| Publication du portail | Aucune |

Preuve : [exécution GitHub Actions 40557578933](https://github.com/MaloElPipo/FootballDashboard/actions/runs/40557578933),
commit testé `28fe8695c159281126c98c6ec0cbe0a9871de9cb`,
branche isolée `diagnostic/tm-http-bounded-20261027-180552`.
Le rapport `tm-http-diagnostic.json` de l'artifact homonyme contient les durées
individuelles et les empreintes des CSV source ; son SHA-256 est
`102ed27b90cfe9ed6b7cafca6665d3946dadcf74f98b32885eaceb4b9eaea177`.
Aucun changement de `main` n'a été effectué par l'expérience.

Échantillon réellement testé (saison source 2026 partout) :

| Championnat | Identifiants des trois joueurs |
| --- | --- |
| a1 | 59032, 695225, 1533305 |
| l1 | 7161, 569387, 1497653 |
| alb1 | 58570, 881272, 1612778 |
| alg1 | 56809, 861236, 1603746 |
| arg1 | 7966, 816843, 1533085 |
| aus1 | 44068, 1077355, 1603333 |
| az1 | 32928, 637808, 1581730 |
| be1 | 38978, 794749, 1577556 |
| gb1 | 34130, 543499, 1421433 |
| fr1 | 35047, 745200, 1524445 |
| bos1 | 46346, 689217, 1478286 |
| bra1 | 10471, 649184, 1568045 |

Deux essais préparatoires sont distingués du résultat :

1. [40556749383](https://github.com/MaloElPipo/FootballDashboard/actions/runs/40556749383) :
   arrêt avant tout réseau Transfermarkt car `al1`, `bg1` et `bh1` étaient vides.
   Remplacement explicite par `l1`, `gb1`, `fr1`, sans repli silencieux.
2. [40557151851](https://github.com/MaloElPipo/FootballDashboard/actions/runs/40557151851) :
   plafond navigateur de 40 requêtes atteint (1 × 202, 39 × 200) en 2,708 s,
   un déclenchement d'arrêt, **zéro GET carrière**. Ce n'est pas un refus HTTP.
   Les ressources non nécessaires ont ensuite été exclues, sans relever le budget.

Les trois exécutions ont réussi le contrôle d'absence de modification des données.
Le dernier job a passé les 18 tests de récupération/diagnostic hors réseau ;
les 4 tests locaux supplémentaires de protection des exports passent également.
Les arrêts CAPTCHA/403/405/429, erreurs de transport et blocage tardif ont été
validés par simulations hors réseau, **pas provoqués sur le service réel**.

**Conclusion :** l'accès fonctionne pour ce petit échantillon, séquentiellement,
pendant environ quatre minutes. L'endurance sur des milliers de joueurs,
plusieurs heures ou trois workers reste non démontrée. Aucune relance complète
n'est recommandée sur cette seule preuve. Avant cette relance, il reste à valider
un volume et une durée représentatifs sous un budget explicitement autorisé,
et à vérifier que l'arrêt persistant se propage à l'ensemble des ligues, plutôt
que de recommencer une session pour chacune.

## Ce que ce test mesure

Ce diagnostic est manuel, dans `.github/workflows/tm-http-diagnostic.yml`.
Il ne lance ni le scraper d'exports, ni le constructeur du portail, ni une
publication. Le jeton GitHub du job n'a que `contents: read` et le checkout ne
conserve pas ses identifiants.

L'expérience utilise `_fetch_json_once` de `tm_player_career.py`, mais **pas**
sa reprise automatique : une session initiale seulement, aucune réinitialisation
entre championnats, aucune nouvelle tentative après un refus. Le comportement
de reprise de production est couvert séparément par les tests hors réseau.

## Échantillon et budgets

- 12 championnats fixes : `a1`, `l1`, `alb1`, `alg1`, `arg1`, `aus1`,
  `az1`, `be1`, `gb1`, `fr1`, `bos1`, `bra1`.
- Pour chacun : saison maximale du CSV d'effectifs ; trois identifiants distincts
  pris au début, au milieu et à la fin de la liste numérique. Les joueurs déjà
  choisis dans un autre championnat sont exclus.
- Parcours alternant les championnats : un joueur de chacun, puis le deuxième,
  puis le troisième. Les identifiants, saisons et empreintes SHA-256 des sources
  sont conservés dans le rapport pour rendre la sélection vérifiable.
- Paliers cumulatifs de **6, 18 et 36** joueurs ; un seul GET carrière par joueur.
  Redirections non suivies. **5 secondes** entre requêtes, **30 secondes** entre
  paliers, un seul worker.
- Une seule ouverture de la page d'accueil pour initialiser la session :
  **40 requêtes navigateur maximum**, ressources comprises ; aucun clic,
  solveur CAPTCHA ou rafraîchissement de session. La navigation est limitée
  à 45 secondes, puis 6 secondes d'initialisation.
  Les images, feuilles de style, polices, médias et domaines autres que
  `transfermarkt.com` / `awswaf.com` sont bloqués avant émission afin de ne pas
  consommer le budget avec des ressources non nécessaires à la session.
- Budget carrière : 36 GET et 15 minutes, vérifié avant chaque GET.
  Un appel déjà lancé conserve son timeout réseau de 30 secondes.
  Le workflow entier a une limite dure de 25 minutes, installation comprise.
- Au maximum **76 requêtes réseau initiées** par la sonde (40 navigateur +
  36 carrière), hors installation et communication GitHub.

## Arrêts et preuve de non-écriture

Le premier échec carrière ouvre le circuit : CAPTCHA, challenge WAF, HTTP non
200 (notamment 403/405/429), erreur transport ou payload invalide. Aucun joueur
suivant n'est demandé. Le bootstrap s'arrête également sur CAPTCHA, 403/405/429,
budget dépassé ou absence de session exploitable. Un arrêt fait échouer le job :
ce n'est pas une collecte réussie.

Un succès exige `success: true`, un objet `data` et une liste `performance`.
Une liste vide est acceptée : le diagnostic valide l'accès et la structure,
**pas la qualité ou la complétude statistique de la carrière**.

Le rapport JSON est écrit uniquement dans `RUNNER_TEMP`, puis conservé comme
artifact GitHub pendant 14 jours, y compris en cas d'échec. Les logs ne contiennent
que des identifiants publics, statuts, classifications et durées ; ni cookies,
ni corps de réponses, ni textes d'exceptions. Aucune capture réseau n'est produite.
Une étape `always()` contrôle l'absence de modification des fichiers de données
du checkout. Aucun code d'export ou de publication n'est appelé.

## Interprétation avant une relance complète

Même 36/36 réussites sur 12 championnats ne reproduiraient pas le volume de onze
championnats complets : le blocage historique pouvait n'apparaître qu'à ce stade.
Ce test lent et séquentiel ne valide pas non plus les trois workers de production,
la durée de vie de la session sur plusieurs heures, ni un autre runner/IP.

En cas de blocage : ne pas relancer automatiquement, ne pas augmenter la
concurrence et ne pas contourner le CAPTCHA. Examiner d'abord la classification
et l'étape atteinte ; vérifier les conditions d'accès autorisées et la source.
En cas de succès : une expérience ultérieure, explicitement autorisée et dotée
de son propre budget, serait nécessaire avant toute conclusion sur une collecte
complète. Conserver les protections contre les exports partiels dans tous les cas.
