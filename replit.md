# Overview

This pnpm workspace monorepo, built with TypeScript, provides a football analytics dashboard and a supporting API. The project focuses on comprehensive data visualization, ELO rankings, match predictions, odds comparison, and World Cup 2026 simulations, targeting the sports analytics and betting insights market.

**Key Capabilities:**
- **Football Analytics Dashboard:** A Streamlit application for detailed analysis, ELO rankings, match predictions, and World Cup 2026 simulations.
- **API Server:** An Express.js backend for data serving and business logic.
- **Data Scraping:** Tools for collecting odds from bookmakers and national squad information.

# User Preferences

I prefer iterative development, focusing on one feature or bug fix at a time. Please ask for confirmation before making significant architectural changes or adding new external dependencies. For any new features, prioritize robust error handling and clear logging. I value detailed explanations of complex logic, especially in prediction models or data processing.

# System Architecture

The project uses a pnpm workspace monorepo for shared code and independent application deployment.

**Core Technologies:**
- **Monorepo Tool:** pnpm workspaces
- **Node.js:** v24
- **TypeScript:** v5.9
- **API Framework:** Express v5
- **Database:** PostgreSQL with Drizzle ORM
- **Validation:** Zod
- **API Codegen:** Orval (from OpenAPI spec)
- **Build Tool:** esbuild
- **Frontend (Dashboard):** Python + Streamlit

**Monorepo Structure:**
- `artifacts/`: Deployable applications (e.g., `api-server`, `football-dashboard`).
- `lib/`: Shared libraries (e.g., `api-spec`, `api-client-react`, `api-zod`, `db`).
- `scripts/`: Utility scripts.

**TypeScript & Composite Projects:**
All packages extend a base `tsconfig.base.json` with `composite: true` for cross-package type-checking.

**UI/UX (Football Analytics Dashboard):**
The Streamlit dashboard offers an interactive interface with sections for match results, team/player data, ELO rankings, match predictions, odds comparisons, and World Cup 2026 simulations. It integrates an AI Assistant (Claude).

**Technical Implementations & Feature Specifications:**

- **API Server (`@workspace/api-server`):** Express.js server with routes, validation via `@workspace/api-zod`, and database interaction via `@workspace/db`.
- **Database Layer (`@workspace/db`):** Drizzle ORM for PostgreSQL schema and connections.
- **API Specification & Codegen (`@workspace/api-spec`):** Defines OpenAPI 3.1 spec and generates React Query hooks, fetch clients, and Zod schemas.
- **Football Analytics Dashboard (`artifacts/football-dashboard`):**
    - **Prediction Models:** Includes a V8-Pin Optimized Model, a Dynamic ELO System with competition-specific K-factors and time decay, and Monte Carlo Simulations for WC 2026.
    - **Data Processing:** Handles historical odds, scraped odds, and ELO computations.
    - **Scraping:** Betclic odds (gRPC-web) and Transfermarkt national squad data.
    - **Garantie 2+ Section:** Calculates G2+ probabilities based on market 1X2 odds, O/U 2.5, and BTTS using a closed-form analytical method (`lambdas_buchdahl`).
    - **Forward Test Live (Top 5):** Real-time pipeline for validating proprietary scorer/assister models.
        - **Player Pool & Stats:** Builds player pools with season stats, caches career stats, and handles transfer overrides.
        - **Prediction Logic:** Predicts scorer/assister odds using a calibrated anti-Poisson model, resolving player positions and minutes, and managing lineup fallbacks. The scorer engine uses goals-per-90 instead of xG.
        - **Probable Lineup (T008):** When BSD has not yet published the official lineup (~1h pre-kickoff), the pool computes a `start_rate` per player (starts/team_matches), and `build_lineup_fallback` selects the top-11 by start_rate (with mandatory GK guaranteed). Each player carries a "shadow odd" `fair_odd_scorer/assist_if_starter` simulating his odds if he were a starter — useful to spot value on presumed substitutes. The UI shows a "Compo prob. confiance X%" badge and a "Cote si tit." column.
        - **Cote 90' théorique (T009):** All scorer/assist fair odds are computed at theoretical 90' game time (`xg_for_90 = xg_calibrated × 90 / minutes_expected`), aligning with the French "garantie buteur" market convention (the bookmaker's bet is validated even if the player only enters as a substitute). The team xG calibration is preserved (`sum xg_calibrated = team_xg`), only the per-player probability is published at 90'-equivalent. This significantly lowers fair odds for presumed substitutes (e.g. a sub at 25' avg minutes has odds ~3.6× lower than the minutes-aware model) and makes the model directly comparable to bookmaker prices. The "Cote si tit." column (T008 shadow odds) is preserved alongside: post-T009, the gap between Cote juste and Cote si tit. is smaller (since the actual sub odd is already inflated to 90'), but still surfaces the share-renormalization effect of promoting one specific sub to starter.
        - **Expected Shots (T010):** Two descriptive columns added to the predictions table: `xT` (expected shots) = `shots_per_90 × minutes_expected / 90` and `xT cad.` (expected shots on target) = `shots_on_target_per_90 × minutes_expected / 90`. Aggregated from BSD per-game `total_shots` / `shots_on_target` fields. Unlike the cote at 90' theoretical, these use real `minutes_expected` since they describe what the player will actually do in the match. Helpful to spot value: a player with high xT but low p% suggests the model under-rates his danger.
        - **Injured player visibility (T011):** Injured/suspended/doubtful players now appear in the prediction table (previously hidden), unchecked by default. They're shown with the corresponding emoji (🤕 / 🟥 / ❓) and with `xg_calibrated = 0` (no impact on team xG normalization). Their `minutes_expected` defaults to `avg_mins_when_starter` (~85 min) so that if the user manually re-enables them (last-minute rumor of recovery), `_recalculate_shares` produces valid odds based on `xg_per_90_used × 85 / 90`. When a BSD-confirmed lineup includes a player previously flagged as injured (e.g. Sorloth listed in starters despite "doubtful" tag), the BSD lineup is now treated as source of truth and the player is force-included with normal odds calculation.
        - **Manual position overrides (T012):** BSD only provides fine positions (ST/RW/CB/AM/…) for ~10–18% of Top 5 players; the rest are tagged with the coarse codes MID/DEF/FWD/GK. To bypass this limitation, the user's proprietary Excel file (`Buteurs_Maison_4.1.xlsx`, sheet `Joueurs`, column `Poste`) is extracted into `live/data/manual_positions.json` (~2 500 Top 5 players) via `live/extract_manual_positions.py`. The French codes are mapped to BSD codes (BU→ST, AT→SS, AD→RW, AG→LW, MOC→AM, MDC→DM, MC→CM, DC→CB, DD→RB, DG→LB, G→GK). At pool build time, `assign_team_ids_via_squads` looks up each BSD player by `(name, team, country)` in the override dict and stores `pool[pid]["manual_position"]`. The `resolve_detailed_position` cascade now uses this override at step 0 (highest priority, before BSD lineup/squad fields). For players absent from the Excel (typically goalkeepers, U21, fringe substitutes), the BSD cascade still applies. Coverage measured at ~73% on PL pool, ~65% on La Liga pool, ~80% on real prediction players (logged in forward log). Star players impacted: Salah MID→**RW**, Haaland FWD→**ST**, Griezmann FWD→**SS**, Bruno Fernandes MID→**AM**, Yamal MID→**RW**, Vinicius FWD→**LW**, Saka MID→**RW**, Bellingham MID→**AM**, Lewandowski FWD→**ST**, Mbeumo confirmed RW.
        - **Result Enrichment:** Retrieves outcomes and updates prediction logs.
        - **UI Streamlit (`live/ui.py`):** Provides detailed match predictions, an edge testing table, and tracking KPIs for forward tests.
        - **StatsHub complementary lineup (T013):** Read-only integration with StatsHub.com (no auth required). The new module `live/statshub_helpers.py` resolves any BSD match to its StatsHub external (Sportradar) id via fuzzy team-name + kickoff-date matching, then fetches the predicted lineup via `/api/event/{externalId}/predicted-teams-lineup`. Results are cached locally (`live/data/statshub_match_cache.json`, TTL 30 min, negative results cached too to avoid retries). In `_render_match_detail`, a new collapsible "Compo prédite (StatsHub)" expander appears below the existing BSD lineup block, displaying the home/away predicted XI side-by-side with shirt numbers and positions. Designed as a strict complement: if StatsHub is unreachable or no match is found, nothing is rendered (zero impact on existing UI). The Buteurs Maison 4.1 model and the BSD-primary pipeline are NOT modified — StatsHub is purely visual additional context.

# External Dependencies

- **Database:** PostgreSQL
- **Football Data API:** TheStatsAPI
- **Odds API:** The Odds API
- **AI Assistant:** Claude (Anthropic)
- **Data Sources:** Transfermarkt, Betclic, Pinnacle, Betfair Exchange (EU), Unibet FR, PMU FR, AllSportsAPI (for BSD API odds), OPTA Power Ratings.