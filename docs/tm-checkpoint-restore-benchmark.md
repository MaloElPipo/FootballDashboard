# Restauration indexée des sauvegardes TM

## Banc d'essai GitHub Actions : restauration réelle

### Remplacement sous le même nom et téléchargement interrompu

Le workflow `tm-checkpoint-integration-replacement.yml` est indépendant des
mesures de débit. Il utilise uniquement `MaloElPipo/ViveLaPiscine`, une branche
`tm-checkpoint-replacement/**` et le brouillon `it-<run_id>-<run_attempt>3`.
Le verrou global `scrape-weekly`, sans annulation, couvre le scénario et son
nettoyage `always()`. Aucun scraping, publication ou asset réel n'est touché.

Six processus successifs partagent le disque du runner :

1. `seed` importe une réponse synthétique et valide le reçu.
2. `replace` supprime **uniquement** l'asset attendu après contrôle de
   l'inventaire exact, puis téléverse un nouveau `replacement.jsonl.gz`.
   Le nouvel identifiant opaque `gh` doit différer ; le nom reste identique.
   Le reçu précédent ne doit pas reconnaître les nouvelles métadonnées.
   Un seul téléchargement doit restituer exactement la nouvelle réponse.
3. `replaced-warm` vérifie le contenu et le reçu avec **zéro téléchargement**.
4. `interrupt` remplace à nouveau ce seul asset, puis lance réellement
   `gh release download --output -`. Après lecture de 4 096 octets distants,
   le test écrit ce préfixe dans le fichier temporaire et termine le processus
   `gh` encore actif. L'adaptateur remonte un échec au restaurateur : aucun
   reçu pour la nouvelle identité et aucune modification des données déjà
   validées ne sont permis.
5. `recover` retélécharge intégralement le lot et valide données, date et reçu.
6. `warm` exige à nouveau zéro téléchargement et le contenu exact.

L'interruption est injectée côté lecteur ; ce n'est pas une panne réseau
GitHub ni un crash du runner. Le transfert partiel est mesuré séparément des
octets importés avec succès. Les JSON `replacement-*.json` conservent les
métadonnées réelles avant/après, les PID, les téléchargements, les octets
partiels, la version de `gh`, le run et le SHA du code. L'artifact Actions
`replacement-evidence` est conservé sept jours.

Les trois révisions ont des dates de collecte synthétiques strictement
croissantes, vérifiées sans réécriture à la lecture. Cela respecte la règle
existante « réponse la plus récente » : le scénario ne prétend pas définir
une correction de contenu à date identique ni la suppression d'un joueur
absent du lot remplacé. L'index reste un cache fusionné de réponses immuables,
pas un miroir avec suppression des anciennes lignes.

Le nettoyage vise le tag exact de cette campagne et exige l'absence de
brouillon, d'assets et de tag Git. Après annulation forcée, vérifier ce
nettoyage avant de supprimer la branche temporaire.

#### Preuve GitHub — 30 octobre 2026

Run réussi : https://github.com/MaloElPipo/ViveLaPiscine/actions/runs/41033400790

Code exécuté : `eef0e80545d538c95b6bc15cdc744909de6bc006`.
Les jobs `replacement` et `cleanup` ont réussi avec
`gh version 2.103.2 (2026-10-23)`. Campagne : `it-41033400790-13`.
Nom unique conservé : `replacement.jsonl.gz`.

| Passage | ID réel gh | updatedAt (UTC) | Taille distante | Octets importés | Octets partiels | Téléchargements |
|---|---|---|---:|---:|---:|---:|
| seed | RA_kwDOTz9B5c4pOO4L | 2026-10-30T09:26:18Z | 75 451 | 75 451 | 0 | 1 |
| replace | RA_kwDOTz9B5c4pOO6l | 2026-10-30T09:26:23Z | 75 452 | 75 452 | 0 | 1 |
| replaced-warm | RA_kwDOTz9B5c4pOO6l | 2026-10-30T09:26:23Z | 75 452 | 0 | 0 | 0 |
| interrupt | RA_kwDOTz9B5c4pOO-B | 2026-10-30T09:26:30Z | 75 452 | 0 | 4 096 | 1 interrompu |
| recover | RA_kwDOTz9B5c4pOO-B | 2026-10-30T09:26:30Z | 75 452 | 75 452 | 0 | 1 |
| warm | RA_kwDOTz9B5c4pOO-B | 2026-10-30T09:26:30Z | 75 452 | 0 | 0 | 0 |

Le second remplacement a même nom **et même taille** : l'identité n'est donc
pas réduite au couple nom/taille. Les assertions ont vérifié chaque réponse
et sa date, l'absence du nouveau reçu après interruption, puis sa présence
après reprise. Les octets partiels sont ceux lus par l'adaptateur, pas une
mesure des octets réseau préchargés par `gh`.

Les contrôles API après exécution ont confirmé l'absence du brouillon exact
et de son tag, la branche principale inchangée et la suppression de la seule
branche temporaire créée pour cet essai. Les JSON sont conservés dans
`replacement-evidence` et dans `generated-artifacts/restore-replacement/`
(ignoré par Git et le déploiement). Les résultats essentiels ci-dessus
restent disponibles après expiration des artifacts Actions.

Validation locale : 84 tests réussis (68 index/partitions/rétention/volume,
13 checkpoints carrière et 3 scénarios de benchmark hors ligne). Les tests
locaux couvrent aussi l'invalidation séparée de chacun des quatre champs
d'identité et la séquence complète remplacement/interruption/reprise.
La logique de production n'a pas nécessité de modification.

### Comparaison partitionnée sur runners neufs

Le workflow courant compare deux campagnes **exclusivement synthétiques** :
`it-<run_id>-<run_attempt>1` (monolithe) et
`it-<run_id>-<run_attempt>2` (partitions). Les suffixes numériques restent
compatibles avec le garde-fou du runner. Il ne convertit aucune campagne,
même synthétique : les deux formats sont générés indépendamment avec les mêmes
512 réponses déterministes, leurs dates et leur contenu d'origine.

- Monolithe : un fichier ; partitions : quatre lots de 128 réponses au format v2.
- Sélection groupée : identifiants 1 à 16, soit une seule partition.
- Sélection dispersée : identifiants 1, 33, …, 481, soit les quatre partitions.
- Contrôle intégral : les 512 réponses, dans un job indépendant pour ne pas
  réchauffer le cache des sélections ciblées.
- Chacun des six couples format/sélection démarre dans un **job GitHub neuf**,
  sans transfert de cache. Deux processus Python successifs mesurent le disque
  neuf puis le même disque. Les jobs de génération n'envoient que les fixtures
  distantes, aucun artifact local aux lecteurs.
- Le job `compare` exige les douze mesures et l'égalité des SHA-256 canoniques
  entre formats et entre passages, y compris sur l'intégralité de la population.
  Seul le champ campagne est retiré du hash comparatif, car les campagnes sont
  distinctes ; chaque réponse complète, campagne incluse, est d'abord comparée
  exactement à sa référence déterministe.

Les mesures séparent le constructeur et la lecture/vérification ; le **total**
et les **octets téléchargés** couvrent les deux. Le constructeur partitionné
doit télécharger zéro octet ; les imports différés sont comptés explicitement.
Les assertions vérifient les noms, tailles et nombres exacts des téléchargements,
les reçus des seules partitions demandées, la stabilité des identités et
l'absence de transfert au passage suivant sur le même disque.

Six artifacts `restore-<format>-<sélection>` conservent les JSON sept jours.
Le verrou de workflow `scrape-weekly`, sans annulation, couvre la génération,
les six jobs de mesure, la comparaison et les deux nettoyages `always()`.
Chaque nettoyage vise uniquement le brouillon synthétique exact du run et
contrôle l'absence de tag. En cas d'annulation forcée, contrôler ces nettoyages
avant de retirer la branche de test. Aucun scraper, workflow de collecte,
portail, campagne réelle ou règle de rétention n'est modifié.

La sélection groupée est volontairement favorable ; la sélection dispersée
mesure le cas où aucune partition ne peut être évitée. Cette population reste
petite et artificielle : ces temps GitHub ne prédisent pas ceux d'une archive
de 576 Mo. Les jobs peuvent se chevaucher ; ni les machines ni les caches
réseau GitHub ne sont identiques ou contrôlés. Ce n'est pas un essai statistique
de latence. Les octets sont ceux des fichiers compressés, hors HTTP/TLS, et le
RSS celui de Python, hors sous-processus `gh`.

### Résultats partitionnés GitHub Actions — 30 octobre 2026

Run réussi : https://github.com/MaloElPipo/ViveLaPiscine/actions/runs/41032217256

Code testé : `f5b07237e928dd0068e7703605dd40e4071fa7d5`.
Les onze jobs ont réussi, dont la comparaison intégrale et les deux nettoyages.
Runners `ubuntu-latest`, `gh version 2.103.2 (2026-10-23)`.
Campagnes jetables : `it-41032217256-11` et `it-41032217256-12`.

| Format / sélection / disque | Constructeur (s) | Lecture + contrôle (s) | Total (s) | RSS (Mio) | Octets téléchargés | Lots | Commandes gh |
|---|---:|---:|---:|---:|---:|---:|---:|
| Monolithe / groupés / neuf | 4,794 | 0,017 | 4,812 | 24,25 | 38 332 486 | 1 | 3 |
| Partitions / groupés / neuf | 1,333 | 1,414 | 2,747 | 24,12 | 9 584 047 | 1 | 3 |
| Monolithe / dispersés / neuf | 3,465 | 0,017 | 3,483 | 24,23 | 38 332 486 | 1 | 3 |
| Partitions / dispersés / neuf | 2,706 | 5,147 | 7,852 | 24,28 | 38 334 316 | 4 | 6 |
| Monolithe / groupés / même disque | 0,946 | 0,019 | 0,965 | 20,34 | 0 | 0 | 2 |
| Partitions / groupés / même disque | 1,100 | 0,022 | 1,122 | 20,41 | 0 | 0 | 2 |
| Monolithe / dispersés / même disque | 0,795 | 0,033 | 0,828 | 20,20 | 0 | 0 | 2 |
| Partitions / dispersés / même disque | 0,957 | 0,014 | 0,972 | 20,27 | 0 | 0 | 2 |
| Monolithe / tous / neuf | 4,475 | 0,360 | 4,836 | 24,23 | 38 332 486 | 1 | 3 |
| Partitions / tous / neuf | 1,438 | 5,829 | 7,267 | 24,29 | 38 334 316 | 4 | 6 |
| Monolithe / tous / même disque | 0,949 | 0,444 | 1,394 | 20,48 | 0 | 0 | 2 |
| Partitions / tous / même disque | 1,296 | 0,544 | 1,840 | 20,33 | 0 | 0 | 2 |

Dans cet essai, la sélection groupée télécharge **75 % d'octets en moins** et
prend 2,747 s contre 4,812 s (environ 43 % de temps en moins). La sélection
dispersée télécharge tout et prend **7,852 s contre 3,483 s** : le découpage
n'est pas une accélération générale. La légère hausse du volume partitionné
(1 830 octets) vient des fichiers compressés distincts. Toutes les reprises
sur le même disque téléchargent **zéro octet**.

Pour les partitions, **tous les octets sont téléchargés pendant les lectures**,
pas pendant le constructeur. Ne comparer que 1,333 s ou 2,706 s au temps
monolithique masquerait donc une part importante du coût réel.

Le hash canonique intégral des 512 réponses, identique dans les quatre mesures
complètes, vaut :
`044f6946f96b9103076346b3bde6aac48c571e7a011428922c5db756a763a791`.
Le contrôle inclut les données et les dates ; la campagne est vérifiée
séparément contre la référence complète avant calcul du hash comparatif.

Les appels API après le run ont confirmé l'absence des deux brouillons et de
leurs tags, ainsi que la branche principale inchangée. La branche temporaire
a été supprimée. Les JSON bruts sont conservés dans les six artifacts du run
pendant sept jours et localement dans
`generated-artifacts/restore-remote/` (ignoré par Git et le déploiement).
Les mesures essentielles restent dans ce document après expiration des artifacts.

Validation locale : **199 tests réussis**, dont le banc hors ligne étendu aux
deux formats, aux trois sélections et aux imports différés. Aucune campagne
réelle migrée, aucune collecte ni publication déclenchée.

### Scénario monolithique précédent (conservé dans le script)

Le workflow `tm-checkpoint-integration-restore.yml` est distinct des essais
de file et de compaction. Il n'importe aucun scraper et n'appelle ni
Transfermarkt, ni un workflow de collecte, ni une publication. Il est limité
à `MaloElPipo/ViveLaPiscine`, sur une branche `tm-checkpoint-restore/**`
(ou par déclenchement manuel une fois installé).

Le verrou global `scrape-weekly`, sans annulation du détenteur, couvre les
deux runners et le nettoyage. Les jobs utilisent leur propre `GITHUB_TOKEN`.
Une campagne `it-<run_id>-<run_attempt>` contient uniquement des réponses
synthétiques ; aucune campagne réelle n'est ouverte ou migrée.

### Scénario et preuves produites

- Un journal initial contient 256 réponses déterministes, chacune avec 64 Kio
  de bruit pseudo-aléatoire encodé en hexadécimal, pour éviter une compression
  irréaliste. La date d'origine est fixe.
- Premier import sur disque vierge, puis second processus sur le même disque :
  aucun téléchargement n'est permis au second passage.
- Un écrivain séparé ajoute une réponse dans un petit lot : le lecteur ne doit
  télécharger que ce nouveau lot, sans changement d'identité du premier.
- Suppression du répertoire de cache lecteur : les deux lots doivent être
  téléchargés et reconstruits intégralement.
- Un autre job GitHub, sans transfert de cache ni de sauvegarde locale,
  restaure les deux lots sur un runner neuf.

Chaque passage compare **toutes** les réponses attendues, dates et campagne
comprises, et exporte un SHA-256 canonique. Les reçus SQLite sont vérifiés
avec les véritables champs `name`, `id`, `size`, `updatedAt` renvoyés par `gh`.
Les assertions refusent les métadonnées incomplètes, les téléchargements
supplémentaires et les réponses modifiées.

Deux artifacts Actions conservés sept jours contiennent les mesures JSON :
`restore-retained-disk` et `restore-fresh-runner`. Chaque mesure inclut le SHA
du code, l'identifiant du run, la version de `gh`, les identités des assets,
les téléchargements et leurs tailles, le nombre de commandes `gh`, le temps
de construction du lecteur, le temps total et le pic RSS Python.

**Périmètre des métriques :** le temps total comprend la lecture et la
vérification des réponses, y compris les imports différés ; il exclut la
génération/upload des lots et la commande de version de `gh`. Les octets sont
les tailles des fichiers compressés effectivement téléchargés, pas les octets
HTTP/TLS. Les commandes ne comptent pas les requêtes HTTP internes de `gh`
(pagination, redirections). Le RSS est celui du processus Python, pas celui
des sous-processus `gh` ni de toute la VM. Ce petit essai valide la mécanique,
pas un débit représentatif de l'archive de 576 Mo.

Le job final `always()` supprime exclusivement le brouillon jetable du run et
vérifie l'absence de release, assets et tag. C'est le nettoyage des fixtures
existantes, pas une exception appliquée aux campagnes réelles : leurs règles
de clôture, délai de 30 jours, protection des trois récentes et confirmation
restent inchangées. Après annulation forcée, vérifier le résultat du nettoyage
avant de retirer la branche temporaire ; ne jamais purger un autre préfixe.

### Résultats GitHub Actions — 30 octobre 2026

Run réussi : https://github.com/MaloElPipo/ViveLaPiscine/actions/runs/41029634155

Code testé : `e5f5f6328a3e75a496f8698ac01ba67f9d076f09`.
Campagne exclusivement synthétique : `it-41029634155-1`.
Les trois jobs `retained-disk`, `fresh-runner` et `cleanup` ont réussi.
Version des runners : `gh version 2.103.2 (2026-10-23)`, `ubuntu-latest`.
Chaque passage est un processus Python distinct ; les quatre premiers
partagent un runner, le dernier est un autre job sans cache transféré.

| Passage | Import (s) | Total (s) | Pic RSS Python (Mio) | Octets téléchargés | Lots | Commandes gh |
|---|---:|---:|---:|---:|---:|---:|
| Premier import, 256 réponses | 2,659 | 2,948 | 23,40 | 19 166 819 | 1 | 3 |
| Second processus, même disque | 0,875 | 1,217 | 20,43 | **0** | **0** | 2 |
| Nouveau petit lot, 257 réponses | 1,938 | 2,254 | 20,62 | **75 406** | **1 nouveau** | 3 |
| Cache lecteur supprimé | 2,934 | 3,222 | 23,48 | 19 242 225 | 2 | 4 |
| Runner neuf | 3,828 | 4,008 | 23,94 | 19 242 225 | 2 | 4 |

Identités réellement renvoyées par `gh`, stables dans tous les passages :

| Nom | id | size | updatedAt |
|---|---|---:|---|
| baseline.jsonl.gz | RA_kwDOTz9B5c4pN7kk | 19166819 | 2026-10-30T08:54:55Z |
| delta.jsonl.gz | RA_kwDOTz9B5c4pN7pc | 75406 | 2026-10-30T08:55:04Z |

Le champ `id` de `gh` est ici un identifiant opaque, pas un entier REST.
Le reçu SQLite conserve cette valeur sans conversion. Les assertions vérifient
la présence des quatre champs, leur stabilité et les reçus effectivement
enregistrés, pas simplement l'existence des fichiers.

Empreintes canoniques des réponses complètes (données, campagne et dates) :

- Premier import et reprise, 256 réponses :
  `4afe199c55192887ebca7d202aca0d4c7616fb88d831f1b540656b1bf13923ff`.
- Ajout du petit lot, reconstruction et runner neuf, 257 réponses :
  `dd77995667dba638dba9840043e04a2e745825d5fe314ece939b5fc49a47c9f9`.

La reprise est 2,42 fois plus rapide que le premier import dans cet essai et
supprime tout transfert de journal. Le nouveau lot évite de télécharger
à nouveau les 19,17 Mo inchangés. La différence de temps entre reconstruction
et runner neuf illustre la variabilité des runners/réseau ; un seul passage
par cas ne constitue pas une distribution de latence. Ne pas extrapoler
ces temps au benchmark local de 576 Mo ni au format partitionné expérimental.

Le job de nettoyage a confirmé l'absence du brouillon, de ses assets et de tag.
Une vérification API après le run a confirmé ces absences ainsi que la
branche principale inchangée. La branche temporaire du test a ensuite été
supprimée et son absence vérifiée. Aucun nettoyage de campagne réelle,
aucun scraping, aucune publication et aucune migration n'ont été effectués.
Les JSON bruts sont attachés au run pendant sept jours ; les mesures et
identités ci-dessus restent dans ce document après leur expiration.

Validation locale : **183 tests réussis**, dont deux tests du banc d'essai.
Les tests locaux ne sont pas utilisés comme preuve du débit réseau ;
la preuve distante est le run Actions ci-dessus.

## Extension : runner neuf et lots distants partitionnés

### Format et compatibilité

Le format expérimental conserve les mêmes réponses JSON version 1 et le même
conteneur `jsonl.gz`. Un lot nommé
`tm-part-v2-<id_min>-<id_max>-<uuid>.jsonl.gz` contient au plus 128 réponses,
triées par identifiant numérique. Le nom indexe une plage inclusive ; il ne
contient ni nom de joueur, ni date modifiée, ni information d'authentification.
Le catalogue des assets de la release suffit : aucun manifeste central mutable
à publier atomiquement ou à récupérer après une interruption.

Les nouveaux lecteurs reconnaissent ces plages et ne chargent un lot que lorsque
`get(pid)` le nécessite. Les anciens journaux sans plage sont importés en entier,
comme avant. Les deux formats peuvent coexister : chaque lecture importe tous
les lots susceptibles de contenir le joueur, puis conserve sa réponse la plus
récente. Les anciens lecteurs peuvent toujours lire tous les nouveaux lots :
extension et schéma des réponses sont inchangés.

**Écriture et migration explicitement opt-in** :
`Checkpoints(..., remote=True, partitioned=True)` autorise l'écriture partitionnée ;
`compact_partitioned()` convertit l'inventaire complet. Aucune modification des
workflows réels n'active cette option. Un lecteur qui reprend une campagne déjà
partitionnée conserve ce format lors des écritures suivantes. Un ancien lecteur
reste compatible mais peut recompacter en monolithe et perdre le gain de vitesse.

### Sécurité de migration

- Le verrou externe de campagne reste obligatoire, partagé avec la maintenance.
- Avant compaction, charger **tous** les lots, même ceux des ligues jamais
  demandées, puis fusionner les réponses locales plus récentes.
- Envoyer **toutes** les partitions de remplacement avant la première suppression.
  Une interruption d'upload laisse les anciens lots ; une interruption de
  suppression laisse des doublons compatibles, jamais des réponses manquantes.
- Ne supprimer que les journaux présents dans l'inventaire initial ; garder
  les autres assets et le contenu de la release.
- Garder chaque `collected_at` et l'identifiant de campagne inchangés ; valider
  la campagne, le schéma et l'appartenance à la plage avant commit SQLite.
- Ne changer ni le marqueur de clôture, ni la rétention de 30 jours, ni les
  trois campagnes protégées, ni la confirmation de purge. Une campagne close
  reste refusée dès l'ouverture.
- Ne migrer aucune archive active sans autorisation spécifique.

### Mesure et limites

Le benchmark compare le lecteur actuel sur un monolithe et sur sa conversion
partitionnée. Chaque passage utilise un processus neuf ; chaque cas à froid a
son propre répertoire vide. Le temps **total** inclut les imports différés pendant
l'inventaire : le seul temps du constructeur serait trompeur.

Deux répartitions doivent être distinguées : les 600 premiers identifiants
(groupés) et 600 identifiants répartis sur toute la population. Les identifiants
TM ne sont pas ordonnés par ligue : une sélection réelle dispersée peut toucher
tous les lots et annuler le gain de transfert. Les 78 étiquettes de ligues servent
à vérifier la conservation, pas à prétendre reproduire leur distribution réelle.
Le format est donc une option compatible à évaluer sur un runner GitHub réel,
pas une promesse d'accélération de toute ligue.

Le découpage fixe augmente le nombre d'assets et de commandes réseau.
La compaction reste coûteuse et complète ; sa durée est mesurée séparément de la
reprise ciblée. Aucun transfert WAN ni coût HTTP n'est simulé. À grande échelle,
la limite d'assets GitHub doit être vérifiée avant activation (128 réponses par
lot, plus les lots transitoires de remplacement).

Reproduction du nouveau comparatif depuis la racine :

```bash
python artifacts/football-dashboard/scripts/benchmark_tm_checkpoint_restore.py \
  --output generated-artifacts/tm-partition-restore-new \
  --bytes 575938816 --players 600
python -m unittest discover -s artifacts/football-dashboard/tests -q
```

Le script vérifie aussi l'égalité SHA-256 de toutes les réponses canoniques
avant/après migration (données, dates, campagnes, tous les joueurs). Prévoir
environ 6 Go de disque ; les fichiers générés sont exclus de Git et du déploiement.
`--baseline` reste facultatif pour comparer un ancien lecteur.

Les tests couvrent restauration ciblée, compatibilité des anciens lecteurs,
formats mixtes, réponse la plus récente, réponse locale non envoyée, compaction
depuis un index partiel, toutes les ligues, mauvaise campagne, plage invalide,
interruption au second upload et interruption avant suppression. Les suites
existantes de clôture/purge sont conservées.

### Résultats du nouveau comparatif — 29 octobre 2026

Même population synthétique : **12 224 réponses / 78 étiquettes de ligues**,
monolithe de **575 996 551 octets**, converti en **96 partitions**
(557 473 980 octets). Les deux variantes utilisent le même lecteur actuel :
le gain ci-dessous vient du format distant, pas de l'ancien correctif SQLite.

| Format / sélection / disque | Total (s) | Pic RSS (Mio) | Octets téléchargés simulés | Lots téléchargés | Commandes `gh` |
|---|---:|---:|---:|---:|---:|
| Monolithe / 600 groupés / neuf | 28,731 | 32,01 | 575 996 551 | 1 | 3 |
| Partitions / 600 groupés / neuf | 3,325 | 31,87 | 29 182 133 | 5 | 7 |
| Monolithe / 600 groupés / reprise 1 | 0,289 | 29,11 | 0 | 0 | 2 |
| Partitions / 600 groupés / reprise 1 | 0,408 | 29,02 | 0 | 0 | 2 |
| Monolithe / 600 groupés / reprise 2 | 0,295 | 28,89 | 0 | 0 | 2 |
| Partitions / 600 groupés / reprise 2 | 0,386 | 29,02 | 0 | 0 | 2 |
| Partitions / 600 dispersés / neuf | 35,564 | 32,12 | 557 473 980 | 96 | 98 |

Pour la sélection groupée, **−94,9 % d'octets et un total 8,6× plus rapide**.
L'index local ne stocke que 60 329 984 octets contre 1 151 901 696 pour le
monolithe. Le démarrage seul dure 0,353 s, mais l'inventaire déclenche ensuite
2,972 s d'imports : les deux sont bien inclus dans le résultat.

Pour la sélection dispersée, tous les lots sont nécessaires : seulement −3,2 %
d'octets (compression), **24 % plus lent** dans cet essai local et beaucoup plus
de commandes réseau potentielles. Les reprises locales restent sans transfert,
mais la sélection des plages ajoute un petit surcoût. **Ne pas activer une
migration générale sur la seule base du cas groupé.**

La migration synthétique complète prend **68,720 s** (import initial, découpage,
upload simulé et suppression simulée). La lecture de contrôle de tous les joueurs
prend ensuite **30,174 s** et réimporte les nouveaux lots dans l'index :
**98,894 s au total**, pic RSS 33,39 Mio. Les 1 133 470 531 octets transférés
simulés pendant cette phase comprennent le monolithe et la relecture des partitions,
pas les uploads. Cette mesure ne doit pas être confondue avec une reprise ciblée.

L'égalité de contenu intégral, indépendante de SQLite, est confirmée pour les
12 224 réponses par SHA-256 canonique :
`55432382255225aabef5c6ff980d1bca5eded3324afb023f8179bc2ac35292ac`.
Elle inclut toutes les données de matchs et les dates originales.
Les résultats détaillés sont dans
`generated-artifacts/tm-partition-restore/results.json` (sortie locale ignorée).
La vérification intégrale et le passage dispersé ont été exécutés après les
six premiers passages, sans mesures concurrentes ; le script les inclut désormais.
L'ordre de mesure est fixe et le cache disque système n'est pas vidé.

**Validation : 181 tests réussis.** Workflow Streamlit redémarré, endpoint de
santé `ok`. Aucune archive active modifiée, aucune collecte, aucune publication
et aucune modification des règles de clôture/purge. La mesure sur un vrai runner
GitHub reste le travail distinct déjà prévu.

## Mesure précédente : index local — 29 octobre 2026

Le benchmark utilise **12 224 réponses synthétiques**, chacune contenant
120 matchs, réparties sur 78 étiquettes de ligues. L'archive compressée mesure
**575 996 551 octets**, contre 575 938 816 octets pour l'archive observée
(écart +0,01 %). Les détails de match pseudo-aléatoires empêchent une compression
artificiellement favorable de lignes répétées. Ce n'est pas une copie des vraies
réponses TM ni une mesure de leur distribution exacte.

Chaque mesure démarre un nouveau processus Python, restaure la campagne, puis
lit les réponses de 600 joueurs. « Reprise » signifie que le disque du runner
est conservé, pas que le processus ou ses objets restent en mémoire.
Le transport GitHub est remplacé par une copie locale du fichier : **aucune
requête GitHub ou Transfermarkt**, aucun délai réseau simulé. Le temps total
ci-dessous couvre restauration + inventaire, pas une collecte ni un export CSV.

| Version / passage | Restauration (s) | Inventaire (s) | Total (s) | Pic RSS (Mio) | Octets téléchargés simulés |
|---|---:|---:|---:|---:|---:|
| Avant / disque vierge | 38,865 | 0,196 | 39,060 | 33,23 | 575 996 551 |
| Avant / reprise 1 | 28,263 | 0,185 | 28,448 | 33,48 | 575 996 551 |
| Avant / reprise 2 | 22,076 | 0,183 | 22,260 | 33,79 | 575 996 551 |
| Après / disque vierge | 31,304 | 0,896 | 32,200 | 31,80 | 575 996 551 |
| Après / reprise 1 | 0,002 | 0,342 | 0,343 | 28,65 | 0 |
| Après / reprise 2 | 0,002 | 0,296 | 0,299 | 28,98 | 0 |

Les reprises sont **75 à 83 fois plus rapides** sur ces deux passages, et
évitent chacune 576 Mo de transfert simulé. Le premier import gagne environ
18 % sur le total, mais télécharge toujours toute l'archive.
Le stockage local passe de 1 141 116 665 à 1 151 901 696 octets (+0,95 %).
Les commandes GitHub simulées passent de trois à deux lors des reprises :
l'inventaire distant reste obligatoire ; seul le téléchargement disparaît.
Ce nombre compte les appels à `gh`, pas les requêtes HTTP internes de pagination.

Ces résultats ne constituent ni une mesure WAN GitHub ni une preuve d'accès
à Transfermarkt. L'ordre avant/après est fixe, le cache disque du système
n'est pas vidé ; ne pas extrapoler la petite amélioration à froid à tous les
runners. Le gain à chaud provient surtout du travail explicitement supprimé.

## Implémentation et garanties

- Index SQLite local dans le répertoire de **chaque campagne**, sans changement
  du format des releases, des journaux ou des règles de purge.
- Les lots distants restent immuables. Leur nom et leurs métadonnées d'identité
  servent de reçu local. Seuls les lots absents de l'index sont téléchargés.
- Import en flux, avec validation de toutes les réponses. Les réponses d'un lot
  et son reçu sont validés dans **la même transaction**. Un arrêt brutal avant
  commit ne marque jamais un import partiel comme terminé.
- `get()` lit le joueur demandé dans l'index et/ou dans sa réponse locale ;
  la plus récente gagne. Les dates originales sont conservées.
- Les nouvelles réponses restent des fichiers JSON atomiques avec fsync.
  Un envoi raté est repris grâce à ces fichiers, sans refaire la requête TM.
- La compaction parcourt **tous les joueurs de l'index et du disque local**,
  y compris les ligues non consultées par le processus courant. Envoi du nouveau
  lot avant suppression des anciens ; les assets étrangers ne sont pas supprimés.
- L'inventaire distant et la vérification de clôture précèdent toute utilisation
  de l'index. Une erreur réseau n'est pas interprétée comme une campagne vide.
- Supprimer l'index local entraîne sa reconstruction depuis les sauvegardes.
  Une corruption SQLite provoque un échec explicite, pas une collecte vide.

L'index n'est pas un nouveau service de stockage ni une migration de la base
applicative : c'est un cache dérivé des journaux GitHub. Les anciennes réponses
locales et les sauvegardes distantes restent compatibles avec les anciens outils.
Il suppose, comme les checkpoints précédents, le verrou externe de collecte.

### Limite conservée

Un runner neuf, ou un disque dont l'index a été supprimé, doit télécharger et
indexer les journaux disponibles. Cette optimisation cible les processus par
ligue partageant un même runner. Une restauration distante réellement sélective
sur un runner neuf nécessiterait de partitionner les anciennes archives et de
valider une migration ; aucune archive active n'a été modifiée pour ce travail.
La couverture hebdomadaire, l'hébergement et les autorisations de reprise sont
inchangés.

## Reproduction

Depuis la racine de ce dépôt, avec la révision de référence disponible :

```bash
mkdir -p generated-artifacts
git show 1804f4958abe4662da17a36c7052005de62f30fe:artifacts/football-dashboard/tm_career_checkpoints.py \
  > generated-artifacts/tm_checkpoints_before.py
python artifacts/football-dashboard/scripts/benchmark_tm_checkpoint_restore.py \
  --baseline generated-artifacts/tm_checkpoints_before.py \
  --output generated-artifacts/tm-restore
python -m unittest discover -s artifacts/football-dashboard/tests -q
```

Utiliser un répertoire de sortie neuf pour chaque benchmark. Le script produit
`results.json` ainsi que l'archive et les caches locaux, exclus de Git et des
déploiements. Prévoir environ 3 Go de disque. Le baseline est la version qui
avait déjà supprimé les fsync par réponse restaurée.

**Validation : 139 tests réussis**, incluant les suites de rétention, de
transactions d'exports et de file de collecte. Les nouveaux cas couvrent :
réutilisation sans téléchargement, nouveau lot uniquement, suppression de
l'index, rollback d'un import invalide, mort du processus au milieu d'une
transaction, mauvaise campagne, réponse la plus récente, ligue non consultée
conservée pendant la compaction, arrêt après upload avant suppression,
et indisponibilité distante malgré un index chaud.

Le serveur Streamlit redémarre et son endpoint de santé répond `ok`.
Aucune collecte ni publication n'a été déclenchée.
