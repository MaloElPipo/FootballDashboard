# Audit Elo vs marche Pinnacle — 3-way CDM 2026

Source : **live** (TheOddsAPI, bookmaker=pinnacle). Matchs : **69** (de-vig Buchdahl). Elo : `compute_all_nations_elo` prod live (48 nations).

## 1. Proximite globale modele / marche

| Metrique | Valeur |
|---|---|
| TVD moyenne / mediane / max | 4.10% / 2.76% / 14.16% |
| Accord favori | 92.8% |
| Correlation proba-favori | 0.925 |
| Biais signe H/D/A | -0.43% / -0.68% / +1.11% |

## 2. Diagnostic du biais favoris

- **Spread Elo** : delta_implicite ≈ 0.89×delta_reel +27 ; gap moyen +3 Elo → spread quasi correct, **pas** de compression systematique.
- **Calibration par tier de proba favori marche** (gap = modele − marche) :

| Tier | n | fav marche | fav modele | gap |
|---|---|---|---|---|
| 0.40-0.55 | 24 | 48.1% | 47.2% | -0.9% |
| 0.55-0.70 | 25 | 61.3% | 61.4% | +0.0% |
| 0.70-0.85 | 14 | 74.7% | 73.6% | -1.1% |
| 0.85-1.01 | 1 | 85.5% | 86.0% | +0.5% |

- **Avantage hote non modelise (effet dominant)** : la sigmoid est purement fonction du delta Elo, sans terme domicile.
  - Matchs hote (USA/MEX/CAN a domicile, n=6) : le marche favorise l'hote de **+8.5 pts** (home−away) de plus que le modele.
  - Matchs neutres (n=63) : ecart **+0.9 pts** → negligeable.

**Conclusion** : le sous-cotage des favoris vient surtout de l'**avantage hote absent** (+~40 Elo implicites pour USA/MEX/CAN) et d'erreurs Elo par nation, **pas** de la forme de la sigmoid (bien calibree a ±1%).

## 3. Classement Elo : ecarts vs marche (signal long terme)

### On SUR-cote (Elo trop haut → prudence outrights)
| Nat | Elo prod | Elo marche | Δ |
|---|---|---|---|
| JOR | 1638 | 1524 | +114 |
| SEN | 1858 | 1753 | +105 |
| ARG | 2126 | 2024 | +102 |
| IRQ | 1560 | 1472 | +88 |
| NOR | 1947 | 1862 | +85 |
| FRA | 2121 | 2038 | +83 |
| UZB | 1671 | 1589 | +82 |
| AUS | 1736 | 1670 | +66 |
| PAR | 1816 | 1753 | +63 |
| COL | 1969 | 1908 | +61 |

### On SOUS-cote (Elo trop bas → value cote marche)
| Nat | Elo prod | Elo marche | Δ |
|---|---|---|---|
| BIH | 1581 | 1736 | -155 |
| CAN | 1764 | 1884 | -120 |
| QAT | 1429 | 1548 | -119 |
| SUI | 1854 | 1957 | -103 |
| RSA | 1553 | 1653 | -100 |
| BEL | 1932 | 2005 | -73 |
| USA | 1790 | 1860 | -70 |
| MEX | 1864 | 1931 | -67 |
| CZE | 1714 | 1780 | -66 |
| EGY | 1724 | 1787 | -63 |

## 4. Top 15 ecarts 1X2 par match

| Match | Modele H/D/A | Marche H/D/A | TVD |
|---|---|---|---|
| GHA-PAN | 34/28/38 | 48/25/27 | 14.2% |
| USA-PAR | 33/28/38 | 47/28/25 | 13.7% |
| USA-AUS | 41/28/31 | 54/24/22 | 13.5% |
| AUT-JOR | 60/22/18 | 71/18/11 | 11.5% |
| TUR-USA | 46/27/27 | 35/28/37 | 11.2% |
| BRA-MAR | 49/26/25 | 59/25/16 | 10.1% |
| TUN-JPN | 18/22/60 | 21/28/50 | 9.9% |
| CRO-GHA | 64/21/15 | 55/26/19 | 8.5% |
| JOR-ALG | 25/26/49 | 18/24/57 | 8.4% |
| TUN-NED | 13/19/69 | 16/23/61 | 7.6% |
| CIV-ECU | 25/26/49 | 25/34/41 | 7.5% |
| ECU-GER | 24/26/49 | 19/24/57 | 7.3% |
| BEL-IRN | 60/22/18 | 67/21/13 | 6.8% |
| BIH-QAT | 51/26/23 | 58/25/17 | 6.7% |
| SCO-MAR | 22/26/52 | 24/30/46 | 5.6% |