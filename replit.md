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
        - **Betclic Scraper:** Pure HTTP scraper for Betclic odds (1X2, goalscorer, outrights) using gRPC-web.
        - **Squad Scraper:** Scrapes Transfermarkt for WC 2026 national team squad data, including player profiles, market values, and positions.
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