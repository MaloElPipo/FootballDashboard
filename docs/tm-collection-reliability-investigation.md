# Enquête collecte fiable et rapide — 28 octobre 2026

## Périmètre et preuves

Inspection du code local, du workflow `scrape-weekly.yml` sur `main` GitHub,
des rapports d'endurance et des effectifs au commit
`0310737be965236467b9c502936322521d14fcf1`. Aucune nouvelle requête
Transfermarkt pour cette enquête. Les CSV sources ont été lus depuis GitHub
dans `/tmp`, avec vérification des SHA-256 contre la fenêtre 2.

Au moment de l'enquête, deux fenêtres avaient réussi 120 GET chacune.
La troisième a ensuite réussi elle aussi : 360 GET sur les mêmes 120 joueurs,
pas 360 joueurs distincts. Elles ne reproduisent pas la collecte de production.
Les derniers runs GitHub affichent « success », mais les étapes de scraping
tolèrent les erreurs : ce statut ne prouve pas une actualisation complète.
Les logs historiques détaillés n'ont pas été analysés ici ; la cause exacte
du changement de comportement du service n'est donc pas établie.

## Constats vérifiables

1. **Le workflow utilise déjà cinq workers**, malgré le défaut Python de trois.
   Chaque worker attend 0,30 à 0,60 seconde, sans régulateur de débit global.
   C'est très différent de la sonde : un worker, dix secondes entre GET.
2. **Timeout fixe de 240 secondes par ligue.** Les effectifs saison maximale
   + précédente des douze ligues testées représentent 9 085 participations,
   soit 8 774 joueurs distincts. Une ligue compte jusqu'à 1 162 joueurs.
   Pour celle-ci, finir en quatre minutes exige au moins 4,84 joueurs/s,
   avant même le coût d'initialisation. Ce calcul est une contrainte
   arithmétique, pas un débit observé ou autorisé.
3. **Pas de reprise durable par joueur.** Les résultats sont accumulés en
   mémoire ; les exports ne sont préparés qu'après la fin de la ligue.
   Un échec préserve les anciens CSV, mais les réponses déjà obtenues ne
   constituent pas un checkpoint réutilisable. Une reprise refait la ligue.
4. **Reprises imbriquées.** Le workflow continue avec la ligue suivante,
   refait les ligues KO puis peut déclencher un nouveau workflow de rattrapage.
   Sans propagation de l'arrêt global, un blocage peut engendrer du trafic
   inutile. Ce correctif relève du chantier déjà prévu, pas de cette enquête.
5. **Rafraîchissement d'effectifs plus large que la sélection.** L'étape
   `--refresh-current` n'est pas filtrée par les ligues demandées dans le
   workflow. Un petit rattrapage peut donc déclencher du travail sur toutes
   les ligues. Le mode global reste pertinent pour un renouvellement complet.
6. **Petite marge de déduplication entre ligues, gros gain potentiel sur les
   reprises.** Sur les douze ligues, 311 participations sont des doublons
   interligues (3,4 %). La déduplication seule ne résoudra pas le problème ;
   ne plus recommencer les joueurs déjà réussis est le levier principal.

## Recommandation

### Priorité 1 — rendre chaque réussite réutilisable

Ajouter un stockage durable des réponses validées par identifiant joueur,
avec horodatage, version de format, état de campagne et écriture atomique.
Ne pas stocker de cookie ni d'en-tête d'authentification. Une reprise utilise
les succès de **la même campagne** et ne réclame que les éléments manquants.
Définir séparément une politique de fraîcheur pour une nouvelle campagne :
un cache ancien ne doit jamais être présenté comme nouvellement collecté.

Conserver les exports publics précédents jusqu'à ce que tous les joueurs
requis pour une ligue soient disponibles et validés. Persister les checkpoints
avant la fin du job et survivre à sa disparition ; `/tmp` et un upload en
dernière étape ne suffisent pas. Un stockage durable ou des lots persistés
régulièrement sont nécessaires.

### Priorité 2 — dissocier budget, débit et publication

Remplacer le timeout arbitraire par un budget explicite de campagne et une
sortie propre avec checkpoint. Introduire un régulateur **global**, partagé
entre workers. Garder les arrêts CAPTCHA/refus et ne pas lancer automatiquement
une nouvelle session après un blocage. La vitesse acceptable reste à mesurer
sous autorisation ; les sondes actuelles ne permettent pas de fixer un seuil.

La protection du portail incomplet, l'arrêt global, les CSV courants et les ZIP
ont déjà leurs chantiers distincts. Ne pas les dupliquer ni les contourner.
Un opérateur doit pouvoir publier uniquement les ligues complètes tout en
conservant les autres avec leur ancienne date de fraîcheur.

### Priorité 3 — accélérer seulement le travail utile

Limiter le refresh des effectifs aux ligues demandées lors d'un run ciblé.
Dédupliquer les joueurs entre ligues ; paralléliser librement les traitements
locaux (agrégation, validation, construction des exports), mais faire passer
toutes les requêtes source par le même budget de débit.

Plusieurs agents de collecte ne créent pas de capacité autorisée supplémentaire.
Un serveur AWS WAF peut agréger sur plusieurs critères, pas seulement l'IP :
[documentation AWS](https://docs.aws.amazon.com/waf/latest/developerguide/waf-rule-statement-type-rate-based-aggregation-options.html).
La configuration réelle de Transfermarkt n'est pas connue. Aucune rotation
d'identité ou résolution automatique de CAPTCHA n'est proposée.

Si les besoins de fraîcheur restent incompatibles avec le débit accessible,
évaluer un accès autorisé/licencié ou un fournisseur alternatif **après**
inventaire des champs indispensables (historique, minutes, compétitions,
identifiants). Aucune équivalence de couverture ou de coût n'est établie ici.

## Ce qui n'est pas conclu

- Aucun débit rapide et stable n'a encore été démontré.
- Aucun délai fiable pour une collecte complète ne peut être annoncé.
- L'accès n'est pas indisponible : 360 GET ont réussi sur trois fenêtres.
- Le protocole d'endurance de trois fenêtres est terminé ; la troisième
  a été avancée sur autorisation explicite, sans augmentation du budget.
  Voir `tm-http-diagnostic.md` pour les mesures et limites d'interprétation.
  Cette enquête n'a déclenché aucune collecte de production.
