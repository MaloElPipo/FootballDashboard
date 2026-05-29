---
name: Biais "favoris sous-cotes" CDM = avantage hote manquant
description: Pourquoi le modele V8 semble sous-coter les favoris vs Pinnacle, et la vraie cause (pas la sigmoid).
---

# "On sous-cote les favoris" CDM : c'est l'avantage hote, pas la sigmoid

Audit 1X2 modele (`sigmoid_v8_1x2`) vs Pinnacle de-vigge (Buchdahl) sur les
matchs de poule. Le ressenti "on sous-cote les favoris" est reel en agrege
(fav_gap ~ -0.7%, bias away ~ +1.1%) mais sa cause n'est PAS la forme de la
sigmoid :

- Par tier de proba favori marche, le modele est calibre a **±1%** (pas de
  sur/sous-confiance systematique).
- Spread Elo correct : delta_implicite ≈ 0.89×delta_reel, gap moyen ~+3 Elo.
- **Cause dominante = avantage hote absent.** La sigmoid ne depend que du delta
  Elo, sans terme domicile. Sur les 6 matchs hotes (USA/MEX/CAN a domicile) le
  marche favorise l'hote de **~+8.5 pts** (home−away) de plus que le modele
  (~+44 Elo implicites). Sur les matchs neutres l'ecart est negligeable (~+1 pt).
- Reste = erreurs Elo par nation (on sur-cote ARG/FRA/NOR/SEN/JOR, on sous-cote
  BIH/CAN/QAT/SUI/RSA), visibles sur les gros ecarts 1X2 par match.

**Regle** : pour "se calibrer sur le marche" sur la CDM, ajouter un terme
avantage hote (~+40 Elo pour USA/MEX/CAN uniquement) AVANT de toucher aux
params de la sigmoid. Hotes CDM 2026 = USA, MEX, CAN (PAS le Qatar).

**Piege source Elo** : un audit "vs Elo prod" doit lire l'Elo via
`elo_engine.compute_all_nations_elo()` (resolution complete : elorating base +
BSD adj + pin calib + overrides, ~48 nations dont AUT/BIH), PAS le sous-ensemble
`pin_calibrated_elo.json` (46 nations, sans AUT/BIH) — sinon on perd des matchs
par faux "elo_manquant".
