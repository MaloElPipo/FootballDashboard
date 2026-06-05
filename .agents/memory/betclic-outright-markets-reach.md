---
name: Betclic outright markets unreachable per-stage
description: Why the per-stage "Stade atteint" WC2026 markets can't be scraped via the current gRPC/ng-state path, and what would be required.
---

For the WC2026 outright event (Betclic), the gRPC `MatchService/GetMatchWithNotification`
returns ONLY ~6 markets: Vainqueur compétition, Vainqueur Double Chance, Stade de la
compétition atteint - **La Finale**, Gagnant/Meilleur buteur, Les Finalistes, Duo gagnant.

The per-stage variants ("Stade de la compétition atteint - Huitième / Quart / Demi de
finale") are **not reachable** through any path we can hit without a real browser. Verified
exhaustively:
- The match container in the gRPC response has a single field (3 = markets); no
  subcategory/market-group metadata to follow.
- The outright page ng-state has exactly ONE subcategory (name "") with those 6 markets;
  both gRPC TransferState payloads contain the same 6.
- Swept ALL ~41 `matchId`/`eventId` values found recursively in the competition-page
  ng-state via parallel gRPC probe — only the main event carries any "Stade atteint", and
  only "La Finale".
- Alternative gRPC methods (`GetMatch`, `GetMatchMarkets`, `GetMarkets`) return empty.
- Direct (no proxy) vs `BETCLIC_PROXY_URL` return the identical 6 markets → not geo/proxy.

**Why:** these per-stage markets are lazy-loaded by the Angular frontend when the user
clicks a market-group/subcategory tab, which fires a gRPC call with an extra request field
(market-group id) we have not reverse-engineered. The current minimal body is only
`field1=matchId, field2="fr"`.

**How to apply:** do NOT re-run the 41-event sweep or proxy comparison — that ground is
covered. To get the per-stage markets you must capture the exact gRPC request a headless
browser (Playwright) sends when selecting that tab, then replay it with the discovered
extra field. Faster: ask the user for the exact URL/screenshot of the market.
