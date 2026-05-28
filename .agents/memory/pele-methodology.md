---
name: PELE methodology (Silver Bulletin)
description: Formules, multipliers, et sources CSV publiques pour reproduire ou comparer PELE.
---

# PELE — méthodologie officielle

Article méthodo de Silver est **libre** (pas paywall) à `natesilver.net/p/pele-methodology`.
Copie texte propre dans `.local/refs/pele_paywall/methodology_clean.txt` (~58 KB).
**Toujours chercher la doc méthodo publique AVANT de reverse-engineer un modèle externe** — le contenu des CSV paywall sans la méthodo conduit à des reconstructions fausses.

## Architecture en 2 phases

| | Phase 1 | Phase 2 |
|---|---|---|
| Mécanisme | Elo zero-sum classique, **mais sur h-margin** (chaque but additionnel pèse 1/n) | Mean-reversion gradient quotidien vers prior Transfermarkt (valeur 23 joueurs) |
| Données | résultats matchs + GDP prior + region + legacy year | valeurs marché + âges joueurs (depuis 2005) |
| K-factor | bas | légèrement plus haut |

**Why Phase 2 matters:** sans Phase 2 (donc juste Elo from results), une équipe forte sur le papier (gros roster Transfermarkt) peut s'effondrer après une série de friendlies ratés. Phase 2 = plancher structurel ancré sur la valeur des joueurs.

## Tilt rating est ORTHOGONAL au PELE rating

- **PELE rating** = qualité globale → utilisé pour 1X2 et spread
- **Tilt rating** = propension goals (attaque/défense) → utilisé pour O/U
- Combinés via **négative binomiale avec terme de corrélation** (PAS Poisson pur — Silver dit explicitement que Poisson sous-estime à la fois les nuls 0-0 et les blowouts type 7-1)

## Match importance multipliers (cadeau direct)

| Compétition | K mult |
|---|---:|
| Friendlies | 0.5 – 0.7× |
| Mini tournois / friendly tournois | 0.7 – 0.9× |
| Tournois régionaux et JO (qualif → final) | 0.7× → 1.0× |
| Continentaux Euro/Copa (qualif → final) | 1.3× → 1.4× |
| **World Cup (qualif → final)** | **1.5× → 1.6×** |

Spread d'environ 3× entre friendly et CDM principale.

## World Cup specific tweaks (à appliquer sur nos sims CDM)

1. **0.9× sur Δ PELE en group stage** (matchs plus upsets que default)
2. **1.1× sur Δ PELE en KO stage** (matchs plus chalk que default)
3. **MD3 collusion :** si nul qualifie les 2 (sans clinch) → **-1 but expected total**
4. **MD3 do-or-die :** si win-needed pour les 2 (sans élim) → **+1 but expected total**
5. HFA par **altitude du venue spécifique** (Mexico City ≠ Monterrey)
6. K-factor relevé pendant tournoi pour modéliser "form" (chaque match update les ratings pour le reste de la sim)
7. Roster = 23 sélectionnés parmi les 26 officiels, pas algo Transfermarkt
8. Cards/bookings simulés pour Fair Play tiebreaker (qu'on remplace nous par Elo)

## CSVs Datawrapper publics — oracle direct

Headers `User-Agent` navigateur obligatoire (urllib default → 403).
URL pattern : `https://datawrapper.dwcdn.net/<id>/1/data.csv`

## Paramètres de reconstruction λ calibrés sur 72 matchs CDM 2026 vraies PELE

Formule : `λ_h = baseline × (1 + α·(tilt_h+tilt_a)) × exp(scale × Δ_PELE / 600)`

| Param | Valeur calibrée | RMSE λ atteint |
|---|---:|---:|
| baseline | 1.35 buts/équipe/match | |
| scale_delta | 1.2 (vs intuition initiale 0.5 — **2.4× plus pentu**) | |
| alpha_tilt | 0.2 (vs intuition initiale 0.4 — **÷2**) | |
| **Tous combinés** | | **0.244 but/match** |

**Why:** sans Phase 2 Transfermarkt, on ne peut pas reproduire exactement les ratings PELE, mais avec ces 3 params on reproduit fidèlement la **transformation rating → λ**. La pente raide (scale=1.2) signifie que pour 100 pts PELE de delta, λ_h/λ_a × ~1.18.

**How to apply:** quand on a besoin d'un λ "PELE-like" depuis un Elo connu, utiliser ces 3 params. Le WC group-stage shrink 0.9× s'applique ENSUITE sur (lh-la).

## Paramètres WC group-stage shrink — confirmation empirique

Le 0.9× sur Δ PELE en group stage rapproche vraie PELE de Pinnacle :
- MAE vs Pinnacle : 6.23 → 5.27 (-0.96 pts)
- Biais favori : +4.34 → +1.99 (-54%)
Implementation : `wc_shrink_1x2()` log-odds par rapport au draw, `wc_shrink_lambdas()` shrink (lh-la) en preservant tot.

## CSVs Datawrapper publics — oracle direct

| ID | Contenu | Taille |
|---|---|---|
| `SBs0a` | **211 nations : PELE + Tilt officiels** (oracle direct) | ~6 KB |
| `VAVO6` | HFA historique mondial depuis 1872 (par date) | ~300 KB |
| `w8a4E` | Table conversion raw margin → h-margin | <1 KB |
| `1mqG4` | Score matrix exemple USA-PAR | ~250 B |
| `aRfjE` | Allocation offensive/défensive par position joueur | ~300 B |
| `DcqkH` | 211 équipes : Tilt/PELE/GF/GA/W/D/L Round-Robin | ~6 KB |

Note : les IDs Datawrapper peuvent changer à chaque update PELE (1× par jour environ). Re-extraire depuis l'article méthodo si broken.

## Régions Silver (≠ confédérations FIFA)

12 régions avec overlap. Ordre de prédictivité résiduelle (après contrôle GDP + legacy year) :
Latin Am > West Africa > Europe > North Africa > Caribbean > East Africa > Middle East > Ex-USSR > North Am > Oceania > East Asia > South Asia.
Mexique = hybride Nord-Am + Latam. Indonésie = Asia + Oceania. Baltes = Ex-USSR + Europe.

## Autres détails utiles

- HFA non-linéaire avec altitude (10 000 ft > 2× plus dur que 5 000 ft)
- Travel distance compte plus pour matchs neutres que home/road
- Provisional period pour nouvelles nations : K plus haut sur ~100 premiers matchs internationaux
- Penalty shootouts ≈ 50/50 avec edge max 60/40 pour le favori
- 40% des nuls réguliers résolus en prolongation, 60% vont aux tirs au but
- Roster CDM 2026 : ils utiliseront le **roster officiel 26 joueurs** (sélectionnent les 23 meilleurs) pour la sim finale, pas l'algo Transfermarkt
