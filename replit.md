# Overview

This is a pnpm workspace monorepo using TypeScript, designed for building and deploying applications, primarily focusing on a football analytics dashboard and its supporting API. The project aims to provide comprehensive data visualization and prediction capabilities for football events, including the FIFA World Cup 2026.

**Key Capabilities:**
- **Football Analytics Dashboard:** A Streamlit app offering detailed analysis, ELO rankings, match predictions, odds comparison, and World Cup 2026 simulations.
- **API Server:** An Express.js backend serving data and handling business logic.
- **Data Scraping:** Tools for gathering odds data from various bookmakers and national squad information from Transfermarkt.

**Business Vision & Market Potential:**
The project taps into the growing market for sports analytics and betting insights, offering a sophisticated tool for enthusiasts and potentially professional analysts. The focus on the upcoming World Cup 2026 positions it to capture significant user interest during a major global sporting event.

# User Preferences

I prefer iterative development, focusing on one feature or bug fix at a time. Please ask for confirmation before making significant architectural changes or adding new external dependencies. For any new features, prioritize robust error handling and clear logging. I value detailed explanations of complex logic, especially in prediction models or data processing.

# System Architecture

The project is structured as a pnpm workspace monorepo, facilitating shared code and independent deployment of applications.

**Core Technologies:**
- **Monorepo Tool:** pnpm workspaces
- **Node.js:** v24
- **TypeScript:** v5.9
- **API Framework:** Express v5
- **Database:** PostgreSQL with Drizzle ORM
- **Validation:** Zod (`zod/v4`), `drizzle-zod`
- **API Codegen:** Orval (from OpenAPI spec)
- **Build Tool:** esbuild (CJS bundle)
- **Frontend (Dashboard):** Python + Streamlit

**Monorepo Structure:**
- `artifacts/`: Deployable applications (e.g., `api-server`, `football-dashboard`).
- `lib/`: Shared libraries (e.g., `api-spec`, `api-client-react`, `api-zod`, `db`).
- `scripts/`: Utility scripts.

**TypeScript & Composite Projects:**
All packages extend a base `tsconfig.base.json` with `composite: true`. The root `tsconfig.json` references all packages, enabling cross-package type-checking and dependency graph resolution. `tsc --build --emitDeclarationOnly` is used for type-checking, with actual JS bundling handled by esbuild/tsx.

**UI/UX (Football Analytics Dashboard):**
The dashboard is built with Streamlit, providing an interactive web interface. It features:
- Multiple sections for match results, team/player data, ELO rankings, match predictions, and odds comparisons.
- Dedicated sections for World Cup 2026 calendar, squad analysis, and Monte Carlo simulations.
- Interactive elements like filters, charts, and tables for data visualization.
- Integration of an AI Assistant (Claude) for enhanced user interaction.

**Technical Implementations & Feature Specifications:**

- **API Server (`@workspace/api-server`):** An Express.js server with routes defined in `src/routes/`. It uses `@workspace/api-zod` for request/response validation and `@workspace/db` for database interactions.
- **Database Layer (`@workspace/db`):** Utilizes Drizzle ORM for PostgreSQL, defining schema models and managing database connections.
- **API Specification & Codegen (`@workspace/api-spec`):** Defines the OpenAPI 3.1 specification and uses Orval to generate:
    - React Query hooks and a fetch client (`lib/api-client-react`).
    - Zod schemas for validation (`lib/api-zod`).
- **Football Analytics Dashboard (`artifacts/football-dashboard`):**
    - **Prediction Models:**
        - **V8-Pin Optimized Model:** A core prediction model calibrated to minimize divergence from Pinnacle odds, with configurable parameters.
        - **Dynamic ELO System:** Calculates and updates ELO ratings with competition-specific K-factors and time decay. Supports both classic ELO and Pinnacle-anchored ELO.
        - **Monte Carlo Simulation:** For WC 2026 predictions, simulating group stages, knockout rounds, and providing nation-specific probabilities.
    - **Data Processing:** Handles historical odds, scraped odds, and ELO computations.
    - **Scraping:**
        - **Betclic Scraper:** Pure HTTP scraper for Betclic odds (1X2, goalscorer, outrights, Garantie 2 Buts) using gRPC-web.
            - **Garantie 2 Buts (Early Win) scraping path:** gRPC match response → market with label containing "2 buts d'avance" → selections in **field 16** (not field 11 like other markets) → team name in sub-field 10, odds in sub-field 12 (double, 8 bytes). Market state=8 does NOT mean no data — selections can still be present in field 16.
        - **Squad Scraper:** Scrapes Transfermarkt for WC 2026 national team squad data, including player profiles, market values, and positions.
    - **Garantie 2+ Section:**
        - **Inputs:** Match selection (Betclic dropdown), target team, Lay 1X2 (auto via Odds API or manual). Optional: Betfair Exchange scraping for enriched markets.
        - **Auto data:** Betclic G2+ odds via gRPC field 16 scraping. Betfair Exchange scraping via Playwright + Webshare EU proxy for 1X2, BTTS, O/U 2.5, O/U 0.5, and 16 Correct Score markets.
        - **Betfair data extraction:** For each market selection, captures Back price + volume and Lay price + volume. Computes volume-weighted mid-price: `mid = back × (back_vol/total_vol) + lay × (lay_vol/total_vol)`.
        - **Lambda derivation — 3-tier cascade (Buchdahl-inspired):**
            - **Tier 1 — P(0) direct (best):** `lambdas_from_betfair()` — derives λ_team = -ln(1/cote_U0.5_team) and λ_total = -ln(1/cote_0-0), then λ_opp = λ_total - λ_team. No optimization — pure analytical derivation from P(0). Matches the Google Sheets reference exactly.
            - **Tier 2 — Cascade optimization (fallback):** Multi-constraint weighted optimization using scipy Nelder-Mead when P(0) data unavailable:
              - 1X2 Lay → P(team wins) = 1/lay (weight=10)
              - O/U 2.5 Under mid → P(Under 2.5) constrains λ_total (weight=50)
              - BTTS Yes mid → P(BTTS) = (1-e^-λA)(1-e^-λB) splits λA/λB (weight=30)
              - O/U 0.5 Under mid → validates λ_total (weight=20)
              - CS mid-prices → MLE refinement on 16 scores (weight=5)
        - **Margin removal (Buchdahl method):** `remove_margin_proportional()` — fair odds = n×O/(n-M×O) for n-outcome market. Accounts for favourite-longshot bias. Available for 3-way and 2-way markets.
        - **G2+ probability:** Two methods: (1) Monte Carlo simulation (50K iterations, minute-by-minute) — team wins if it led by 2+ at any point OR wins at full time. (2) Fixed-fraction analytical method using ballot problem formula: `fraction(i,j) = i(i-1)/((j+2)(j+1))` for i≥2. P(G2+) = P(win)_market + Σ(draws+losses) P(score) × fraction(score). When `p_win_market` is provided (from 1/Lay), uses the market P(win) instead of Poisson P(win) for better accuracy.
        - **Output:** xG team, xG opponent, xG match, P(G2+) MC, P(G2+) fractions, fair odds, Betclic odds, edge %, EV0, Poisson matrix, value indicator, cascade method used.
        - **Manual fallback:** All market fields are editable. Tool works with just Lay 1X2 (minimum), additional markets improve precision progressively.
    - **Workflow:** Runs on port 5000 via a Streamlit web application.

# External Dependencies

- **Database:** PostgreSQL (managed via Drizzle ORM)
- **Football Data API:** TheStatsAPI (`https://api.thestatsapi.com/api`) - for football data (teams, players, competitions, matches). API key and base URL are managed via environment variables.
- **Odds API:** The Odds API (`the-odds-api.com`) - for multi-bookmaker odds. API key managed via environment variables.
- **AI Assistant:** Claude (Anthropic) - integrated for AI assistant functionalities within the dashboard. API key managed via environment variables.
- **Transfermarkt:** Used for scraping national team squad data.
- **Betclic:** Scraped directly for live odds using gRPC-web.
- **Pinnacle, Betfair Exchange (EU), Unibet FR, PMU FR:** Specific bookmakers whose odds are integrated and analyzed.
- **AllSportsAPI:** Used as a source for BSD API odds (likely Bet365 as default).
- **OPTA Power Ratings:** Used in conjunction with ELO calculations.