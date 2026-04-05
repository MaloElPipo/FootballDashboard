"""Betclic scraper — gRPC-web + ng-state (pur HTTP, pas de Playwright).

Marchés supportés :
  • 1X2 (Résultat du match)      — via ng-state listing
  • Double chance                — via ng-state listing
  • Total buts / BTTS            — via gRPC par match
  • Buteur / Passeur             — via gRPC par match
  • Outrights (Vainqueur, Finale…) — via ng-state page outright

Architecture :
  fetch_competition_page()  → ng-state → matchs + 1X2 inline
  fetch_match_grpc()        → gRPC     → buteurs, passeurs, totals
  fetch_outright_page()     → ng-state → vainqueur compétition, etc.
  scrape_betclic()          → orchestrateur configurable
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_GRPC_ENDPOINT = (
    "https://offering.begmedia.com/web/offering.access.api"
    "/offering.access.api.MatchService/GetMatchWithNotification"
)
_BASE_URL = "https://www.betclic.fr"

_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

_GRPC_HEADERS = {
    **_PAGE_HEADERS,
    "content-type": "application/grpc-web+proto",
    "x-grpc-web": "1",
    "x-bg-ref-platform": "DESKTOP",
    "x-bg-regulation": "FR",
    "x-bg-ref-brand": "BETCLIC",
    "x-bg-ref-regulator-zone": "FR",
    "origin": _BASE_URL,
    "referer": f"{_BASE_URL}/",
}


COMPETITIONS: dict[str, dict[str, Any]] = {
    "world_cup_2026": {
        "slug": "coupe-du-monde-2026-c1",
        "sport_prefix": "football-sfootball",
        "comp_id": "1",
        "outright_match_id": 608035523850240,
    },
    "ligue_1": {
        "slug": "ligue-1-s4",
        "sport_prefix": "football-s1",
        "comp_id": "4",
    },
    "premier_league": {
        "slug": "premier-league-s3",
        "sport_prefix": "football-s1",
        "comp_id": "3",
    },
    "la_liga": {
        "slug": "laliga-s7",
        "sport_prefix": "football-s1",
        "comp_id": "7",
    },
    "bundesliga": {
        "slug": "bundesliga-s5",
        "sport_prefix": "football-s1",
        "comp_id": "5",
    },
    "serie_a": {
        "slug": "serie-a-s6",
        "sport_prefix": "football-s1",
        "comp_id": "6",
    },
    "champions_league": {
        "slug": "champions-league-s15",
        "sport_prefix": "football-s1",
        "comp_id": "8",
    },
    "europa_league": {
        "slug": "ligue-europa-s3453",
        "sport_prefix": "football-s1",
        "comp_id": "3453",
    },
}


@dataclass
class BetclicSelection:
    market_type: str
    selection_name: str
    odds: float
    market_name: str = ""

    def to_dict(self) -> dict:
        return {
            "market_type": self.market_type,
            "selection_name": self.selection_name,
            "odds": self.odds,
            "market_name": self.market_name,
        }


@dataclass
class BetclicMatch:
    home_team: str
    away_team: str
    match_id: int
    kickoff_utc: datetime | None = None
    competition: str = ""
    selections: list[BetclicSelection] = field(default_factory=list)

    def odds_1x2(self) -> dict[str, float] | None:
        h = next((s for s in self.selections if s.market_type == "1x2_home"), None)
        d = next((s for s in self.selections if s.market_type == "1x2_draw"), None)
        a = next((s for s in self.selections if s.market_type == "1x2_away"), None)
        if h and d and a:
            return {"home": h.odds, "draw": d.odds, "away": a.odds}
        return None

    def to_dict(self) -> dict:
        return {
            "home_team": self.home_team,
            "away_team": self.away_team,
            "match_id": self.match_id,
            "kickoff_utc": self.kickoff_utc.isoformat() if self.kickoff_utc else None,
            "competition": self.competition,
            "selections": [s.to_dict() for s in self.selections],
        }


@dataclass
class BetclicOutright:
    market_name: str
    competition: str
    selections: list[BetclicSelection] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market_name": self.market_name,
            "competition": self.competition,
            "selections": sorted(
                [s.to_dict() for s in self.selections],
                key=lambda x: x["odds"],
            ),
        }


def _parse_ng_state(html: str) -> dict:
    for pattern in [
        r'<script[^>]*id="ng-state"[^>]*type="application/json"[^>]*>(.*?)</script>',
        r'<script[^>]*type="application/json"[^>]*id="ng-state"[^>]*>(.*?)</script>',
    ]:
        m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
        if m:
            try:
                return json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                return {}
    return {}


def _parse_kickoff(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        cleaned = raw.replace("Z", "").split(".")[0] + "+00:00"
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _varint_encode(value: int) -> bytes:
    result = b""
    while value > 0x7F:
        result += bytes([(value & 0x7F) | 0x80])
        value >>= 7
    return result + bytes([value & 0x7F])


def _grpc_body(match_id: int) -> bytes:
    lang = b"fr"
    proto = (
        b"\x08" + _varint_encode(match_id)
        + b"\x12" + _varint_encode(len(lang)) + lang
    )
    return b"\x00" + struct.pack(">I", len(proto)) + proto


def _proto_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    raise ValueError("truncated varint")


def _proto_fields(data: bytes) -> dict[int, list]:
    out: dict[int, list] = {}
    pos, n = 0, len(data)
    while pos < n:
        tag, pos = _proto_varint(data, pos)
        fn, wt = tag >> 3, tag & 7
        if wt == 0:
            val, pos = _proto_varint(data, pos)
        elif wt == 1:
            val = data[pos: pos + 8]; pos += 8
        elif wt == 2:
            ln, pos = _proto_varint(data, pos)
            val = data[pos: pos + ln]; pos += ln
        elif wt == 5:
            val = data[pos: pos + 4]; pos += 4
        else:
            break
        out.setdefault(fn, []).append(val)
    return out


_GOALSCORER_LABELS = (
    "buteur (tps r",
    "buteur anytime",
    "scorer anytime",
    "buteur ou son remplaçant",
)
_ASSIST_LABELS = ("passeur", "joueur décisif", "joueur decisif")
_MATCH_RESULT_LABELS = ("résultat du match", "match result", "1x2")
_DOUBLE_CHANCE_LABELS = ("double chance",)
_TOTAL_GOALS_LABELS = ("nombre total de buts", "total goals", "plus/moins")
_BTTS_LABELS = ("2 équipes marquent", "both teams to score", "les deux équipes marquent")


def _classify_grpc_market(name: str) -> str | None:
    lower = name.lower()
    if any(x in lower for x in _GOALSCORER_LABELS):
        return "goalscorer"
    if any(x in lower for x in _ASSIST_LABELS):
        return "assist"
    if any(x in lower for x in _MATCH_RESULT_LABELS):
        return "1x2"
    if any(x in lower for x in _DOUBLE_CHANCE_LABELS):
        return "double_chance"
    if any(x in lower for x in _TOTAL_GOALS_LABELS):
        return "total_goals"
    if any(x in lower for x in _BTTS_LABELS):
        return "btts"
    return None


async def _stream_grpc_frame(
    client: httpx.AsyncClient, body: bytes
) -> bytes:
    data = b""
    needed: int | None = None
    async with client.stream(
        "POST", _GRPC_ENDPOINT, content=body,
        headers=_GRPC_HEADERS,
        timeout=httpx.Timeout(30.0, connect=10.0),
    ) as r:
        r.raise_for_status()
        async for chunk in r.aiter_bytes():
            data += chunk
            if needed is None and len(data) >= 5:
                flags = data[0]
                frame_len = struct.unpack(">I", data[1:5])[0]
                needed = 5 + frame_len
                if flags != 0x00:
                    await r.aclose()
                    return b""
            if needed is not None and len(data) >= needed:
                await r.aclose()
                break
    if needed is None or len(data) < needed:
        return b""
    frame_len = struct.unpack(">I", data[1:5])[0]
    return data[5: 5 + frame_len]


def _parse_grpc_markets(
    raw: bytes,
    market_filter: set[str] | None = None,
) -> list[BetclicSelection]:
    try:
        root = _proto_fields(raw)
        f1 = _proto_fields(root[1][0])
        f1f1 = _proto_fields(f1[1][0])
        f11 = _proto_fields(f1f1[11][0])
        markets = f11.get(3, [])
    except (KeyError, IndexError, ValueError):
        return []

    selections: list[BetclicSelection] = []
    for market_bytes in markets:
        try:
            market = _proto_fields(market_bytes)
        except Exception:
            continue
        name_raw = market.get(2, [b""])[0]
        market_name = name_raw.decode("utf-8", errors="replace") if name_raw else ""
        market_type = _classify_grpc_market(market_name)
        if not market_type:
            continue
        if market_filter and market_type not in market_filter:
            continue

        state = market.get(9, [0])[0]
        if state == 3:
            continue

        for group_bytes in market.get(11, []):
            try:
                group = _proto_fields(group_bytes)
            except Exception:
                continue
            for sel_bytes in group.get(2, []):
                try:
                    sel = _proto_fields(sel_bytes)
                except Exception:
                    continue
                name_b = (sel.get(10) or sel.get(11) or [None])[0]
                if not name_b:
                    continue
                sel_name = name_b.decode("utf-8", errors="replace").strip()
                if not sel_name:
                    continue
                odds_raw = (sel.get(12) or [None])[0]
                if not odds_raw or len(odds_raw) != 8:
                    continue
                try:
                    odds_val = struct.unpack("<d", odds_raw)[0]
                    if not (1.01 <= odds_val <= 1000.0):
                        continue
                    selections.append(BetclicSelection(
                        market_type=market_type,
                        selection_name=sel_name,
                        odds=round(odds_val, 2),
                        market_name=market_name,
                    ))
                except struct.error:
                    continue
    return selections


class BetclicScraper:
    def __init__(self) -> None:
        self._page_client: httpx.AsyncClient | None = None
        self._grpc_client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "BetclicScraper":
        self._page_client = httpx.AsyncClient(
            headers=_PAGE_HEADERS, follow_redirects=True
        )
        self._grpc_client = httpx.AsyncClient(
            headers=_GRPC_HEADERS, follow_redirects=True
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._page_client:
            await self._page_client.aclose()
        if self._grpc_client:
            await self._grpc_client.aclose()

    def _comp_url(self, comp_key: str) -> str:
        comp = COMPETITIONS[comp_key]
        return f"{_BASE_URL}/{comp['sport_prefix']}/{comp['slug']}"

    async def fetch_competition_matches(
        self, comp_key: str
    ) -> tuple[list[BetclicMatch], int | None]:
        assert self._page_client
        comp = COMPETITIONS[comp_key]
        url = self._comp_url(comp_key)

        try:
            r = await self._page_client.get(url, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Betclic page fetch failed %s: %s", url, exc)
            return [], None

        ng = _parse_ng_state(r.text)
        matches: list[dict] = []
        outright_match_id: int | None = comp.get("outright_match_id")

        comp_id = comp.get("comp_id", "")
        all_raw_matches: list[dict] = []

        for _key, val in ng.items():
            if not isinstance(val, dict):
                continue
            payload = val.get("response", {}).get("payload", {})
            raw_matches = payload.get("matches", [])
            if raw_matches:
                all_raw_matches.extend(raw_matches)
            if payload.get("hasOutright") and not outright_match_id:
                for m2_key, m2_val in ng.items():
                    if not isinstance(m2_val, dict):
                        continue
                    m2_payload = m2_val.get("response", {}).get("payload", {})
                    m2_match = m2_payload.get("match", {})
                    if m2_match.get("matchId") and m2_match.get("name"):
                        outright_match_id = int(m2_match["matchId"])

        matches = all_raw_matches

        now = datetime.now(UTC)
        results: list[BetclicMatch] = []

        for mx in matches:
            if comp_id:
                mx_comp = mx.get("competition", {})
                if mx_comp and mx_comp.get("id") and str(mx_comp["id"]) != str(comp_id):
                    continue
            kickoff = _parse_kickoff(mx.get("matchDateUtc"))
            if kickoff and kickoff < now:
                continue
            contestants = mx.get("contestants", [])
            if len(contestants) < 2:
                continue
            home = contestants[0].get("name", "")
            away = contestants[1].get("name", "")
            match_id_raw = mx.get("matchId")
            if not home or not away or not match_id_raw:
                continue

            bm = BetclicMatch(
                home_team=home,
                away_team=away,
                match_id=int(match_id_raw),
                kickoff_utc=kickoff,
                competition=comp_key,
            )

            market_data = mx.get("market", {})
            if market_data:
                main_sels = market_data.get("mainSelections", [])
                market_name = market_data.get("name", "")
                for i, sel in enumerate(main_sels):
                    sel_name = sel.get("name", "")
                    odds = sel.get("odds")
                    status = sel.get("status", 0)
                    if not sel_name or not odds or status != 1:
                        continue
                    if len(main_sels) == 3:
                        if i == 0:
                            mtype = "1x2_home"
                        elif i == 1:
                            mtype = "1x2_draw"
                        else:
                            mtype = "1x2_away"
                    else:
                        mtype = "1x2_other"
                    bm.selections.append(BetclicSelection(
                        market_type=mtype,
                        selection_name=sel_name,
                        odds=float(odds),
                        market_name=market_name,
                    ))

            results.append(bm)

        return results, outright_match_id

    async def fetch_match_grpc(
        self,
        match_id: int,
        market_filter: set[str] | None = None,
    ) -> list[BetclicSelection]:
        assert self._grpc_client
        body = _grpc_body(match_id)
        try:
            raw = await _stream_grpc_frame(self._grpc_client, body)
        except Exception as exc:
            logger.warning("Betclic gRPC match %d: %s", match_id, exc)
            return []
        return _parse_grpc_markets(raw, market_filter) if raw else []

    async def fetch_outright(
        self, comp_key: str, outright_match_id: int | None = None
    ) -> list[BetclicOutright]:
        assert self._page_client
        comp = COMPETITIONS[comp_key]
        mid = outright_match_id or comp.get("outright_match_id")
        if not mid:
            return []

        slug = comp["slug"]
        sport_prefix = comp["sport_prefix"]
        comp_name_slug = slug.split("-c")[0] if "-c" in slug else slug.split("-s")[0]
        url = f"{_BASE_URL}/{sport_prefix}/{slug}/{comp_name_slug}-m{mid}"

        try:
            r = await self._page_client.get(url, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Betclic outright fetch failed %s: %s", url, exc)
            return []

        ng = _parse_ng_state(r.text)
        outrights: list[BetclicOutright] = []

        for _key, val in ng.items():
            if not isinstance(val, dict):
                continue
            payload = val.get("response", {}).get("payload", {})
            match = payload.get("match", {})
            if not match or not match.get("matchId"):
                continue

            for sc in match.get("subCategories", []):
                for mkt in sc.get("markets", []):
                    market_name = mkt.get("name", "")
                    matrix = mkt.get("selectionMatrix", [])
                    main_sels = mkt.get("mainSelections", [])

                    items: list[BetclicSelection] = []

                    for entry in matrix:
                        for sel_wrap in entry.get("selections", []):
                            oneof = sel_wrap.get("selectionOneof", {})
                            sel = oneof.get("selection", {})
                            if not sel:
                                continue
                            name = sel.get("name", "")
                            odds = sel.get("odds")
                            status = sel.get("status", 0)
                            if name and odds and status == 1:
                                items.append(BetclicSelection(
                                    market_type="outright",
                                    selection_name=name,
                                    odds=float(odds),
                                    market_name=market_name,
                                ))

                    for sel in main_sels:
                        name = sel.get("name", "")
                        odds = sel.get("odds")
                        status = sel.get("status", 0)
                        if name and odds and status == 1:
                            items.append(BetclicSelection(
                                market_type="outright",
                                selection_name=name,
                                odds=float(odds),
                                market_name=market_name,
                            ))

                    if items:
                        outrights.append(BetclicOutright(
                            market_name=market_name,
                            competition=comp_key,
                            selections=items,
                        ))
            break

        return outrights

    async def scrape_competition(
        self,
        comp_key: str,
        include_1x2: bool = True,
        include_goalscorer: bool = False,
        include_assist: bool = False,
        include_outright: bool = False,
        grpc_delay: float = 0.3,
    ) -> dict[str, Any]:
        matches, outright_mid = await self.fetch_competition_matches(comp_key)
        logger.info(
            "Betclic %s: %d matchs trouvés (outright_mid=%s)",
            comp_key, len(matches), outright_mid,
        )

        grpc_types: set[str] = set()
        if include_goalscorer:
            grpc_types.add("goalscorer")
        if include_assist:
            grpc_types.add("assist")

        if grpc_types:
            for i, bm in enumerate(matches):
                sels = await self.fetch_match_grpc(bm.match_id, grpc_types)
                bm.selections.extend(sels)
                if i < len(matches) - 1:
                    await asyncio.sleep(grpc_delay)

        outrights: list[BetclicOutright] = []
        if include_outright:
            outrights = await self.fetch_outright(comp_key, outright_mid)

        if not include_1x2:
            for bm in matches:
                bm.selections = [
                    s for s in bm.selections
                    if s.market_type not in ("1x2_home", "1x2_draw", "1x2_away")
                ]

        return {
            "competition": comp_key,
            "matches": matches,
            "outrights": outrights,
        }


async def scrape_betclic(
    competitions: list[str] | None = None,
    include_1x2: bool = True,
    include_goalscorer: bool = False,
    include_assist: bool = False,
    include_outright: bool = False,
) -> list[dict[str, Any]]:
    if competitions is None:
        competitions = ["world_cup_2026"]

    results: list[dict[str, Any]] = []
    async with BetclicScraper() as scraper:
        for i, comp_key in enumerate(competitions):
            if comp_key not in COMPETITIONS:
                logger.warning("Compétition inconnue: %s", comp_key)
                continue
            try:
                data = await scraper.scrape_competition(
                    comp_key,
                    include_1x2=include_1x2,
                    include_goalscorer=include_goalscorer,
                    include_assist=include_assist,
                    include_outright=include_outright,
                )
                results.append(data)
            except Exception as exc:
                logger.error("Betclic %s: %s", comp_key, exc)
            if i < len(competitions) - 1:
                await asyncio.sleep(0.5)
    return results


async def quick_1x2(comp_key: str = "world_cup_2026") -> list[dict]:
    async with BetclicScraper() as scraper:
        matches, _ = await scraper.fetch_competition_matches(comp_key)
    return [
        {
            "home": m.home_team,
            "away": m.away_team,
            "kickoff": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
            **m.odds_1x2(),
        }
        for m in matches if m.odds_1x2()
    ]


async def quick_outright(comp_key: str = "world_cup_2026") -> list[dict]:
    async with BetclicScraper() as scraper:
        _, outright_mid = await scraper.fetch_competition_matches(comp_key)
        outrights = await scraper.fetch_outright(comp_key, outright_mid)
    return [o.to_dict() for o in outrights]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    async def _main() -> None:
        comp = sys.argv[1] if len(sys.argv) > 1 else "world_cup_2026"
        print(f"\n{'='*60}")
        print(f"Scraping Betclic: {comp}")
        print(f"{'='*60}")

        results = await scrape_betclic(
            [comp],
            include_1x2=True,
            include_goalscorer=True,
            include_assist=True,
            include_outright=True,
        )

        for data in results:
            matches = data["matches"]
            outrights = data["outrights"]
            print(f"\nMatchs: {len(matches)}")

            for m in matches:
                ko = m.kickoff_utc.strftime("%d/%m %H:%M") if m.kickoff_utc else "?"
                odds = m.odds_1x2()
                odds_str = f"1={odds['home']:.2f} X={odds['draw']:.2f} 2={odds['away']:.2f}" if odds else "pas encore de cotes"
                print(f"  {m.home_team} vs {m.away_team} ({ko}) — {odds_str}")

                gs = [s for s in m.selections if s.market_type == "goalscorer"]
                if gs:
                    print(f"    Buteurs ({len(gs)}):")
                    for s in sorted(gs, key=lambda x: x.odds)[:5]:
                        print(f"      {s.selection_name:<30} {s.odds:.2f}")

                assists = [s for s in m.selections if s.market_type == "assist"]
                if assists:
                    print(f"    Passeurs ({len(assists)}):")
                    for s in sorted(assists, key=lambda x: x.odds)[:5]:
                        print(f"      {s.selection_name:<30} {s.odds:.2f}")

            for o in outrights:
                print(f"\n  === {o.market_name} ===")
                for s in sorted(o.selections, key=lambda x: x.odds)[:10]:
                    print(f"    {s.selection_name:<25} {s.odds}")

    asyncio.run(_main())
