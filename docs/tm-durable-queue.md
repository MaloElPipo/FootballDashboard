# Collectes ordinaires : file durable

## Fonctionnement

Le workflow hebdomadaire crée une campagne seulement s'il n'existe pas déjà de
campagne active. Un passage horaire observe et reprend cette même campagne ;
il ne crée pas de collecte. Le cron GitHub peut être retardé.
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

## Reprises et arrêts

- Maximum **4 tentatives par ligue**, effectifs et carrière compris.
- Budget épuisé (76) ou erreur réseau temporaire explicitement classifiée (77) :
  attente minimale de **1 h, 2 h, puis 4 h**. Les autres ligues peuvent avancer.
- 403, 405, CAPTCHA ou 429 (75) : suspension durable globale, sans nouveau
  navigateur ni nouvelle session automatique ; les campagnes suivantes sont
  également bloquées tant que la suspension n'est pas réconciliée.
- Écriture/sauvegarde indisponible, erreur inconnue ou preuve invalide :
  arrêt conservateur, pas de classement arbitraire comme erreur réseau.
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
export validé. Si l'envoi de l'artefact échoue après le scellement, conserver
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
