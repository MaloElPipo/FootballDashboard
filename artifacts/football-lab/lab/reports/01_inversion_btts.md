# Report Phase 1 — Triple inversion BTTS

Status : **DRAFT** (algo livre, calibration unitaire OK, backtest BSD a lancer manuellement depuis la page Streamlit)

## Probleme

L'inversion actuelle prod (Poisson independants `lambda_h`, `lambda_a`) calee sur
1X2 + Over 2.5 ignore le marche BTTS. Resultat : le BTTS implicite par notre
modele peut s'ecarter de plusieurs points de % du BTTS marche (Pinnacle 14 books),
ce qui biaise :

- les buteurs (P(scorer) sous-evaluee pour les equipes a defense fragile)
- les corner kicks / first scorer (correle a `lambda_a`)
- le ROI Pinnacle close sur BTTS et sur les marches derives

## Methode nouvelle : Dixon-Coles 3 parametres

PMF :
```
P(x, y) = tau(x, y) * Pois(x; lambda_h) * Pois(y; lambda_a)
```
avec `tau` qui n'agit que sur les 4 cellules basses 0-0, 0-1, 1-0, 1-1 :
```
tau(0,0) = 1 - lambda_h * lambda_a * rho
tau(0,1) = 1 + lambda_h * rho
tau(1,0) = 1 + lambda_a * rho
tau(1,1) = 1 - rho
```

Optimisation : `scipy.optimize.least_squares` sur 5 residuels ponderes
(1, X, 2 : poids 1.0 ; O2.5 : 1.2 ; BTTS : 1.5).

Bornes : `lambda` dans [0.05, 6.0], `rho` dans [-0.4, 0.4] (bornes Dixon-Coles
en pratique respectees pour football pro).

## Test unitaire — preset "match equilibre, beaucoup de buts"

Marche : P(1)=0.50, P(X)=0.27, P(2)=0.23, P(O2.5)=0.55, P(BTTS)=0.52

| Methode | lambda_h | lambda_a | rho    | residuel BTTS |
|---------|----------|----------|--------|---------------|
| Double  | 1.7144   | 1.1264   | 0.0    | **+0.0541**   |
| Triple  | 1.6931   | 1.0638   | -0.058 | **+0.0211**   |

**Le residuel BTTS est divise par 2.5** sans degrader 1X2/O2.5 (residuels < 3pp
sur toutes les contraintes). `rho` negatif = bas scores boostes vs Poisson pur,
ce qui est le pattern classique Dixon-Coles 1997.

## Critere go/no-go (a valider sur backtest 100 matchs PL)

Trois conditions cumulatives pour basculer la prod :

1. **|residuel BTTS| triple < 50 % de |residuel BTTS| double** sur >= 80 % des matchs
2. **Log-loss 1X2 triple <= log-loss 1X2 double + 0.002** (degradation tolerable
   sur 1X2 si BTTS gagne beaucoup, mais pas plus)
3. **Taux d'echec optimiseur (ok=False) < 5 %**

## Coverage BSD a verifier

Les endpoints reels BSD pour compareOdds peuvent ne pas renvoyer 1X2 + O/U 2.5 +
BTTS systematiquement. La fonction `match_fetcher.extract_market_probs` est
defensive (None si l'un des marches manque). Le taux de couverture sera reporte
ici apres le 1er backtest. Si < 70 %, on degrade gracefully (utiliser TheOddsAPI
en fallback pour BTTS).

## Prochaines actions

- Lancer le backtest depuis l'onglet "Backtest log-loss" sur 30 matchs PL season 2024
- Coller ici le tableau resultats + decision GO/NO-GO sur les 3 criteres
- Si GO : extension du backtest a La Liga, Serie A, Bundesliga, Ligue 1
- Si NO-GO sur BTTS : explorer ponderation differente (poids BTTS = 2.0) ou
  modele bivariate Poisson (Karlis-Ntzoufras) avec parametre lambda_3 commun

## Fichiers

- `lab/calibration/invert_market.py` — algos `invert_double` / `invert_triple` / `derived_probs`
- `lab/calibration/match_fetcher.py` — wrappers BSD compareOdds + extraction marches
- `lab/pages/phase1_btts.py` — UI Streamlit 3 tabs (manuel / match BSD / backtest)
- `lab/reports/backtest_<league>_<season>.csv` — output backtest persiste
