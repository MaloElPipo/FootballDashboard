---
name: WC sim — buts de poule = xG continu (pas de buts entiers)
description: Pourquoi toute distribution de buts marqués en poule CDM exige un tirage discret séparé, découplé de l'issue 1X2.
---

# Simulateur CDM — les buts de poule sont des xG continus

Dans `wc_simulator.simulate_tournament`, le classement de poule accumule des
**buts attendus continus (xG)** par match (`derive_lambdas_from_elo` ou
`expected_scores` marché), pas des buts entiers tirés au sort. C'est voulu :
plus stable et plus précis pour le goal-average de départage (`_rank_group`).

Conséquence : `avg_gf`/`avg_ga` sont des espérances continues, et il
**n'existe aucune distribution de buts entiers** native dans la sim.

**Why:** un tirage discret par match introduirait du bruit dans les égalités de
classement ; le modèle privilégie un goal-average déterministe par match.

**How to apply :** pour exposer une distribution « P(l'équipe marque N buts) »
(ou tout marché O/U buts marqués), ajouter un **tirage Poisson discret séparé**
cumulé sur les 3 matchs, **sans** toucher l'accumulation xG du classement.

Subtilité importante : l'issue du match (W/N/D → points) est tirée du **1X2
marché/sigmoïde**, indépendamment des buts. Donc buts discrets et résultat ne
sont **pas couplés** : les distributions points/classement d'un côté et buts
marqués de l'autre sont des **marges indépendantes**, à présenter comme telles
(ne pas laisser croire à une jointe score↔résultat).
