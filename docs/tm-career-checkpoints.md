# Reprise des carrières Transfermarkt

## Campagnes et fraîcheur

Le workflow normal utilise `run-<github.run_id>` ; une réexécution du même
run et le rattrapage automatique gardent cet identifiant. Un nouveau lancement
crée une nouvelle campagne. Pour reprendre manuellement, renseigner
`campaign_id` avec l'identifiant du run initial.

En CLI, fournir `--campaign <identifiant>` pour reprendre ; sans identifiant,
chaque invocation crée une campagne distincte. Les identifiants acceptent
lettres ASCII, chiffres, tirets et underscores (100 caractères maximum).

Les checkpoints contiennent uniquement la réponse métier, l'identifiant joueur,
la campagne, la version du format et l'instant de collecte UTC. Ils ne contiennent
ni cookie ni en-tête HTTP. Une réponse sans liste `performance` valide n'est
pas un succès ; une liste explicitement vide est acceptée. L'agrégation doit
réussir avant l'enregistrement. Les métadonnées d'effectif restent propres à
chaque ligue, même si la réponse du joueur est partagée entre ligues.

Une nouvelle campagne ne lit pas les réponses des précédentes. Une reprise
ancienne conserve ses dates réelles : la preuve de la ligue expose la plage
`collected_from`–`collected_through`, et la date de fraîcheur publique est
la plus ancienne réponse requise, pas la date de reprise ou d'export.

## Persistance hors du runner

Le workflow active `TM_CHECKPOINT_REMOTE=github`. Il utilise le `GITHUB_TOKEN`
existant (`contents: write`) via `gh`, pour une release **brouillon**
`tm-checkpoints-<campagne>`. Aucun service ni secret supplémentaire à installer.
Les fichiers ne sont ni dans Git, ni dans les CSV/ZIP publics, ni publiés comme
release finale. Le code ne déploie pas et ne modifie pas la branche principale
pour enregistrer ces checkpoints.

Chaque succès est écrit localement par fsync + renommage atomique. Les journaux
compressés sont envoyés à GitHub tous les 25 succès ou toutes les 15 secondes,
ainsi qu'à la sortie propre. Les lots déjà envoyés survivent à la disparition du
runner ; un arrêt brutal peut perdre le dernier lot non confirmé (au plus
24 succès en attente, plus des requêtes en vol). Les uploads ont un timeout
de 60 secondes et une panne de stockage arrête les nouvelles requêtes source.

Après 100 journaux, une archive consolidée est envoyée **avant** la suppression
des anciens journaux. Une interruption entre upload et suppression laisse des
copies dédupliquées par joueur/horodatage à la restauration. Un upload échoué
ne supprime pas la dernière sauvegarde. Les succès locaux non encore envoyés
sont renvoyés à la prochaine reprise sur le même disque.

Le mode CLI sans `--checkpoint-remote` suppose un disque persistant dans
`live/data/tm_checkpoints/` (surcharge : `--checkpoint-dir`). Il ne garantit pas
la survie à la disparition de cette machine. Ne pas exécuter deux collecteurs
simultanés sur une même campagne ; le workflow conserve son verrou global.
Les brouillons ne sont jamais purgés sur leur seul âge. La maintenance manuelle
ci-dessous protège toute campagne encore susceptible d'être reprise.

## Rétention confirmée

Politique confirmée par le propriétaire : **30 jours**, **3 campagnes les plus
récentes conservées**, **aucune clôture automatique**. Une campagne partielle,
ancienne ou au statut inconnu reste reprenable et protégée indéfiniment.
La réussite d'un run GitHub ne prouve pas qu'une campagne est complète.

La clôture est une décision explicite : vérifier les exports utiles ou décider
d'abandonner définitivement la reprise, puis fournir une justification.
Elle écrit un marqueur horodaté dans le corps de la release brouillon.
Le collecteur refuse ensuite de reprendre cette campagne distante. La clôture
ne détruit aucun lot et n'est pas appliquée automatiquement aux anciennes releases.
Un marqueur absent, invalide ou ambigu protège la campagne.

Une campagne close n'est éligible qu'après 30 jours **depuis la clôture ET depuis
la dernière modification** de la release ou de ses assets. Les trois campagnes
les plus récentes par date de création sont toujours conservées. Les releases
publiques et les identifiants invalides ne sont jamais supprimés.

### Inventaire / simulation (aucune écriture)

Avec `gh` authentifié et un accès privé au dépôt :

```sh
python artifacts/football-dashboard/tm_checkpoint_retention.py \
  --repo MaloElPipo/FootballDashboard --output /tmp/tm-retention.json
```

Le rapport JSON liste toutes les campagnes, chaque asset et sa taille, la
raison de protection, les candidats, le volume total et le volume récupérable
en octets compressés. Releases **et** assets sont paginés. L'empreinte
`PURGE-…` lie la confirmation au dépôt, à la politique et à l'inventaire exact.
Les runs de collecte/maintenance actifs ou en attente sont également listés.
Un échec API n'est jamais interprété comme une liste vide.

### Clôture puis purge dans GitHub Actions

Après fusion du workflow `Rétention des sauvegardes TM` :

1. Lancer `operation=inventory` (valeur par défaut). Télécharger l'artefact
   `tm-retention-inventory` ou consulter le JSON dans les logs privés.
2. Pour une campagne **dont aucune reprise n'est nécessaire**, lancer
   `operation=close`, `campaign=<identifiant>`, `reason=<justification vérifiée>`,
   `confirmation=CLOSE-<identifiant>`. Cela commence le délai de 30 jours.
3. Après ce délai, refaire `inventory`. Examiner les candidats et leurs volumes.
4. Pour accepter la suppression définitive de ces seuls candidats, lancer
   `operation=apply`, `confirmation=<valeur PURGE-… exacte du rapport>`.
   Sans cette confirmation, aucune suppression n'est possible. Une modification
   de l'inventaire impose une nouvelle simulation et confirmation.

Collecte et maintenance partagent le verrou `scrape-weekly`, sans annulation
d'un run en cours. Les mutations sont refusées hors de ce workflow manuel.
Un autre run de collecte/maintenance actif **ou en attente** bloque la mutation :
relancer la maintenance quand la file est vide. Les erreurs réseau, de permission,
de date ou les changements d'un candidat interrompent la purge. Une suppression
partielle réussie n'est pas annulable ; refaire un inventaire avant de poursuivre.

La purge supprime uniquement les releases brouillon candidates et leurs assets :
pas les tags, pas les CSV/ZIP, pas les checkpoints locaux, pas l'historique Git.
Ne pas lancer de collecteur distant hors du workflow verrouillé pendant la
maintenance, ni modifier manuellement les releases en parallèle. Aucun accès à
Transfermarkt n'est effectué par cette maintenance. Il n'y a pas de purge planifiée.

## Budget et exports

`--budget-seconds` vaut 240, accepte une réduction mais refuse une augmentation.
L'initialisation WAF et les GET partagent cette échéance monotone ; les timeouts
HTTP/navigateur sont bornés au temps restant. Les requêtes en cours terminent
ou expirent ; aucune nouvelle requête source n'est engagée après l'échéance.
La sauvegarde et l'agrégation locales peuvent se terminer après le budget :
elles ne donnent pas de temps réseau supplémentaire à Transfermarkt.

Le code 76 signifie budget épuisé, 75 conserve le refus global existant.
Nombre de workers, pauses, nombre de passes et déclenchements de rattrapage
ne sont pas augmentés. Chaque passe reprend les manquants de la même campagne.
Les quatre exports publics restent inchangés si un joueur manque. Seule une
ligue complète entre dans la transaction d'export existante.

## Vérification sans réseau source

Depuis `artifacts/football-dashboard` :

```sh
python -m unittest discover -s tests -v
python -m unittest test_tm_career_guard test_tm_global_stop test_tm_http_recovery -v
```

Les tests simulent notamment interruption/reprise, nouveau runner, upload
échoué, compaction interrompue, changement de campagne, absence de GET répété,
absence d'initialisation WAF lorsque tout est sauvegardé, réponse invalide,
budget épuisé et conservation des anciens exports. Les échanges GitHub sont
simulés ; aucune collecte Transfermarkt réelle n'est lancée par ces tests.
