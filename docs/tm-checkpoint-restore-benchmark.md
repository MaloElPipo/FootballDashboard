# Restauration indexée des sauvegardes TM

## Périmètre et résultats hors ligne — 29 octobre 2026

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
