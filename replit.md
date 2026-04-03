# Workspace

## Overview

pnpm workspace monorepo using TypeScript. Each package manages its own dependencies.

## Stack

- **Monorepo tool**: pnpm workspaces
- **Node.js version**: 24
- **Package manager**: pnpm
- **TypeScript version**: 5.9
- **API framework**: Express 5
- **Database**: PostgreSQL + Drizzle ORM
- **Validation**: Zod (`zod/v4`), `drizzle-zod`
- **API codegen**: Orval (from OpenAPI spec)
- **Build**: esbuild (CJS bundle)

## Structure

```text
artifacts-monorepo/
├── artifacts/              # Deployable applications
│   └── api-server/         # Express API server
├── lib/                    # Shared libraries
│   ├── api-spec/           # OpenAPI spec + Orval codegen config
│   ├── api-client-react/   # Generated React Query hooks
│   ├── api-zod/            # Generated Zod schemas from OpenAPI
│   └── db/                 # Drizzle ORM schema + DB connection
├── scripts/                # Utility scripts (single workspace package)
│   └── src/                # Individual .ts scripts, run via `pnpm --filter @workspace/scripts run <script>`
├── pnpm-workspace.yaml     # pnpm workspace (artifacts/*, lib/*, lib/integrations/*, scripts)
├── tsconfig.base.json      # Shared TS options (composite, bundler resolution, es2022)
├── tsconfig.json           # Root TS project references
└── package.json            # Root package with hoisted devDeps
```

## TypeScript & Composite Projects

Every package extends `tsconfig.base.json` which sets `composite: true`. The root `tsconfig.json` lists all packages as project references. This means:

- **Always typecheck from the root** — run `pnpm run typecheck` (which runs `tsc --build --emitDeclarationOnly`). This builds the full dependency graph so that cross-package imports resolve correctly. Running `tsc` inside a single package will fail if its dependencies haven't been built yet.
- **`emitDeclarationOnly`** — we only emit `.d.ts` files during typecheck; actual JS bundling is handled by esbuild/tsx/vite...etc, not `tsc`.
- **Project references** — when package A depends on package B, A's `tsconfig.json` must list B in its `references` array. `tsc --build` uses this to determine build order and skip up-to-date packages.

## Root Scripts

- `pnpm run build` — runs `typecheck` first, then recursively runs `build` in all packages that define it
- `pnpm run typecheck` — runs `tsc --build --emitDeclarationOnly` using project references

## Football Analytics Dashboard

A Streamlit-based data visualization app located at `artifacts/football-dashboard/`.

- **Framework**: Python + Streamlit
- **Port**: 5000
- **Workflow**: "artifacts/football-dashboard: web"
- **Data source**: TheStatsAPI (`https://api.thestatsapi.com/api`) — football data (teams, players, competitions, matches)
- **API key**: stored as `STATS_API_KEY` secret; base URL as `STATS_API_URL` env var
- **Pre-filter**: Only curated major competitions shown (not all 12,000+ in the API)
- **Competition categories** (sidebar filter):
  - UEFA Club Competitions (Champions League, Europa League, Conference League, Women's CL)
  - International National Teams (Nations League, Copa América, AFCON, CONCACAF, International Friendlies)
  - World Cup Qualifiers (UEFA/AFC/CONMEBOL/CAF/OFC/CONCACAF)
  - Continental Club Competitions (Libertadores, Sudamericana, CAF CL, CONCACAF CC)
  - Top Domestic Leagues (Premier League, Bundesliga, Ligue 1, Serie A, 2. Bundesliga)
- **Key competition IDs**:
  - `comp_3498` UEFA Champions League, `comp_7739` UEFA Europa League, `comp_408698` Conference League
  - `comp_574977` UEFA Nations League, `comp_5749` Copa América, `comp_1554` AFCON
  - `comp_1376` CONCACAF Gold Cup, `comp_0499` CONMEBOL Libertadores, `comp_1615` Sudamericana
  - `comp_08478` CAF Champions League, `comp_8649` CONCACAF Champions Cup
  - `comp_3039` Premier League, `comp_4643` Bundesliga, `comp_0256` Ligue 1, `comp_5840` Serie A
  - `comp_29967` International Friendly Games (World)
  - WC Qualifiers: `comp_2954` UEFA, `comp_8973` AFC, `comp_4682` CONMEBOL, `comp_5720` CAF, `comp_7363` OFC, `comp_0836` CONCACAF
- **AI Assistant**: Claude (Anthropic) integration via `ANTHROPIC_API_KEY`, streaming responses
- **ELO Ranking**: EloRating.net base + BSD ±50pts adjustment (effectif 70% + performance 30%). Supports manual "ELO forcé" overrides with configurable weight (default 80%). Persisted in `elo_overrides.json`. Module: `elo_engine.py`
- **Odds API**: The Odds API (`the-odds-api.com`) for multi-bookmaker odds; key stored as `ODDS_API_KEY`
  - Selected bookmakers: Pinnacle, Betfair Exchange (EU), Unibet FR, PMU FR
  - BSD API odds source: AllSportsAPI (likely Bet365 as default bookmaker)
- **Sections**:
  - Match Results: filter by competition & status, goal distribution charts, outcome pie chart, match list
  - Teams: team nationalities chart, full team table per competition
  - Players: age/height/position/nationality visualizations per team
  - ELO Ranking: blended ELO scores for national teams
  - Prédiction de Matchs: ELO-based win probability
  - Comparaison de Cotes: bookmaker odds scraping
  - **Calendrier CDM 2026**: World Cup 2026 match calendar with multi-bookmaker 1X2 odds (Pinnacle, Betfair, Unibet FR, PMU), outright winner odds, phase filtering
  - **Effectifs CM 2026**: squads for all 48 WC 2026 nations via Transfermarkt scraping
  - **Prédictions**: Monte Carlo simulation (Buchdahl 1X2 model calibrated on Pinnacle) — global rankings, group stage probabilities, match-by-match 1X2 predictions with fair odds, value detection vs Pinnacle live lines

## WC 2026 Simulator (`wc_simulator.py`)

Monte Carlo engine for FIFA World Cup 2026 predictions.

### Core Model — Sigmoid V7
- **Sigmoid + Power-law Draw + Quality factor**: `draw_adj = 27.9% + (-0.70) × (elo_avg-1800)/100`, `P(draw) = draw_adj / (1 + (|Δ|/540)^2.6)`, `P(1) = (100-draw) × sigmoid(Δ/431.3)`
- Quality effect: avg=1600 → 29.3% draw base, avg=2100 → 26.0% (top teams draw less)
- Calibrated on 79 points (19 WC2026 + 59 WC2022 Pinnacle + anchor): RMSE=5.76%
- Smooth draw decline: Δ=0→27.9%, Δ=200→25.5%, Δ=400→19%, Δ=542→13.7%
- Backtest WC 2022 (63 matchs): Brier=0.595 vs Pinnacle=0.597, ROI=+20.1% flat betting
- Goal model: Poisson with λ calibrated from ELO delta (avg ~2.5 goals)

### Simulation Pipeline
1. Build ELO map from `elo_engine.py` composite scores
2. Simulate 3 group-stage matches per group (12 groups × 6 matches = 72 matches)
3. Rank groups: pts > GD > GF; qualify top 2 + best 8 of 12 third-place teams
4. Bracket: R32 → R16 → QF → SF → Final (matches 73–88 mapped from FIFA bracket)
5. Output: per-nation probabilities (avg_pts, p_1st/2nd/3rd/4th, p_r32/r16/qf/sf/final/winner)

### Key Functions
- `run_simulation(n_sims)` — returns sorted list of nation results
- `get_group_predictions()` — returns 1X2 predictions for all 72 group matches
- `sigmoid_v6_1x2(delta, elo_avg=None)` — probability calculation from ELO delta + quality factor (Sigmoid V7 model)
- `_build_elo_map()` — builds nation_code→ELO dict from composite engine

## Squad Scraper (`squad_scraper.py`)

Scrapes Transfermarkt for WC 2026 national team squads.

### Pipeline
1. `get_recent_match_ids(slug, tm_id, n=5)` — fixture page → last N match IDs
2. `get_match_lineup(match_id, nation_tm_id)` — match sheet page → player list for the specific team
3. `get_player_profile(player_tm_id)` — profile page → club, market value, position
4. `build_squad(nation, n_matches=5)` — full pipeline, deduplicates players, returns top 30 by appearances
5. `get_squad_cached(nation, force_refresh=False)` — disk cache (48h TTL) wrapper

### Key HTML parsing
- Fixture URL: `https://www.transfermarkt.fr/{slug}/spielplandatum/verein/{tm_id}/saison_id/2025`
- Lineup URL: `https://www.transfermarkt.fr/x/aufstellung/spielbericht/{match_id}`
- **Team splitting**: TM match sheet has 4 `class="large-6 columns"` blocks: [0]=home starters, [1]=away starters, [2]=home bench, [3]=away bench. Home/away determined by `class="sb-team sb-heim/sb-gast"` in page header.
- **Player name**: extracted from `alt` attribute of `<img>` inside `/profil/spieler/{id}` links
- **Market value**: regex `(\d+[,.]?\d*)\s*(?:mio\.|Mio\.)\s*€`
- REQUEST_DELAY = 0.6s; cache TTL = 48h; cache file: `squads_cache.json`

### Nations data (`nations_data.py`)
- 48 WC 2026 nations with TM IDs, slugs, FR names, confederations
- Structure: `WC2026_NATIONS` dict by confederation (UEFA, CONMEBOL, CONCACAF, AFC, CAF, OFC)
- Access: `get_nation_by_code('FRA')`, `get_all_nations()`

## Packages

### `artifacts/api-server` (`@workspace/api-server`)

Express 5 API server. Routes live in `src/routes/` and use `@workspace/api-zod` for request and response validation and `@workspace/db` for persistence.

- Entry: `src/index.ts` — reads `PORT`, starts Express
- App setup: `src/app.ts` — mounts CORS, JSON/urlencoded parsing, routes at `/api`
- Routes: `src/routes/index.ts` mounts sub-routers; `src/routes/health.ts` exposes `GET /health` (full path: `/api/health`)
- Depends on: `@workspace/db`, `@workspace/api-zod`
- `pnpm --filter @workspace/api-server run dev` — run the dev server
- `pnpm --filter @workspace/api-server run build` — production esbuild bundle (`dist/index.cjs`)
- Build bundles an allowlist of deps (express, cors, pg, drizzle-orm, zod, etc.) and externalizes the rest

### `lib/db` (`@workspace/db`)

Database layer using Drizzle ORM with PostgreSQL. Exports a Drizzle client instance and schema models.

- `src/index.ts` — creates a `Pool` + Drizzle instance, exports schema
- `src/schema/index.ts` — barrel re-export of all models
- `src/schema/<modelname>.ts` — table definitions with `drizzle-zod` insert schemas (no models definitions exist right now)
- `drizzle.config.ts` — Drizzle Kit config (requires `DATABASE_URL`, automatically provided by Replit)
- Exports: `.` (pool, db, schema), `./schema` (schema only)

Production migrations are handled by Replit when publishing. In development, we just use `pnpm --filter @workspace/db run push`, and we fallback to `pnpm --filter @workspace/db run push-force`.

### `lib/api-spec` (`@workspace/api-spec`)

Owns the OpenAPI 3.1 spec (`openapi.yaml`) and the Orval config (`orval.config.ts`). Running codegen produces output into two sibling packages:

1. `lib/api-client-react/src/generated/` — React Query hooks + fetch client
2. `lib/api-zod/src/generated/` — Zod schemas

Run codegen: `pnpm --filter @workspace/api-spec run codegen`

### `lib/api-zod` (`@workspace/api-zod`)

Generated Zod schemas from the OpenAPI spec (e.g. `HealthCheckResponse`). Used by `api-server` for response validation.

### `lib/api-client-react` (`@workspace/api-client-react`)

Generated React Query hooks and fetch client from the OpenAPI spec (e.g. `useHealthCheck`, `healthCheck`).

### `scripts` (`@workspace/scripts`)

Utility scripts package. Each script is a `.ts` file in `src/` with a corresponding npm script in `package.json`. Run scripts via `pnpm --filter @workspace/scripts run <script>`. Scripts can import any workspace package (e.g., `@workspace/db`) by adding it as a dependency in `scripts/package.json`.
