# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: playwright_test.spec.ts >> Verify lineup pitch component formations
- Location: playwright_test.spec.ts:4:5

# Error details

```
TimeoutError: locator.waitFor: Timeout 20000ms exceeded.
Call log:
  - waiting for locator('div[data-testid=\'stExpander\']').filter({ hasText: /vs| - / }).first() to be visible

```

# Page snapshot

```yaml
- generic:
  - generic [ref=e2]:
    - generic [ref=e4]:
      - button "keyboard_double_arrow_left" [ref=e7] [cursor=pointer]:
        - generic [ref=e9]: keyboard_double_arrow_left
      - generic [ref=e12]:
        - heading "Filters" [level=2] [ref=e16]
        - generic [ref=e18]:
          - paragraph [ref=e22]: Section
          - radiogroup "Section" [ref=e23] [cursor=pointer]:
            - generic [ref=e24]:
              - radio "📅 Calendrier CDM 2026"
              - paragraph [ref=e29]: 📅 Calendrier CDM 2026
            - generic [ref=e30]:
              - radio "🌍 Effectifs CM 2026"
              - paragraph [ref=e35]: 🌍 Effectifs CM 2026
            - generic [ref=e36]:
              - radio "⚽ Effectifs Clubs"
              - paragraph [ref=e41]: ⚽ Effectifs Clubs
            - generic [ref=e42]:
              - radio "🏅 Classement ELO"
              - paragraph [ref=e47]: 🏅 Classement ELO
            - generic [ref=e48]:
              - radio "🔮 Prédictions"
              - paragraph [ref=e53]: 🔮 Prédictions
            - generic [ref=e54]:
              - radio "🔬 Backtest V8"
              - paragraph [ref=e59]: 🔬 Backtest V8
            - generic [ref=e60]:
              - radio "📡 Cotes Betclic"
              - paragraph [ref=e65]: 📡 Cotes Betclic
            - generic [ref=e66]:
              - radio "🎯 Garantie 2+"
              - paragraph [ref=e71]: 🎯 Garantie 2+
            - generic [ref=e72]:
              - radio "🔮 Prédiction Buteurs" [checked] [active]
              - paragraph [ref=e77]: 🔮 Prédiction Buteurs
            - generic [ref=e78]:
              - radio "📈 Tracking Test Edge Buteurs"
              - paragraph [ref=e83]: 📈 Tracking Test Edge Buteurs
            - generic [ref=e84]:
              - radio "📊 Suivi des paris"
              - paragraph [ref=e89]: 📊 Suivi des paris
            - generic [ref=e90]:
              - radio "🤖 Assistant IA"
              - paragraph [ref=e95]: 🤖 Assistant IA
        - separator [ref=e100]
        - paragraph [ref=e105]: Data refreshes every 5 minutes.
        - heading "🧭 Navigation compétitions" [level=3] [ref=e110]
        - generic [ref=e113] [cursor=pointer]:
          - checkbox "⭐ Top 5 uniquement"
          - generic [ref=e117]:
            - paragraph [ref=e119]: ⭐ Top 5 uniquement
            - button "Help for ⭐ Top 5 uniquement" [ref=e123]:
              - img [ref=e124]
        - generic [ref=e129] [cursor=pointer]:
          - checkbox "💰 Edge ≥ 5% uniquement"
          - generic [ref=e133]:
            - paragraph [ref=e135]: 💰 Edge ≥ 5% uniquement
            - button "Help for 💰 Edge ≥ 5% uniquement" [ref=e139]:
              - img [ref=e140]
        - button "🔄 Toutes les compétitions" [ref=e145] [cursor=pointer]:
          - paragraph [ref=e149]: 🔄 Toutes les compétitions
        - group [ref=e152]:
          - generic "keyboard_arrow_down 🌍 Compétitions UEFA (3)" [ref=e153] [cursor=pointer]:
            - generic [ref=e154]:
              - generic [ref=e156]: keyboard_arrow_down
              - paragraph [ref=e159]: 🌍 Compétitions UEFA (3)
          - generic [ref=e161]:
            - button "🇪🇺 Champions League · 1" [ref=e164] [cursor=pointer]:
              - paragraph [ref=e168]: 🇪🇺 Champions League · 1
            - button "🇪🇺 Europa League · 2" [ref=e171] [cursor=pointer]:
              - paragraph [ref=e175]: 🇪🇺 Europa League · 2
        - group [ref=e178]:
          - generic "keyboard_arrow_down ⭐ Top 5 ligues (23)" [ref=e179] [cursor=pointer]:
            - generic [ref=e180]:
              - generic [ref=e182]: keyboard_arrow_down
              - paragraph [ref=e185]: ⭐ Top 5 ligues (23)
          - generic [ref=e187]:
            - button "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League · 5" [ref=e190] [cursor=pointer]:
              - paragraph [ref=e194]: 🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League · 5
            - button "🇪🇸 La Liga · 4" [ref=e197] [cursor=pointer]:
              - paragraph [ref=e201]: 🇪🇸 La Liga · 4
            - button "🇮🇹 Serie A · 4" [ref=e204] [cursor=pointer]:
              - paragraph [ref=e208]: 🇮🇹 Serie A · 4
            - button "🇩🇪 Bundesliga · 6" [ref=e211] [cursor=pointer]:
              - paragraph [ref=e215]: 🇩🇪 Bundesliga · 6
            - button "🇫🇷 Ligue 1 · 4" [ref=e218] [cursor=pointer]:
              - paragraph [ref=e222]: 🇫🇷 Ligue 1 · 4
        - group [ref=e225]:
          - generic "keyboard_arrow_right 🇪🇺 Autres ligues européennes (57)" [ref=e226] [cursor=pointer]:
            - generic [ref=e227]:
              - generic [ref=e229]: keyboard_arrow_right
              - paragraph [ref=e232]: 🇪🇺 Autres ligues européennes (57)
        - group [ref=e235]:
          - generic "keyboard_arrow_right 🌎 Amériques (53)" [ref=e236] [cursor=pointer]:
            - generic [ref=e237]:
              - generic [ref=e239]: keyboard_arrow_right
              - paragraph [ref=e242]: 🌎 Amériques (53)
        - group [ref=e245]:
          - generic "keyboard_arrow_right 🌏 Asie / Moyen-Orient (5)" [ref=e246] [cursor=pointer]:
            - generic [ref=e247]:
              - generic [ref=e249]: keyboard_arrow_right
              - paragraph [ref=e252]: 🌏 Asie / Moyen-Orient (5)
    - generic [ref=e255]:
      - banner [ref=e256]:
        - generic [ref=e259]:
          - button "Deploy" [ref=e261] [cursor=pointer]:
            - generic [ref=e263]: Deploy
          - button "Main menu" [ref=e265] [cursor=pointer]:
            - img [ref=e266]
      - generic [ref=e271]:
        - heading "⚽ Football Analytics Dashboard" [level=1] [ref=e276]:
          - text: ⚽ Football Analytics Dashboard
          - generic [ref=e277]:
            - link "Link to heading":
              - /url: "#football-analytics-dashboard"
              - img
        - paragraph [ref=e282]: International competitions & top leagues — powered by TheStatsAPI
        - heading "🔮 Prédiction Buteurs — Détail par match" [level=2] [ref=e287]:
          - text: 🔮 Prédiction Buteurs — Détail par match
          - generic [ref=e288]:
            - link "Link to heading":
              - /url: "#calendrier-coupe-du-monde-2026"
              - img
        - paragraph [ref=e293]: Liste des matchs du week-end avec prédictions disponibles. Sélectionne un match pour voir compositions, coachs, système de jeu, stats des équipes, head-to-head, blessés et tous les buteurs prédits.
        - generic [ref=e295]:
          - button "🔄 Rafraîchir prédictions" [ref=e303] [cursor=pointer]:
            - paragraph [ref=e307]: 🔄 Rafraîchir prédictions
          - paragraph [ref=e314]:
            - text: "🟢 Dernière mise à jour :"
            - strong [ref=e315]: Wed 29/04 15:42
            - text: (Paris) — il y a 1.5h
        - paragraph [ref=e322]: ⏱️ 72 match(s) déjà commencé(s) masqué(s) (cotes Betclic figées une fois le coup d'envoi passé).
        - generic [ref=e324]:
          - paragraph [ref=e328]: 📅 Choisir un match
          - generic [ref=e330]:
            - generic [ref=e331]:
              - generic [ref=e332]: 🇸🇦 Saudi Pro League · Wed 29/04 18:00 — Al-Riyadh - Al-Qadsiah (34 joueurs, 0 cotes)
              - combobox "Selected 🇸🇦 Saudi Pro League · Wed 29/04 18:00 — Al-Riyadh - Al-Qadsiah (34 joueurs, 0 cotes). 📅 Choisir un match" [ref=e334]
            - img "open" [ref=e336]
        - group [ref=e340]:
          - 'generic "keyboard_arrow_right 📋 Vue d''ensemble : 141 matchs prédits" [ref=e341] [cursor=pointer]':
            - generic [ref=e342]:
              - generic [ref=e344]: keyboard_arrow_right
              - paragraph [ref=e347]: "📋 Vue d'ensemble : 141 matchs prédits"
        - separator [ref=e352]
        - heading "⚽ Al-Riyadh — Al-Qadsiah" [level=3] [ref=e357]:
          - text: ⚽ Al-Riyadh — Al-Qadsiah
          - generic [ref=e358]:
            - link "Link to heading":
              - /url: "#al-riyadh-al-qadsiah"
              - img
        - paragraph [ref=e363]:
          - strong [ref=e364]: 🇸🇦 Saudi Pro League
          - text: — Saudi Pro League 25/26 · J30
          - text: 🕒 Wed 29 Apr — 18:00 (heure Paris)
          - text: 🏟️ Prince Turki bin Abdul Aziz Stadium, Riyadh
        - group [ref=e367]:
          - generic "keyboard_arrow_down 🥅 [T023 c4] Composition manuelle interactive" [ref=e368] [cursor=pointer]:
            - generic [ref=e369]:
              - generic [ref=e371]: keyboard_arrow_down
              - paragraph [ref=e374]: 🥅 [T023 c4] Composition manuelle interactive
          - generic [ref=e376]:
            - paragraph [ref=e381]: 🧮 17 joueurs Al-Riyadh · 17 joueurs Al-Qadsiah (cotes, xG, xA et stats issus du moteur Buteurs Maison 4.1)
            - generic [ref=e383]:
              - alert [ref=e388]:
                - generic [ref=e391]:
                  - generic [ref=e394]: 💾
                  - paragraph [ref=e396]: "Compo sauvegardée — Al-Riyadh : 4-3-3 · sauvée 16:14 · Al-Qadsiah : 3-5-2 · sauvée 16:26"
              - button "🗑️ Purger" [ref=e404] [cursor=pointer]:
                - paragraph [ref=e408]: 🗑️ Purger
            - iframe [ref=e411]:
              - generic [ref=f1e3]:
                - generic [ref=f1e4]:
                  - generic [ref=f1e5]:
                    - generic [ref=f1e6]: Al-Riyadh vs Al-Qadsiah
                    - generic [ref=f1e7]: 🇸🇦 Saudi Pro League · Wed 29 Apr — 18:00
                  - generic [ref=f1e8]:
                    - button "↺ Reset" [ref=f1e9] [cursor=pointer]
                    - button "Save" [ref=f1e10] [cursor=pointer]
                - generic [ref=f1e11]:
                  - generic [ref=f1e12]:
                    - button "Al-Riyadh" [pressed] [ref=f1e13] [cursor=pointer]
                    - button "Al-Qadsiah" [ref=f1e14] [cursor=pointer]
                  - generic [ref=f1e15]:
                    - generic [ref=f1e16]: Schéma
                    - combobox [ref=f1e17] [cursor=pointer]:
                      - option "4-3-3" [selected]
                      - option "4-2-3-1"
                      - option "4-4-2"
                      - option "3-5-2"
                      - option "3-4-3"
                      - option "5-3-2"
                      - option "4-5-1"
                      - option "4-1-4-1"
                      - option "5-4-1 (réf BSD)"
                      - option "3-4-2-1"
                    - 'generic "Référence détectée : 5-4-1" [ref=f1e18]': OVERRIDE
                - generic [ref=f1e19]:
                  - text: "💡 Pour permuter 2 joueurs : clique sur l'un, puis le bouton orange"
                  - strong [ref=f1e20]: « ⇄ Permuter ce joueur »
                  - text: dans le panneau de droite, puis sur l'autre joueur (terrain ou banc).
                - generic [ref=f1e22]:
                  - generic [ref=f1e23]:
                    - img [ref=f1e24]
                    - button "Ibrahim Bayesh (MID), cote juste Buteur 9.66" [ref=f1e33] [cursor=pointer]:
                      - generic [ref=f1e35]: "16"
                      - generic [ref=f1e37]: Bayesh
                      - generic [ref=f1e38]: "9.66"
                    - button "Sulaiman Hahya Hazazi (DEF), cote juste Buteur 25.3" [ref=f1e39] [cursor=pointer]:
                      - generic [ref=f1e41]: "74"
                      - generic [ref=f1e43]: Hazazi
                      - generic [ref=f1e44]: "25.3"
                    - button "Ismaila Soro (MID), cote juste Buteur 17.8" [ref=f1e45] [cursor=pointer]:
                      - generic [ref=f1e47]: "76"
                      - generic [ref=f1e49]: Soro
                      - generic [ref=f1e50]: "17.8"
                    - button "Sergio Gonzalez (CB), cote juste Buteur 14.5" [ref=f1e51] [cursor=pointer]:
                      - generic [ref=f1e53]: "77"
                      - generic [ref=f1e55]: Gonzalez
                      - generic [ref=f1e56]: "14.5"
                    - button "Mamadou Sylla (FWD), cote juste Buteur 3.35" [ref=f1e57] [cursor=pointer]:
                      - generic [ref=f1e59]: "80"
                      - generic [ref=f1e61]: Sylla
                      - generic [ref=f1e62]: "3.35"
                    - button "Osama Al-Boardi (DEF), cote juste Buteur 23.9" [ref=f1e63] [cursor=pointer]:
                      - generic [ref=f1e65]: "71"
                      - generic [ref=f1e67]: Al-Boardi
                      - generic [ref=f1e68]: "23.9"
                    - button "Teddy Okou (MID), cote juste Buteur 13.9" [ref=f1e69] [cursor=pointer]:
                      - generic [ref=f1e71]: "75"
                      - generic [ref=f1e73]: Okou
                      - generic [ref=f1e74]: "13.9"
                    - button "Mohammed Al-Khaibari (DEF), cote juste Buteur 22.9" [ref=f1e75] [cursor=pointer]:
                      - generic [ref=f1e77]: "72"
                      - generic [ref=f1e79]: Al-Khaiba…
                      - generic [ref=f1e80]: "22.9"
                    - button "Yoann Barbet (DEF), cote juste Buteur 19.1" [ref=f1e81] [cursor=pointer]:
                      - generic [ref=f1e83]: "73"
                      - generic [ref=f1e85]: Barbet
                      - generic [ref=f1e86]: "19.1"
                    - button "Tozé (MID), cote juste Buteur 4.56" [ref=f1e87] [cursor=pointer]:
                      - generic [ref=f1e89]: "78"
                      - generic [ref=f1e91]: Tozé
                      - generic [ref=f1e92]: "4.56"
                    - button "Milan Borjan (GK), cote juste Buteur —" [ref=f1e93] [cursor=pointer]:
                      - generic [ref=f1e95]: "70"
                      - generic [ref=f1e97]: Borjan
                      - generic [ref=f1e98]: —
                  - button "▸Remplaçants · 6 ▼" [ref=f1e100] [cursor=pointer]:
                    - generic [ref=f1e101]: ▸Remplaçants · 6
                    - generic [ref=f1e102]: ▼
                - generic [ref=f1e103]: 💾 Compo personnalisée sauvegardée sur disque · 11 permutation(s) · schéma 4-3-3 (réf 5-4-1) · 1 minute(s) overridées
            - group [ref=e414]:
              - 'generic "keyboard_arrow_right Debug : dernier message React → Python" [ref=e415] [cursor=pointer]':
                - generic [ref=e416]:
                  - generic [ref=e418]: keyboard_arrow_right
                  - paragraph [ref=e421]: "Debug : dernier message React → Python"
        - separator [ref=e426]
        - heading "📊 xG attendus & marchés" [level=3] [ref=e432]:
          - text: 📊 xG attendus & marchés
          - generic [ref=e433]:
            - link "Link to heading":
              - /url: "#x-g-attendus-and-marches"
              - img
        - generic [ref=e435]:
          - generic [ref=e440]:
            - paragraph [ref=e443]: λ Al-Riyadh
            - paragraph [ref=e446]: "1.10"
          - generic [ref=e451]:
            - paragraph [ref=e454]: λ Al-Qadsiah
            - paragraph [ref=e457]: "2.28"
          - generic [ref=e462]:
            - paragraph [ref=e465]: Total xG
            - paragraph [ref=e468]: "3.38"
        - paragraph [ref=e473]:
          - text: "Méthode dérivation λ :"
          - code [ref=e474]: Analytique 1X2 + O/U 2.5 + BTTS
        - generic [ref=e479]:
          - button "Show/hide columns" [ref=e483] [cursor=pointer]:
            - img [ref=e484]
          - button "Download as CSV" [ref=e489] [cursor=pointer]:
            - img [ref=e490]
          - button "Search" [ref=e495] [cursor=pointer]:
            - img [ref=e496]
          - button "Fullscreen" [ref=e501] [cursor=pointer]:
            - img [ref=e502]
        - separator [ref=e517]
        - heading "👥 Compositions & système de jeu" [level=3] [ref=e523]:
          - text: 👥 Compositions & système de jeu
          - generic [ref=e524]:
            - link "Link to heading":
              - /url: "#compositions-and-systeme-de-jeu"
              - img
        - alert [ref=e527]:
          - generic [ref=e530]:
            - generic [ref=e533]: ⏳
            - paragraph [ref=e535]: Compositions non encore confirmées par BSD (publiées ~1h avant le coup d'envoi).
        - generic [ref=e537]:
          - generic [ref=e539]:
            - paragraph [ref=e544]:
              - text: 👤
              - strong [ref=e545]: "Coach Al-Riyadh :"
              - text: Maurício Dulac (Brazil)
            - paragraph [ref=e550]:
              - text: "⚙️ Formation préférée :"
              - code [ref=e551]: 4-4-2
              - text: "· 🎨 Styles : cross_pray, terrorist_fb · 🧭 Profil : balanced"
          - generic [ref=e553]:
            - paragraph [ref=e558]:
              - text: 👤
              - strong [ref=e559]: "Coach Al-Qadsiah :"
              - text: Brendan Rodgers (Northern Ireland)
            - paragraph [ref=e564]:
              - text: "⚙️ Formation préférée :"
              - code [ref=e565]: 4-4-2
              - text: "· 🎨 Styles : wing_play, heritage · 🧭 Profil : attacking"
        - separator [ref=e570]
        - heading "📈 Forme récente & comparatif des forces" [level=3] [ref=e576]:
          - text: 📈 Forme récente & comparatif des forces
          - generic [ref=e577]:
            - link "Link to heading":
              - /url: "#forme-recente-and-comparatif-des-forces"
              - img
        - generic [ref=e579]:
          - generic [ref=e581]:
            - paragraph [ref=e586]:
              - strong [ref=e587]: 🏠 Al-Riyadh
              - text: — 🔴🟢⚪🟢🔴
            - paragraph [ref=e592]: 5 matchs · 2V 1N 2D · 8-9 buts · xG 2.17 | xGA 1.69
          - generic [ref=e594]:
            - paragraph [ref=e599]:
              - strong [ref=e600]: 🛫 Al-Qadsiah
              - text: — ⚪⚪🔴🟢🟢
            - paragraph [ref=e605]: 5 matchs · 2V 2N 1D · 12-9 buts · xG 2.00 | xGA 1.57
        - generic [ref=e611]:
          - img:
            - generic:
              - generic:
                - generic:
                  - generic:
                    - generic: xG/match
                  - generic:
                    - generic: xG concédé
                  - generic:
                    - generic: Tirs/match
                  - generic:
                    - generic: Tirs cadrés
                  - generic:
                    - generic: "% passes"
                  - generic:
                    - generic: "% duels gagnés"
                  - generic:
                    - generic: "% duels aériens"
                - generic:
                  - generic:
                    - generic: "0"
                  - generic:
                    - generic: "20"
                  - generic:
                    - generic: "40"
                  - generic:
                    - generic: "60"
                  - generic:
                    - generic: "80"
                  - generic:
                    - generic: "100"
          - img:
            - generic [ref=e620]:
              - generic [ref=e622]: Al-Riyadh
              - generic [ref=e631]: Al-Qadsiah
          - toolbar [ref=e639]:
            - button "Download plot as a PNG" [ref=e641] [cursor=pointer]:
              - img [ref=e642]
            - button "Zoom" [ref=e645] [cursor=pointer]:
              - img [ref=e646]
            - button "Fullscreen" [ref=e649] [cursor=pointer]:
              - img [ref=e650]
          - img
        - separator [ref=e656]
        - heading "🤝 Confrontations directes (1 matchs)" [level=3] [ref=e662]:
          - text: 🤝 Confrontations directes (1 matchs)
          - generic [ref=e663]:
            - link "Link to heading":
              - /url: "#confrontations-directes-1-matchs"
              - img
        - generic [ref=e665]:
          - generic [ref=e670]:
            - paragraph [ref=e673]: V Al-Riyadh
            - paragraph [ref=e676]: "0"
          - generic [ref=e681]:
            - paragraph [ref=e684]: Nuls
            - paragraph [ref=e687]: "0"
          - generic [ref=e692]:
            - paragraph [ref=e695]: V Al-Qadsiah
            - paragraph [ref=e698]: "1"
        - paragraph [ref=e703]:
          - text: "⚽ Moyenne buts/match :"
          - strong [ref=e704]: "4.00"
        - group [ref=e707]:
          - generic "keyboard_arrow_right 📋 1 derniers face-à-face" [ref=e708] [cursor=pointer]:
            - generic [ref=e709]:
              - generic [ref=e711]: keyboard_arrow_right
              - paragraph [ref=e714]: 📋 1 derniers face-à-face
        - separator [ref=e719]
        - heading "⚽ Buteurs prédits (modèle propriétaire)" [level=3] [ref=e725]:
          - text: ⚽ Buteurs prédits (modèle propriétaire)
          - generic [ref=e726]:
            - link "Link to heading":
              - /url: "#buteurs-predits-modele-proprietaire"
              - img
        - generic [ref=e728]:
          - button "↩ Réinitialiser à BSD" [ref=e736] [cursor=pointer]:
            - paragraph [ref=e740]: ↩ Réinitialiser à BSD
          - generic [ref=e744]:
            - paragraph [ref=e748]: Marché
            - radiogroup "Marché" [ref=e749] [cursor=pointer]:
              - generic [ref=e750]:
                - radio "Buteur" [checked]
                - paragraph [ref=e755]: Buteur
              - generic [ref=e756]:
                - radio "Passeur"
                - paragraph [ref=e761]: Passeur
              - generic [ref=e762]:
                - radio "Les deux"
                - paragraph [ref=e767]: Les deux
        - paragraph [ref=e774]:
          - strong [ref=e775]: Al-Riyadh
          - text: ": compo probable (confiance 65%) ·"
          - strong [ref=e776]: Al-Qadsiah
          - text: ": compo probable (confiance 87%)"
          - emphasis [ref=e777]: 100% = onze type qui ne change jamais. Les 11 cochés par défaut sont les plus titularisés sur la saison.
        - generic [ref=e782]:
          - button "Show/hide columns" [ref=e786] [cursor=pointer]:
            - img [ref=e787]
          - button "Download as CSV" [ref=e792] [cursor=pointer]:
            - img [ref=e793]
          - button "Search" [ref=e798] [cursor=pointer]:
            - img [ref=e799]
          - button "Fullscreen" [ref=e804] [cursor=pointer]:
            - img [ref=e805]
        - paragraph [ref=e820]: 📊 22/34 joueurs inclus • ⏳ Compos non confirmées (mins=90 partout)
        - separator [ref=e825]
        - heading "💰 Ajouter au tracking forward test" [level=3] [ref=e831]:
          - text: 💰 Ajouter au tracking forward test
          - generic [ref=e832]:
            - link "Link to heading":
              - /url: "#ajouter-au-tracking-forward-test"
              - img
        - paragraph [ref=e837]: Aucun edge positif avec cote Betclic disponible pour ce match — rien à tracker pour l'instant.
  - img [ref=e838]
```

# Test source

```ts
  1  | 
  2  | import { test, expect } from "@playwright/test";
  3  | 
  4  | test("Verify lineup pitch component formations", async ({ page }) => {
  5  |   const consoleErrors: string[] = [];
  6  |   page.on("console", msg => {
  7  |     if (msg.type() === "error") consoleErrors.push(msg.text());
  8  |   });
  9  | 
  10 |   await page.goto("http://localhost:5000");
  11 |   
  12 |   // 1. Navigate to "🔮 Prédiction Buteurs"
  13 |   await page.getByText("🔮 Prédiction Buteurs").click();
  14 |   
  15 |   // 2. Open first match drill-down
  16 |   const matchExpander = page.locator("div[data-testid='stExpander']").filter({ hasText: /vs| - / }).first();
> 17 |   await matchExpander.waitFor({ state: "visible", timeout: 20000 });
     |                       ^ TimeoutError: locator.waitFor: Timeout 20000ms exceeded.
  18 |   
  19 |   const expanderHeader = matchExpander.locator("summary");
  20 |   await expanderHeader.click();
  21 | 
  22 |   // 3. Find and scroll into interactive expander
  23 |   const interactiveExpander = page.locator("div[data-testid='stExpander']").filter({ hasText: "🥅 [T023 c4] Composition manuelle interactive" });
  24 |   await interactiveExpander.scrollIntoViewIfNeeded();
  25 |   
  26 |   // The component is in an iframe. Use title from code.
  27 |   const frame = page.frameLocator("iframe[title='live.components.lineup_pitch.render_lineup_pitch']");
  28 |   
  29 |   // Wait for the iframe content to load
  30 |   const formationSelect = frame.locator("select");
  31 |   await formationSelect.waitFor({ state: "visible", timeout: 45000 });
  32 | 
  33 |   // 4. Verify home formation
  34 |   const homeFormation = await formationSelect.inputValue();
  35 |   console.log("Home Formation Default:", homeFormation);
  36 | 
  37 |   // Take screenshot of Home lineup
  38 |   await frame.locator("body").screenshot({ path: "home_lineup.png" });
  39 | 
  40 |   // 5. Switch to Away side
  41 |   // Find a button that is NOT the currently selected side.
  42 |   // The selected side button has background: white or aria-pressed=true
  43 |   const awayBtn = frame.getByRole("button").filter({ hasText: /Arsenal|Atlético|Away|Home/ }).nth(1);
  44 |   await awayBtn.click();
  45 |   
  46 |   await page.waitForTimeout(1000);
  47 |   const awayFormation = await formationSelect.inputValue();
  48 |   console.log("Away Formation Default:", awayFormation);
  49 |   
  50 |   // Take screenshot of Away lineup
  51 |   await frame.locator("body").screenshot({ path: "away_lineup.png" });
  52 | 
  53 |   // 6. Confirm 10 formation options exist including 3-4-2-1
  54 |   const options = frame.locator("option");
  55 |   const optionList = await options.allInnerTexts();
  56 |   console.log("Formation options:", optionList);
  57 |   console.log("Formation options count:", optionList.length);
  58 |   
  59 |   expect(optionList.length).toBe(10);
  60 |   expect(optionList.some(o => o.includes("3-4-2-1"))).toBe(true);
  61 | 
  62 |   console.log("Console Errors:", consoleErrors);
  63 | });
  64 | 
```