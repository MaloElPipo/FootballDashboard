# Audit ELO vs marché Pinnacle — 3-way CDM 2026

Source cotes : **live** (TheOddsAPI, bookmaker=pinnacle). Matchs analysés : **63** (de-vig Buchdahl). Modèle : sigmoid_v8_1x2 prod + Elo prod.

## 1. Proximité globale modèle / marché

| Métrique | Valeur | Lecture |
|---|---|---|
| TVD moyenne | 3.44% | écart total moyen entre les 2 distributions 1X2 |
| TVD médiane / max | 2.66% / 14.16% | la moitié des matchs < médiane |
| Accord sur le favori | 93.7% | même issue favorite que Pinnacle |
| Corrélation proba-favori | 0.954 | quasi-linéaire = bien calibré |
| Biais signé H / D / A | -0.25% / -0.67% / +0.92% | ~0 = pas de biais structurel |
| Gap proba favori | -0.54% | <0 = modèle légèrement moins tranché que le marché |

**Conclusion** : le modèle Elo colle très bien au marché sur le 3-way (TVD 3.4%, accord favori 94%, corr 0.95). Base saine pour les paris long terme.

## 2. Classement Elo : où on diverge du marché (signal long terme)

Elo implicite marché = moindres carrés sur les deltas inversés (même sigmoid), ancré à la moyenne de notre Elo.

### On SUR-cote vs marché (notre Elo trop haut → risque de sur-parier en outright)
| Nat | Elo prod | Elo marché | Δ |
|---|---|---|---|
| SEN | 1858 | 1757 | +101 |
| IRQ | 1560 | 1476 | +84 |
| ARG | 2126 | 2043 | +83 |
| NOR | 1947 | 1866 | +81 |
| JOR | 1638 | 1559 | +79 |
| FRA | 2121 | 2042 | +79 |
| UZB | 1671 | 1593 | +78 |
| AUS | 1740 | 1674 | +66 |
| PAR | 1816 | 1757 | +59 |
| COL | 1969 | 1912 | +57 |

### On SOUS-cote vs marché (notre Elo trop bas → valeur possible côté marché)
| Nat | Elo prod | Elo marché | Δ |
|---|---|---|---|
| QAT | 1429 | 1546 | -117 |
| RSA | 1553 | 1657 | -104 |
| CAN | 1764 | 1865 | -101 |
| SUI | 1854 | 1944 | -90 |
| BEL | 1932 | 2009 | -77 |
| MEX | 1864 | 1935 | -71 |
| CZE | 1714 | 1784 | -70 |
| EGY | 1724 | 1792 | -68 |
| CIV | 1722 | 1787 | -65 |
| GER | 1986 | 2049 | -63 |

## 3. Top 15 écarts 1X2 par match (value potentielle ou faiblesse modèle)

| Match | Modèle H/D/A | Marché H/D/A | TVD |
|---|---|---|---|
| GHA-PAN | 34/28/38 | 48/25/27 | 14.2% |
| CRO-GHA | 64/21/15 | 55/26/19 | 8.5% |
| USA-PAR | 39/28/32 | 47/28/25 | 8.0% |
| TUN-JPN | 19/23/58 | 21/28/50 | 7.9% |
| CIV-ECU | 24/26/49 | 25/34/41 | 7.9% |
| ECU-GER | 25/26/49 | 19/24/57 | 7.8% |
| USA-AUS | 47/26/26 | 54/24/22 | 7.1% |
| BEL-IRN | 60/22/18 | 67/21/13 | 6.8% |
| TUR-USA | 40/28/31 | 35/28/37 | 6.1% |
| TUN-NED | 14/20/67 | 16/23/61 | 5.8% |
| RSA-KOR | 23/26/51 | 26/28/45 | 5.6% |
| JOR-ALG | 22/26/53 | 18/24/57 | 4.9% |
| HAI-SCO | 17/22/61 | 15/19/66 | 4.8% |
| POR-UZB | 72/18/10 | 77/15/8 | 4.7% |
| BRA-MAR | 54/26/20 | 59/25/16 | 4.5% |

## 4. Limites / données manquantes

- **6 matchs ignorés** : nations absentes de l'Elo prod → **Autriche (AUT)** et **Bosnie (BIH)** qualifiées mais non notées. À ajouter pour une couverture complète.
- 3 matchs sans 1X2 Pinnacle (handicap-only, ex Allemagne-Curaçao) — non couverts par le marché.
- De-vig proportionnel (Buchdahl) ; une de-vig par la méthode du favori-longshot donnerait des probas favori légèrement plus hautes.