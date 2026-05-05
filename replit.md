# Football Analytics Dashboard

A pnpm monorepo providing a football analytics dashboard and a supporting API for comprehensive data visualization, ELO rankings, match predictions, odds comparison, and World Cup 2026 simulations.

## Run & Operate

```bash
pnpm install
pnpm run build
pnpm run typecheck
pnpm run codegen # Regenerate API client and Zod schemas
pnpm drizzle-kit push:pg # Apply DB schema migrations
```

**Required Environment Variables:**
- `DATABASE_URL`
- `THE_ODDS_API_KEY`
- `ANTHROPIC_API_KEY`

## Stack

- **Monorepo:** pnpm workspaces
- **Runtime:** Node.js v24
- **Language:** TypeScript v5.9
- **API:** Express v5
- **Database:** PostgreSQL
- **ORM:** Drizzle ORM
- **Validation:** Zod
- **API Codegen:** Orval (from OpenAPI spec)
- **Build Tool:** esbuild
- **Frontend (Dashboard):** Python + Streamlit

## Where things live

- `artifacts/api-server/`: Express.js API backend.
- `artifacts/football-dashboard/`: Streamlit frontend application.
- `lib/api-spec/`: OpenAPI specification and generated types.
- `lib/api-client-react/`: React Query hooks for API interaction.
- `lib/api-zod/`: Zod schemas for API validation.
- `lib/db/`: Drizzle ORM schema and database utilities.
- `scripts/`: Utility scripts (e.g., `make_current_season.py`, `build_pages.py`).
- `.github/workflows/`: GitHub Actions workflows (e.g., `scrape-weekly.yml`).
- `live/data/`: Various data caches and outputs (e.g., `statshub_match_cache.json`, `odds_router_cache.json`, `forward_bets.json`).
- `.local/refs/FWC2026_regulations_EN.pdf`: FIFA World Cup 2026 regulations.
- `Buteurs_Maison_4.1.xlsx`: Proprietary Excel file for manual player positions.
- `live/data/manual_positions.json`: Extracted manual player positions.
- `live/leagues_master.py`: Configuration for all scraped leagues.

## Architecture decisions

- **Monorepo with pnpm workspaces:** Enables shared code (`lib/`) across `api-server` and `football-dashboard` while maintaining independent deployable units.
- **TypeScript Composite Projects:** Ensures robust cross-package type-checking and improved developer experience.
- **Drizzle ORM:** Chosen for its type-safety and efficient query building for PostgreSQL.
- **OpenAPI + Orval Codegen:** Automates API client and Zod schema generation, reducing boilerplate and ensuring consistency between frontend and backend.
- **Streamlit for Dashboard:** Provides rapid development and interactive data visualization capabilities for the analytics frontend.
- **Flashscore-like UI in Streamlit:** Implemented a sidebar-based league navigation for enhanced user experience, similar to popular sports score websites.

## Product

- **Football Analytics Dashboard:** Interactive Streamlit application for in-depth football analysis.
- **ELO Rankings & Match Predictions:** Dynamic ELO system with competition-specific K-factors and time decay for accurate match predictions.
- **Odds Comparison:** Integrates with multiple odds providers (Pinnacle, Bet365, Betclic, TheOddsAPI) for identifying value bets.
- **World Cup 2026 Simulator:** Monte Carlo simulations with FIFA-compliant tie-breaking rules and market-derived expected scores.
- **Garantie 2+ Section:** Calculates probabilities for G2+ markets using a closed-form analytical method.
- **Forward Test Live (Top 5+):** Real-time pipeline for validating proprietary scorer/assister models across multiple leagues, including player-specific odds, lineup fallbacks, and injury tracking.
- **AI Assistant Integration:** (Claude) for interactive queries and insights.
- **Public Data Portal:** GitHub Pages portal for sharing Transfermarkt career data for various leagues and national squads.

## User preferences

I prefer iterative development, focusing on one feature or bug fix at a time. Please ask for confirmation before making significant architectural changes or adding new external dependencies. For any new features, prioritize robust error handling and clear logging. I value detailed explanations of complex logic, especially in prediction models or data processing.

## Gotchas

- **Forward Log Immutability:** The forward log is designed to *never* overwrite `outcome_scored` results, ensuring data integrity for backtesting.
- **Streamlit Refresh Behavior:** Be aware that Streamlit reruns scripts on interaction, which can lead to re-calculations if not properly cached.
- **Transfermarkt Scraper:** The Transfermarkt scraper specifically targets club-season pages due to client-side rendering on player pages, limiting available player stats (e.g., no assists/cards).
- **Odds Source Priority:** The odds router prioritizes Bet365 where available, falling back to other sources. Be mindful that `compareOdds` endpoint might not cover all leagues.
- **FIFA WC Tie-breaking:** The simulator explicitly replaces FIFA's "fair-play" (cards) criterion with pre-tournament ELO ranking due to Monte Carlo simulation limitations.

## Pointers

- **Drizzle ORM Docs:** _Populate as you build_
- **OpenAPI Specification:** _Populate as you build_
- **Streamlit Documentation:** _Populate as you build_
- **pnpm Workspaces:** _Populate as you build_
- **TypeScript Handbook:** _Populate as you build_
- **FIFA World Cup 2026 Regulations:** `.local/refs/FWC2026_regulations_EN.pdf`
- **Public Transfermarkt Data Portal:** `https://maloelpipo.github.io/FootballDashboard/`