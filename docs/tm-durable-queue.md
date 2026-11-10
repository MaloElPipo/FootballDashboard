# Collectes ordinaires : file durable

## Fonctionnement

Le workflow crée **une campagne complète par semaine ISO** (fuseau Europe/Paris) :
le premier passage planifié, à partir du **lundi 05:00**, qui trouve la semaine sans
campagne la crée (voir « Complétude hebdomadaire »). Tant qu'une campagne est active,
tous les autres passages observent et reprennent cette même campagne ; ils n'en créent
pas une seconde. Le cron GitHub peut être retardé ou perdu.
Aucun workflow de reprise n'est dispatché par le collecteur : une réponse
GitHub perdue ne peut donc pas provoquer un double dispatch.

Chaque campagne possède une release **brouillon** `tm-queue-<campagne>`.
Son body JSON est le bilan durable par ligue, avec propriétaire (run GitHub),
nombre de tentatives, prochaine échéance, état et empreintes des CSV attendus.
Les réponses joueurs restent dans les checkpoints séparés de la même campagne.
La mise à jour conserve explicitement l'identité et le caractère brouillon ;
elle doit être relue à l'identique avant toute requête de collecte.
Pas de repli sur un fichier local si GitHub est indisponible.

Tous les écrivains doivent utiliser le groupe de concurrence `scrape-weekly`.
Ne pas lancer directement les commandes de mutation hors de ce verrou.
Un run encore actif reste propriétaire : on attend, sans l'interrompre ni
réinitialiser sa file. Un run annulé/expiré ou une tentative interrompue suspend
la campagne. Un redémarrage manuel du même run n'accorde pas une seconde collecte.

## Collecte hebdomadaire en un seul flux (novembre 2026)

Remplace les cinq collecteurs parallèles et leur reprise toutes les 120 s, qui
multipliaient le débit vers une seule IP et relançaient des sessions juste
après un refus. Le volume hebdomadaire mesuré sur les 78 effectifs est de
53 241 requêtes (50 290 fiches carrière + 2 951 pages effectifs) : environ
18,5 h de collecte à 0,8 requête/s, 9,9 h à 1,5 et 7,4 h à 2,0, réparties sur
plusieurs runs enchaînés par la file.

- **Un seul flux** : ligues l'une après l'autre, effectifs puis carrières,
  dans l'ordre de `leagues_master` (priorité). Une seule cadence partagée pour
  toutes les requêtes Transfermarkt, pages effectifs comprises.
- **Paliers de débit** (`pace` dans la file) : 0,8 → 1,0 → 1,2 → 1,5 →
  2,0 requête/s. Un palier de plus après **6 h cumulées de collecte sans
  refus** au palier courant ; au refus, **un palier de moins**, qui devient le
  plafond pendant **2 semaines**. Les paliers passent d'une campagne
  hebdomadaire à la suivante. Plafond absolu codé : 2,0 requêtes/s (les
  collecteurs ignorent toute pause plus courte). `TM_RATE_CEILING` ne peut que
  l'abaisser (`0.8` fige le palier initial). Chaque ligue garde le débit
  utilisé (`rate`) et l'historique des changements est conservé (20 derniers).
- **Un seul jeton par run** : les sous-processus partagent le cookie WAF via
  un fichier local au runner (`TM_WAF_TOKEN_FILE`, droits 600, supprimé en fin
  de collecte, jamais journalisé ni versionné). Plus d'une session navigateur
  par ligue et par étape.
- **Refus (75)** : arrêt de tout le trafic et pause de **toute la campagne**,
  2 h, puis 6 h, puis 24 h (`hold_until`, `refusals` dans la file). Pendant la
  pause, aucune ligue n'est éligible : le passage horaire s'arrête avant
  l'installation du navigateur. À l'échéance, la première tentative sert de
  sonde unique. Un refus après la troisième pause suspend la campagne
  (`access_hold`) pour l'opérateur. Une ligue réussie remet le compteur à zéro.
  On ne change jamais de ligue pour esquiver un refus.
- **Échéance du run (76)** : la ligue reprend au run suivant depuis ses
  checkpoints, sans pénalité ni pause. **Réseau temporaire (77)** : même run,
  10 min plus tard, les autres ligues continuent.
- **Dédoublonnage de la semaine** : un joueur présent dans plusieurs ligues
  n'est demandé qu'une fois. À chaque ligue validée, ses réponses partagées
  avec des ligues encore ouvertes sont publiées dans un asset
  `seed-<ligue>.ndjson.gz` de la release `tm-checkpoints-<campagne>` (extension
  invisible pour `Checkpoints` et la compaction). Les ligues suivantes les
  copient dans leur propre campagne **avec leur date d'origine**. Un échec de
  partage ne coûte que des requêtes, jamais une ligue validée ; une ligue
  collectée sans asset lisible est repartagée depuis sa propre campagne.
- **Saison close** : la saison précédente n'est plus retéléchargée une fois que
  la nouvelle a des apparitions (55 ligues automne-printemps). Les ligues à
  calendrier annuel gardent les deux saisons.
- `TM_COLLECTION_HOURS` (défaut 3, maximum 4,5) règle la collecte par run ;
  le workflow utilise 4,5 h (run #102 : 3 h 06 au total pour 3 h de collecte,
  soit environ 6 min d'installation et de publication).
- **Départ de `main`** : le collecteur fait son checkout sur `main` (`ref: main`) et non
  sur le commit qui l'a déclenché. Un run planifié mis en file derrière un autre
  (verrou `scrape-weekly`) repart ainsi de l'état actuel, commit de données du run
  précédent compris. Sans cela, le `git pull --rebase` final échouait sur un fichier
  modifié des deux côtés (`<ligue>_collection.json` d'une ligue interrompue puis
  reprise) : run #106 du 3 novembre 2026, 21 ligues collectées et aucune publiée.
- **Stockage des points de reprise indisponible (78)** : un envoi vers la release
  `tm-checkpoints-*` qui échoue n'arrête plus la ligue. Les fiches restent en attente,
  en mémoire et sur le disque du runner, et le flush suivant les renvoie (les journaux
  sont immuables et fusionnés par date : renvoyer est sans risque). Les tentatives sont
  espacées de 15 s ; seule une panne continue de plus de `TM_CHECKPOINT_OUTAGE_SECONDS`
  (défaut 180, de 0 à 900 ; `0` rétablit l'arrêt au premier échec) arrête les requêtes
  vers la source. Le flush final fait 3 tentatives, à 20 s puis 40 s d'écart. Au-delà, le processus
  sort avec le code **78** : la ligue repasse en `retry` (motif `checkpoint_storage`)
  5 min plus tard dans le même run, depuis ses fiches locales et distantes, sans pénalité
  de débit ni refus compté. Une même ligue qui échoue une **troisième** fois de suite
  suspend la campagne (`checkpoint_storage`, pas `access_hold`) ; `reconcile` lui
  rend alors un budget de reprises neuf. Le journal du run contient les lignes
  `TM_CHECKPOINT {"event": "gh_error" | "flush_failed" | "flush_recovered" |
  "final_flush_failed", ...}` avec le message de GitHub (jamais les arguments ni le
  jeton). Avant ce correctif, le même incident (run #113 du 3 novembre 2026, JAP1
  arrêtée à 81 %) sortait en code 1 et suspendait toute la campagne (`unclassified_failure`).
  Pendant une panne, jusqu'à `TM_CHECKPOINT_OUTAGE_SECONDS` de collecte non envoyée
  (environ 144 fiches à 0,8 req/s pour 180 s, au lieu de 15 s) peut être perdue si le
  runner disparaît avant la fin de la panne.
- **Passages planifiés d'une campagne suspendue** : le run qui suspend la campagne
  reste rouge (bilan « Campaign needs operator attention »). Les passages horaires
  suivants (`schedule`) qui la retrouvent suspendue ne lancent rien et se terminent
  en vert avec l'annotation « Campaign suspended; explicit operator reconciliation
  required » : ils ne produisent plus un échec par heure dès la suspension. Ce silence
  est borné : douze heures après la dernière activité, l'étape de complétude (voir
  ci-dessous) fait échouer chaque passage livré tant que personne n'a réconcilié.
  Un déclenchement manuel (`workflow_dispatch`) échoue toujours bruyamment.

## Complétude hebdomadaire

Règle de fiabilité : **toutes les ligues qui ont joué sont à jour chaque semaine, et
aucune n'est oubliée**. Le volume n'est donc pas réduit (pas de rotation des ligues) ;
des garde-fous (`tm_queue_completeness.py`) garantissent la semaine.

- **Une campagne par semaine ISO.** `created_at` et `full` (campagne du catalogue entier)
  sont enregistrés à la création. À partir du lundi 05:00 (Paris, été comme hiver), le
  premier passage planifié, qu'il vienne du cron hebdomadaire ou d'un passage horaire,
  qui ne trouve aucune campagne complète créée cette semaine en crée une. Avant, la
  création dépendait d'un seul créneau (lundi 05:15), perdu ou retardé de plusieurs
  heures par GitHub. Toute campagne de la semaine compte, quel que soit son état (active,
  suspendue, terminée, fermée) : seul l'opérateur décide d'en lancer une seconde, par un
  déclenchement manuel, qui crée toujours à la demande. Une campagne limitée à quelques
  ligues (test manuel) ne couvre pas la semaine. Une campagne antérieure à ce correctif,
  sans `created_at`, est jugée sur sa liste de ligues et sa première tentative.
- **Pas de seconde campagne active.** Si la campagne de la semaine précédente n'est pas
  terminée le lundi, elle continue (la file n'autorise qu'une campagne active) ; celle de
  la nouvelle semaine démarre au premier passage qui suit sa clôture, même en milieu de
  semaine : elle recollecte alors toutes les ligues, y compris celles de la veille.
- **Alertes.** Dernière étape du workflow, en lecture seule : elle échoue le run et
  annote les ligues concernées, sans jamais sauter une étape de collecte ou de
  publication. Trois situations :
  - campagne **active depuis plus de 72 h** et non terminée, avec les ligues restantes
    et leur état ;
  - campagne **suspendue ou en `access_hold`** sans décision depuis plus de **12 h**
    (dernière activité enregistrée) ;
  - **semaine sans campagne 24 h après son ouverture**, avec la campagne qui la bloque
    s'il y en a une.

  Chaque passage planifié livré répète l'alerte tant que le problème dure ; GitHub n'en
  livre qu'une partie (environ un passage horaire sur cinq).
- **Bilan « N/78 ligues à jour »** dans le résumé de chaque passage : campagne de la
  semaine, ligues restantes, ligues du catalogue absentes de la campagne, puis un tableau
  repliable par ligue (état, date de collecte, date de vérification de la publication,
  tentatives, motif). Les dates sont en heure de Paris.
- **Ce que ce garde-fou ne fait pas** : il ne saute aucune ligue (une ligue sans match
  est recollectée), ne réduit pas la liste des joueurs et ne relance rien seul après un
  refus. Il garantit qu'un retard, un blocage ou une semaine manquée ne passent pas
  inaperçus.

## Reprises et arrêts

Les règles ci-dessous restent celles de l'ancien chemin séquentiel
(`collection_queue.py collect`, non utilisé par le workflow hebdomadaire).

- Maximum **4 tentatives par ligue**, effectifs et carrière compris.
- Budget épuisé (76) ou erreur réseau temporaire explicitement classifiée (77) :
  attente minimale de **1 h, 2 h, puis 4 h**. Les autres ligues peuvent avancer.
- 403, 405, CAPTCHA ou 429 (75) : suspension durable globale, sans nouveau
  navigateur ni nouvelle session automatique ; les campagnes suivantes sont
  également bloquées tant que la suspension n'est pas réconciliée.
- Écriture/sauvegarde indisponible (code 78, motif `checkpoint_storage`), erreur inconnue
  ou preuve invalide : arrêt conservateur, pas de classement arbitraire comme erreur réseau.
- Après quatre échecs temporaires, la ligue reste `exhausted`, sans reprise.
  Les autres ligues terminent ; la campagne reste visible pour intervention.

Les effectifs sont rafraîchis une fois par ligue dans la campagne ; une reprise
carrière ne refait pas ce rafraîchissement réussi. Les anciens CSV ne sont pas
supprimés par la file.

## Publication

Une réussite de collecte devient `collected`, pas `done`. Après filtrage et
construction, le contrôleur vérifie les quatre CSV complets, la dérivation des
deux CSV de saison courante et le contenu exact des ZIP locaux. Il persiste ces
empreintes avant déploiement (`publishing`).

Au passage suivant, l'URL publique est lue via l'API Pages GitHub. Les deux ZIP
publics doivent contenir exactement les mêmes noms et octets CSV. Un ancien ZIP,
un ZIP manquant, un membre supplémentaire ou dupliqué ne vaut pas réussite.
Une publication retardée reste en attente sans nouvelle collecte. Au bout de
48 h sans correspondance, elle est suspendue. Les ligues déjà collectées restent
vérifiables même si une autre ligue a ensuite rencontré un refus.

Avant publication, la liste des archives de ligues déjà présentes sur gh-pages
doit être couverte par le build. Sinon le déploiement s'arrête ; il ne doit pas
effacer les acquisitions antérieures. Ce garde-fou ne remplace pas le chantier
plus général de validation d'un portail complet.

## Exploitation prudente

**Migration initiale : la collecte est volontairement suspendue.** Le fichier
versionné `artifacts/football-dashboard/tm_collection_access.json` conserve le
refus historique sur CAPTCHA, y compris quand aucune release `tm-queue-*`
n'existe encore. Il est contrôlé avant la préparation d'une file et avant la
collecte. Ni un nouveau lundi, ni un nouvel identifiant, ni un lancement manuel
ne permettent de contourner ce verrou. Un fichier absent ou invalide bloque aussi.

Après décision explicite de l'opérateur et vérification du run historique et
des acquis, la réconciliation de ce verrou nécessite une modification revue :
`status: "reconciled"`, `reviewed_at` au format ISO avec fuseau horaire et
`resolution` décrivant la décision. Ne pas y mettre de secrets ou de données
personnelles. Cette tâche ne lève pas le verrou et n'autorise aucun essai réel.
Cette levée ne supprime pas les suspensions éventuelles des files distantes.

Le bilan est visible dans la release brouillon et le résumé du run collecteur.
Ne jamais effacer une file pour contourner un arrêt. Avant toute intervention :
examiner le run propriétaire via GitHub, ses résultats et les deux ZIP publics.
Une suspension n'expire pas automatiquement. Toute levée exige une décision
explicite de l'opérateur et la réconciliation des états/compteurs, sous le même
verrou ; ne pas remettre à zéro une tentative incertaine.

Les anciennes campagnes sans file ne sont **pas adoptées automatiquement**.
En particulier, le rattrapage historique arrêté au Canada sur CAPTCHA et ses
47 championnats acquis ne sont ni relancés ni modifiés par cette migration ;
le verrou versionné interdit également de recommencer sous un autre nom.
Les modifications de code et les tests ne déclenchent aucune collecte réelle.

## Administration des suspensions

Utiliser le workflow **Administration des campagnes TM suspendues**
(`tm-queue-admin.yml`), sous le même verrou `scrape-weekly` que le collecteur.
Aucune commande d'administration ne lance de navigateur, de collecte, de
publication ou de dispatch ; aucune release ni sauvegarde n'est supprimée.

1. Indiquer la campagne **sans** le préfixe `tm-queue-`, l'opération
   `reconcile` ou `close` et une justification sans données sensibles.
   Laisser `confirmation` vide : c'est une **simulation sans écriture**.
2. Lire le résumé et l'artefact `tm-queue-admin-report` : état complet, révision,
   propriétaire courant/précédent et résultats des runs enregistrés, motifs
   d'arrêt, tentatives consommées et preuves des deux ZIP publics. Une preuve
   absente, indisponible ou différente n'est jamais une réussite.
3. Relancer avec les mêmes paramètres et recopier la valeur `ADMIN-…`.
   Elle lie la décision à ce bilan précis. Toute modification de la file, des
   runs ou des preuves exige une nouvelle simulation et confirmation.
   Un run encore actif ou au résultat inconnu interdit toute mutation.

`close` clôture par abandon, **pas** par réussite : les états des ligues,
empreintes, échéances et compteurs restent conservés. La campagne ne sera plus
collectée. Un refus de source reste un blocage global (`access_hold`) même
après clôture, sauf décision explicite `acknowledge_refusal=true`.

`reconcile` conserve les tentatives consommées, y compris interrompues, et les
effectifs déjà rafraîchis. Une tentative incertaine devient éligible après un
nouveau délai conservateur (1/2/4 h), sans dépasser quatre tentatives ; au plafond
elle reste épuisée. Les publications suspendues ne deviennent réussies que si
les deux ZIP correspondent aux empreintes enregistrées. Une collecte non scellée
doit être réparée avant réconciliation ou clôturée, jamais déclarée réussie.
Une autre campagne active empêche la réouverture d'une suspension.

`requeue-unpublished` (campagne **suspendue** uniquement, même verrou et même
confirmation `ADMIN-…`) traite une collecte validée dont les exports ont disparu avec
le runner avant d'être poussés (suspension `publication_not_prepared`). Les ligues
`collected` sans `expected` repassent en `retry` (motif `exports_lost`), sans tentative
consommée ni échéance d'attente ; le collecteur normal les reconstruit à partir de leurs
sauvegardes `tm-checkpoints-*` (les fiches déjà acquises ne sont pas redemandées, les
effectifs absents du dépôt le sont) et produit sa propre preuve de collecte. Rien n'est
déclaré réussi : la publication passe ensuite par `seal`, comme pour toute ligue.
Refus si une ligue `collected` est déjà scellée (`expected` : utiliser
`recover-publication`), si une ligue `publishing` est trop récente (voir plus bas),
si aucune ligue n'est concernée, ou si le plafond de tentatives
d'une campagne séquentielle est atteint. La décision sur un refus Transfermarkt reste
celle de `reconcile` ; le journal `administration` conserve la liste `requeued`.

Elle couvre aussi une ligue `publishing` **jamais déployée** (scellée, puis une étape
ultérieure a échoué) : si ses deux ZIP publics ne correspondent pas aux empreintes et
que le scellement date d'au moins 30 minutes (un déploiement récent peut encore être en
cours), elle repasse en `retry` (motif `publication_lost`), ses empreintes sont
retirées et le collecteur la reconstruit puis la scelle de nouveau. `reconcile` continue
de refuser ce cas.

**Taille de la file.** Le corps de la release est limité à 120 000 octets (GitHub accepte
125 000 caractères) ; au-delà, la sauvegarde échoue (`Queue too large`) et plus rien ne
peut être scellé ni administré. Le journal `administration` conserve donc un **résumé**
des preuves publiques (format 2 : codes de ligues groupés par type d'archive et par
statut, les ligues sans empreinte attendue étant omises) avec le code `ADMIN-…` ; les
anciennes entrées sont compactées à la sauvegarde. Le bilan complet reste dans
l'artefact `tm-queue-admin-report` (90 jours). Un message `TM_QUEUE_SIZE` apparaît
dans les journaux dès que la file dépasse 100 000 octets.

Un refus Transfermarkt ne peut être réconcilié sans
`acknowledge_refusal=true`, décision distincte incluse dans la confirmation.
Sur une campagne déjà clôturée, cette décision lève seulement son blocage :
elle ne la rouvre pas. Le verrou historique versionné
`tm_collection_access.json` **n'est jamais modifié** par cette commande.
Toutes les décisions sont ajoutées au journal `administration` de la file,
avec le run administrateur, le motif précédent et les preuves examinées.

Inspection locale en lecture seule (nécessite l'accès GitHub au dépôt) :

```sh
python artifacts/football-dashboard/tm_queue_admin.py \
  --campaign run-123 --action close --resolution "Abandon après examen" \
  --output /tmp/tm-queue-admin.json
```

L'application avec `--confirm` est réservée au workflow verrouillé. Ne pas
modifier les compteurs ni supprimer une file manuellement pour lever un arrêt.

## Validation hors ligne

### Récupérer une collecte terminée avant son scellement

Pour une campagne **suspendue**, avec ligues `collected` sans `expected` ou ligues
déjà `publishing` dont le lot doit être récupéré, choisir
`recover-publication` dans le même workflow d'administration. Ne pas utiliser
`reconcile` pour relancer la collecte.

1. Choisir `exports_ref` : idéalement le SHA du commit ayant conservé les quatre
   CSV complets et le fichier `<ligue>_collection.json`, sinon `main`. Le second
   checkout restaure seulement les données ; son code n'est jamais exécuté.
2. Laisser la confirmation vide et `acknowledge_refusal=false`. Le bilan lie
   chaque export à sa campagne, sa preuve de collecte datée et ses empreintes.
   Les ZIP sont reproductibles : leurs dates internes ne dépendent pas du runner.
3. Reprendre les mêmes paramètres avec le jeton `ADMIN-…` du bilan. Toute preuve
   modifiée, export absent/périmé, transaction inachevée, date inconnue ou run
   propriétaire encore actif bloque l'opération **sans écriture de la file**.
4. Le workflow restaure les CSV dans un dossier isolé, refiltre la saison courante,
   prépare les ZIP `all` (quatre CSV) et `current` (deux CSV), puis les valide avec
   `scripts/collection_queue.py seal`. Toutes les ligues sont validées avant
   l'unique sauvegarde distante de la file.
5. Télécharger l'artefact `tm-publication-recovery` (conservation 90 jours) :
   `full/` contient les exports et preuves inchangés, `current/` le filtrage,
   `data/` les deux ZIP par ligue et `recovery.json` le manifeste contrôlé.
   **Cette action prépare seulement la publication, elle ne déploie rien.**
   Ne jamais publier ce dossier comme remplacement complet du portail :
   il ne contient que les ligues récupérées. La publication ultérieure doit
   préserver le portail et toutes les autres archives déjà publiques.

Les ligues récupérées deviennent `publishing`, jamais `done` sur la seule base
du ZIP local. La campagne reste suspendue, ses tentatives et motifs sont conservés,
et aucun refus (y compris historique) n'est levé. Après publication séparée,
`reconcile` vérifie les deux ZIP publics avant de reconnaître la réussite ; un
refus exige toujours sa décision explicite distincte.

Si les exports n'ont jamais été persistés avant la perte du runner, cette
procédure refuse de les inventer ou de reprendre automatiquement le scraping.
Restaurer d'abord un jeu complet de CSV et sa preuve originale dans un commit
conservé, puis refaire la simulation. Un cache de réponses seul n'est pas un
export validé. Si les réponses des ligues sont conservées dans les sauvegardes de la
campagne, utiliser plutôt `requeue-unpublished` (voir plus haut) : elle ne promeut
aucun cache en export validé, elle renvoie les ligues au collecteur normal. Si l'envoi
de l'artefact échoue après le scellement, conserver
la suspension : refaire une simulation `recover-publication`, puis confirmer
son nouveau bilan avec les mêmes exports. Les ligues `publishing` sont acceptées
uniquement si les deux ZIP reconstruits correspondent aux empreintes déjà
scellées. Leurs empreintes, délai de publication et tentatives ne sont pas
réinitialisés. En cas d'écriture distante ambiguë, le workflow tente également
de conserver le lot validé même si la confirmation de sauvegarde a échoué ;
la simulation suivante relit l'état réellement conservé sur GitHub.

Depuis la racine :

```
python -m unittest discover -s artifacts/football-dashboard/tests -p 'test_*.py'
cd artifacts/football-dashboard
python -m unittest test_tm_global_stop test_tm_http_recovery test_tm_http_diagnostic
```

Les simulations injectent GitHub, le temps, les processus et les ZIP ; elles
couvrent interruptions, doublons, pertes de confirmation, refus, indisponibilité
du stockage, résultats partiels, publications retardées et limites de reprises.
Elles ne démontrent ni l'accès futur à Transfermarkt, ni une heure garantie
d'exécution de GitHub Actions.
