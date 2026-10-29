# Collecte TM : diagnostic et conditions de validation

## État observé le 29 octobre 2026

47 des 67 championnats en retard ont été collectés puis vérifiés dans les deux
archives publiques. Le Canada a provoqué le dernier arrêt global, sur CAPTCHA.
Ne pas relancer cette campagne automatiquement après un refus d'accès.

Les codes 502, les épuisements de budget et les CAPTCHA sont des causes
distinctes. Les erreurs 403/405 sont des réponses de la source ; les journaux
ne prouvent pas que GitHub en est la cause principale.

## Problèmes établis par inspection

- La restauration relit les journaux de toute la campagne à chaque processus.
  L'archive principale distante observée pesait 575 938 816 octets.
- La restauration effectuait deux fsync par réponse réécrite localement,
  alors que ces réponses étaient déjà durables sur GitHub.
- L'inventaire local des joueurs manquants consommait le budget réseau.
- Cinq travailleurs avaient chacun leur propre pause, sans cadence commune.
- Une tentative incomplète ne distinguait pas le budget du refus d'accès.

## Correctifs locaux et vérification hors ligne

Les restaurations conservent le remplacement atomique mais n'imposent plus
de fsync : une interruption se répare par relecture du journal distant.
Les nouvelles réponses conservent leurs fsync et leur publication durable.
Le budget démarre après l'inventaire local, avant le démarrage du navigateur.
Deux travailleurs et une pause partagée limitent les départs de joueurs.
Ce réglage ne garantit ni l'absence de CAPTCHA ni une réduction du temps total.
Les essais réseau internes restent soumis aux garde-fous existants.

Les lignes TM_PHASE mesurent restauration, inventaire, démarrage du navigateur
et dernier envoi de sauvegarde. Les nombres reused/missing permettent de
vérifier les reprises sans interpréter une date de fichier comme de la fraîcheur.

Les tests couvrent notamment la reprise après interruption de restauration,
la conservation des fsync pour les nouvelles réponses, l'inventaire local lent,
les exports partiels refusés et l'arrêt global sur refus.

## Ce qui n'est pas encore démontré

- Gain réel sur une archive représentative : tester avec des réponses
  synthétiques, sans solliciter Transfermarkt, puis comparer par phase.
- Fiabilité autonome hebdomadaire et durée acceptable pour 78 ligues.
- Faisabilité d'une source ciblée saison courante : ne pas modifier la
  couverture ni la fraîcheur historique sans accord.
- Meilleure acceptation réseau sur un autre hébergement.

## Étapes suivantes et critères de décision

1. Évaluer la restauration sélective/indexée et un stockage persistant avec
   des données synthétiques représentatives. Mesurer temps, mémoire, requêtes
   GitHub et octets transférés ; conserver les campagnes isolées et les dates.
2. Construire une file durable de ligues restantes. Reprises bornées avec
   attente progressive pour erreurs temporaires, vérification du run existant
   si un dispatch est incertain, suspension persistante sur refus d'accès.
3. Tester interruptions, redémarrages, sauvegarde indisponible, doublons,
   publication retardée et suppression accidentelle d'un cache local.
4. Seulement après ces validations, essai réel limité et autorisé, avec arrêt
   sur refus. Ne pas qualifier la solution d'autonome sur un seul run réussi.

Les modifications de collecte ne doivent jamais déclencher une collecte à
elles seules. Une validation hors ligne n'est pas une preuve d'accès à la source.
