---
name: WC bracket "Bracket complet" = arbre connecté (modal R32 + avancée vainqueurs)
description: pourquoi le bracket MC n'utilise PAS l'occupant modal par slot pour tous les tours
---

`simulate_bracket_mc` (wc_simulator.py, onglet « Bracket complet » de la page Prédictions)
remplit les 32 slots du R32 par l'occupant le plus fréquent (modal) sur N sims, puis FAIT
AVANCER le vainqueur projeté de chaque duel pour les tours suivants. Les cotes par duel
restent empiriques (fréquences H2H de la même sim) avec repli Sigmoid V8 phase KO sur l'ELO
post-poules moyen.

**Why:** une revue a proposé « occupant modal indépendant par slot pour TOUS les tours ».
Refusé volontairement : ça produit un arbre DISJOINT (une équipe peut s'afficher en finale
sans être affichée gagnante de sa demie), ce qui contredit la demande explicite de l'user
« bracket COHÉRENT ». L'avancée des vainqueurs garantit un arbre connecté et lisible.

**How to apply:** ne pas « corriger » en réactivant des occupants modaux r16+ — c'est un
choix produit. Les compteurs occ_home/occ_away ne servent qu'au R32 ; h2h sert à toutes les
manches pour les cotes.
