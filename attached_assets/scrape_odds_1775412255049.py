#!/usr/bin/env python3
"""Standalone scraper — Unibet & Betclic (buteurs / passeurs).

Dépendances : Python ≥ 3.11, httpx
    pip install httpx

Pas de Playwright, pas de LLM, pas de base de données.

Usage :
    python scrape_odds.py                          # tout scraper, sortie texte
    python scrape_odds.py --bookmaker unibet       # Unibet seulement
    python scrape_odds.py --bookmaker betclic      # Betclic seulement
    python scrape_odds.py --league ligue_1         # une seule ligue
    python scrape_odds.py --output json            # JSON sur stdout
    python scrape_odds.py --output json > cotes.json
"""
from __future__ import annotations

import argparse
import asyncio
import codecs
import json
import logging
import re
import struct
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

# ──────────────────────────────────────────────────────────────────────────────
# Structures partagées
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SelectionOdds:
    market_type: str   # "goalscorer" | "assist"
    player_name: str
    odds: float
    bookmaker: str

@dataclass
class MatchOdds:
    home_team: str
    away_team: str
    kickoff_utc: datetime | None
    league: str
    bookmaker: str
    selections: list[SelectionOdds] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# UNIBET — API LVS (pur HTTP, post-fusion PSEL mars 2026)
# ──────────────────────────────────────────────────────────────────────────────

_UNIBET_BASE = "https://www.unibet.fr"

_UNIBET_NODE_IDS: dict[str, int] = {
    "ligue_1":          58531576,
    "premier_league":   58532401,
    "bundesliga":       58529612,
    "la_liga":          58532237,
    "serie_a":          58529754,
    "champions_league": 58532497,
}

_UNIBET_MARKET_TYPES: dict[int, str] = {
    31:        "goalscorer",   # Buteur anytime (priorité haute)
    4:         "goalscorer",   # 1er Buteur     (priorité basse)
    100002524: "assist",       # Passeur décisif
}

_UNIBET_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.unibet.fr/",
}

_UNIBET_LIST_PARAMS = "lineId=1&originId=3&ext=1&showPromotions=true&showMarketTypeGroups=true"


def _unibet_parse_price(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("null", "", "none"):
        return None
    try:
        f = float(s.replace(",", "."))
    except ValueError:
        return None
    return f if 1.01 <= f <= 1000.0 else None


def _unibet_parse_start(value: Any) -> datetime | None:
    """Parse format YYMMDDHHMM → datetime UTC. Ex: '2604051930' → 2026-04-05 19:30."""
    if not value:
        return None
    s = str(value).strip()
    if len(s) != 10:
        return None
    try:
        return datetime(
            2000 + int(s[0:2]), int(s[2:4]), int(s[4:6]),
            int(s[6:8]), int(s[8:10]), tzinfo=UTC,
        )
    except (ValueError, IndexError):
        return None


class UnibetScraper:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._token: str | None = None

    async def _get_token(self) -> None:
        r = await self._client.get(
            f"{_UNIBET_BASE}/lvs-api/acc/token", headers=_UNIBET_HEADERS, timeout=10
        )
        r.raise_for_status()
        self._token = r.json()["hsToken"]

    def _auth_headers(self) -> dict[str, str]:
        return {**_UNIBET_HEADERS, "X-LVS-HSToken": self._token or ""}

    async def _fetch_event_ids(
        self, league: str
    ) -> list[tuple[int, str, str, datetime | None]]:
        node_id = _UNIBET_NODE_IDS.get(league)
        if not node_id:
            return []
        url = f"{_UNIBET_BASE}/lvs-api/next/50/p{node_id}?{_UNIBET_LIST_PARAMS}"
        try:
            r = await self._client.get(url, headers=self._auth_headers(), timeout=15)
            r.raise_for_status()
        except Exception as exc:
            logging.warning("Unibet: fetch_event_ids %s: %s", league, exc)
            return []

        items = r.json().get("items", {})
        now = datetime.now(UTC)
        results = []
        for key, val in items.items():
            if not re.match(r"^e\d+$", key):
                continue
            kickoff = _unibet_parse_start(val.get("start"))
            if kickoff and kickoff < now:
                continue
            home, away = val.get("a", ""), val.get("b", "")
            if home and away:
                results.append((int(key[1:]), home, away, kickoff))
        return results

    def _parse_event(self, items: dict[str, Any], league: str) -> MatchOdds | None:
        event_key = next((k for k in items if re.match(r"^e\d+$", k)), None)
        if not event_key:
            return None
        ev = items[event_key]
        home, away = ev.get("a", ""), ev.get("b", "")
        if not home or not away:
            return None
        kickoff = _unibet_parse_start(ev.get("start"))

        target: dict[str, tuple[int, str]] = {}
        for key, val in items.items():
            if not key.startswith("m"):
                continue
            mtype_id = val.get("markettypeId")
            if mtype_id not in _UNIBET_MARKET_TYPES:
                continue
            if val.get("parent") != event_key:
                continue
            target[key] = (mtype_id, _UNIBET_MARKET_TYPES[mtype_id])

        if not target:
            return None

        anytime: dict[str, SelectionOdds] = {}
        first:   dict[str, SelectionOdds] = {}
        assist:  dict[str, SelectionOdds] = {}

        for key, val in items.items():
            if not key.startswith("o"):
                continue
            parent = val.get("parent", "")
            if parent not in target:
                continue
            mtype_id, market_type = target[parent]
            player = (val.get("desc") or "").strip()
            if not player:
                continue
            odds = _unibet_parse_price(val.get("price"))
            if odds is None:
                continue
            sel = SelectionOdds(market_type=market_type, player_name=player,
                                odds=odds, bookmaker="unibet")
            name_lc = player.lower()
            if market_type == "assist":
                assist.setdefault(name_lc, sel)
            elif mtype_id == 31:
                anytime.setdefault(name_lc, sel)
            else:
                first.setdefault(name_lc, sel)

        mo = MatchOdds(home_team=home, away_team=away, kickoff_utc=kickoff,
                       league=league, bookmaker="unibet")
        mo.selections = list({**first, **anytime}.values()) + list(assist.values())
        return mo

    async def scrape_league(self, league: str) -> list[MatchOdds]:
        events = await self._fetch_event_ids(league)
        results: list[MatchOdds] = []
        for event_id, home, away, kickoff in events:
            url = f"{_UNIBET_BASE}/lvs-api/ff/e{event_id}?{_UNIBET_LIST_PARAMS}"
            try:
                r = await self._client.get(url, headers=self._auth_headers(), timeout=15)
                r.raise_for_status()
                items = r.json().get("items", {})
            except Exception as exc:
                logging.debug("Unibet: ff/e%d: %s", event_id, exc)
                await asyncio.sleep(0.3)
                continue
            mo = self._parse_event(items, league)
            if mo and mo.selections:
                results.append(mo)
            await asyncio.sleep(0.3)
        return results


async def scrape_unibet(leagues: list[str]) -> list[MatchOdds]:
    """Scrape Unibet via l'API LVS (pur HTTP, pas de Playwright)."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        scraper = UnibetScraper(client)
        try:
            await scraper._get_token()
        except Exception as exc:
            logging.error("Unibet: impossible d'obtenir le token LVS: %s", exc)
            return []
        all_matches: list[MatchOdds] = []
        for league in leagues:
            try:
                all_matches.extend(await scraper.scrape_league(league))
            except Exception as exc:
                logging.error("Unibet: %s: %s", league, exc)
    return all_matches


# ──────────────────────────────────────────────────────────────────────────────
# BETCLIC — API gRPC-web (pur HTTP, pas de Playwright)
# ──────────────────────────────────────────────────────────────────────────────

_BETCLIC_GRPC = (
    "https://offering.begmedia.com/web/offering.access.api"
    "/offering.access.api.MatchService/GetMatchWithNotification"
)
_BETCLIC_BASE = "https://www.betclic.fr"

BETCLIC_LEAGUES: dict[str, tuple[str, str]] = {
    "ligue_1":          ("ligue-1-s4",            "4"),
    "ligue_2":          ("ligue-2-s19",            "19"),
    "premier_league":   ("premier-league-s3",      "3"),
    "la_liga":          ("laliga-s7",              "7"),
    "bundesliga":       ("bundesliga-s5",           "5"),
    "serie_a":          ("serie-a-s6",             "6"),
    "champions_league": ("champions-league-s15",   "8"),
    "europa_league":    ("ligue-europa-s3453",     "3453"),
    "coupe_de_france":  ("coupe-de-france-s36",    "36"),
}

_BETCLIC_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}

_BETCLIC_GRPC_HEADERS = {
    **_BETCLIC_PAGE_HEADERS,
    "content-type": "application/grpc-web+proto",
    "x-grpc-web": "1",
    "x-bg-ref-platform": "DESKTOP",
    "x-bg-regulation": "FR",
    "x-bg-ref-brand": "BETCLIC",
    "x-bg-ref-regulator-zone": "FR",
    "origin": "https://www.betclic.fr",
    "referer": "https://www.betclic.fr/",
}

_BETCLIC_GOALSCORER_LABELS = ("buteur (tps r", "buteur anytime", "scorer anytime")
_BETCLIC_ASSIST_LABELS     = ("passeur", "joueur décisif", "joueur decisif")


def _betclic_varint_encode(value: int) -> bytes:
    result = b""
    while value > 0x7F:
        result += bytes([(value & 0x7F) | 0x80])
        value >>= 7
    return result + bytes([value & 0x7F])


def _betclic_grpc_body(match_id: int) -> bytes:
    lang = b"fr"
    proto = (
        b"\x08" + _betclic_varint_encode(match_id)
        + b"\x12" + _betclic_varint_encode(len(lang)) + lang
    )
    return b"\x00" + struct.pack(">I", len(proto)) + proto


def _betclic_classify(name: str) -> str | None:
    lower = name.lower()
    if any(x in lower for x in _BETCLIC_GOALSCORER_LABELS):
        return "goalscorer"
    if any(x in lower for x in _BETCLIC_ASSIST_LABELS):
        return "assist"
    return None


def _betclic_parse_kickoff(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        cleaned = raw.replace("Z", "").split(".")[0] + "+00:00"
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return None


def _betclic_parse_ng_state(html: str) -> dict:
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


async def _betclic_stream_first_frame(
    client: httpx.AsyncClient, body: bytes
) -> bytes:
    data = b""
    needed: int | None = None
    async with client.stream(
        "POST", _BETCLIC_GRPC, content=body,
        headers=_BETCLIC_GRPC_HEADERS,
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


def _betclic_parse_proto(raw: bytes) -> list[SelectionOdds]:
    try:
        root  = _proto_fields(raw)
        f1    = _proto_fields(root[1][0])
        f1f1  = _proto_fields(f1[1][0])
        f11   = _proto_fields(f1f1[11][0])
        markets = f11.get(3, [])
    except (KeyError, IndexError, ValueError):
        return []

    selections: list[SelectionOdds] = []
    for market_bytes in markets:
        try:
            market = _proto_fields(market_bytes)
        except Exception:
            continue
        name_raw = market.get(2, [b""])[0]
        market_name = name_raw.decode("utf-8", errors="replace") if name_raw else ""
        market_type = _betclic_classify(market_name)
        if not market_type:
            continue
        if market.get(9, [0])[0] == 3:
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
                player = name_b.decode("utf-8", errors="replace").strip()
                if not player:
                    continue
                odds_raw = (sel.get(12) or [None])[0]
                if not odds_raw or len(odds_raw) != 8:
                    continue
                try:
                    odds_val = struct.unpack("<d", odds_raw)[0]
                    if not (1.01 <= odds_val <= 1000.0):
                        continue
                    selections.append(SelectionOdds(
                        market_type=market_type, player_name=player,
                        odds=round(odds_val, 2), bookmaker="betclic",
                    ))
                except struct.error:
                    continue
    return selections


class BetclicScraper:
    def __init__(
        self,
        page_client: httpx.AsyncClient,
        grpc_client: httpx.AsyncClient,
    ) -> None:
        self._page = page_client
        self._grpc = grpc_client

    async def fetch_competition_matches(self, league: str) -> list[dict]:
        slug, comp_id = BETCLIC_LEAGUES[league]
        url = f"{_BETCLIC_BASE}/football-s1/{slug}/"
        try:
            r = await self._page.get(url, timeout=20)
            r.raise_for_status()
        except Exception as exc:
            logging.warning("Betclic: page fetch failed %s: %s", url, exc)
            return []

        ng = _betclic_parse_ng_state(r.text)
        payload = ng.get("grpc:4011162472", {}).get("response", {}).get("payload", {})
        if not payload:
            logging.warning("Betclic: no ng-state payload for %s", league)
            return []

        now = datetime.now(UTC)
        results = []
        for mx in payload.get("matches", []):
            kickoff = _betclic_parse_kickoff(mx.get("matchDateUtc"))
            if kickoff and kickoff < now:
                continue
            contestants = mx.get("contestants", [])
            if len(contestants) < 2:
                continue
            home, away = contestants[0].get("name", ""), contestants[1].get("name", "")
            match_id_raw = mx.get("matchId")
            if not home or not away or not match_id_raw:
                continue
            competition = mx.get("competition", {})
            if competition.get("id", "") != comp_id:
                continue
            results.append({
                "match_id": int(match_id_raw),
                "home_team": home,
                "away_team": away,
                "kickoff_utc": kickoff,
                "league": league,
            })
        return results

    async def fetch_match_odds(self, match_id: int) -> list[SelectionOdds]:
        body = _betclic_grpc_body(match_id)
        try:
            raw = await _betclic_stream_first_frame(self._grpc, body)
        except Exception as exc:
            logging.warning("Betclic: gRPC match %d: %s", match_id, exc)
            return []
        return _betclic_parse_proto(raw) if raw else []

    async def scrape_league(self, league: str) -> list[MatchOdds]:
        matches = await self.fetch_competition_matches(league)
        results: list[MatchOdds] = []
        for i, mx in enumerate(matches):
            sels = await self.fetch_match_odds(mx["match_id"])
            if sels:
                mo = MatchOdds(
                    home_team=mx["home_team"], away_team=mx["away_team"],
                    kickoff_utc=mx.get("kickoff_utc"), league=league,
                    bookmaker="betclic",
                )
                mo.selections = sels
                results.append(mo)
            if i < len(matches) - 1:
                await asyncio.sleep(0.3)
        return results


async def scrape_betclic(leagues: list[str]) -> list[MatchOdds]:
    """Scrape Betclic via gRPC-web (pur HTTP, pas de Playwright)."""
    async with (
        httpx.AsyncClient(headers=_BETCLIC_PAGE_HEADERS, follow_redirects=True) as page_client,
        httpx.AsyncClient(headers=_BETCLIC_GRPC_HEADERS, follow_redirects=True) as grpc_client,
    ):
        scraper = BetclicScraper(page_client, grpc_client)
        all_matches: list[MatchOdds] = []
        for i, league in enumerate(leagues):
            try:
                all_matches.extend(await scraper.scrape_league(league))
            except Exception as exc:
                logging.error("Betclic: %s: %s", league, exc)
            if i < len(leagues) - 1:
                await asyncio.sleep(0.5)
    return all_matches


# ──────────────────────────────────────────────────────────────────────────────
# Sortie
# ──────────────────────────────────────────────────────────────────────────────

def _to_dict(m: MatchOdds) -> dict:
    return {
        "bookmaker":   m.bookmaker,
        "league":      m.league,
        "home_team":   m.home_team,
        "away_team":   m.away_team,
        "kickoff_utc": m.kickoff_utc.isoformat() if m.kickoff_utc else None,
        "selections":  [
            {
                "market_type": s.market_type,
                "player_name": s.player_name,
                "odds":        s.odds,
            }
            for s in sorted(m.selections, key=lambda x: x.odds)
        ],
    }


def _print_table(matches: list[MatchOdds]) -> None:
    total_sel = sum(len(m.selections) for m in matches)
    print(f"\n{'='*60}")
    print(f"Total : {len(matches)} matchs, {total_sel} sélections")
    print(f"{'='*60}")
    for m in matches:
        ko = m.kickoff_utc.strftime("%Y-%m-%d %H:%M UTC") if m.kickoff_utc else "?"
        print(f"\n[{m.bookmaker.upper()}] {m.home_team} vs {m.away_team}  ({m.league})  {ko}")
        goal   = [s for s in m.selections if s.market_type == "goalscorer"]
        assist = [s for s in m.selections if s.market_type == "assist"]
        if goal:
            print(f"  Buteurs ({len(goal)}) — top 5:")
            for s in sorted(goal, key=lambda x: x.odds)[:5]:
                print(f"    {s.player_name:<30} {s.odds:.2f}")
        if assist:
            print(f"  Passeurs ({len(assist)}) — top 5:")
            for s in sorted(assist, key=lambda x: x.odds)[:5]:
                print(f"    {s.player_name:<30} {s.odds:.2f}")


# ──────────────────────────────────────────────────────────────────────────────
# Ligues disponibles (union des deux bookmakers)
# ──────────────────────────────────────────────────────────────────────────────

_ALL_LEAGUES = sorted(
    set(_UNIBET_NODE_IDS.keys()) | set(BETCLIC_LEAGUES.keys())
)


async def _main(args: argparse.Namespace) -> None:
    leagues = [args.league] if args.league else None
    all_matches: list[MatchOdds] = []

    if args.bookmaker in ("unibet", "all"):
        unibet_leagues = leagues or list(_UNIBET_NODE_IDS.keys())
        logging.info("Unibet : scrape de %d ligue(s)…", len(unibet_leagues))
        all_matches.extend(await scrape_unibet(unibet_leagues))

    if args.bookmaker in ("betclic", "all"):
        betclic_leagues = leagues or list(BETCLIC_LEAGUES.keys())
        logging.info("Betclic : scrape de %d ligue(s)…", len(betclic_leagues))
        all_matches.extend(await scrape_betclic(betclic_leagues))

    if args.output == "json":
        print(json.dumps([_to_dict(m) for m in all_matches], ensure_ascii=False, indent=2))
    else:
        _print_table(all_matches)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Scrape les cotes buteur/passeur depuis Unibet et Betclic (pur HTTP)."
    )
    parser.add_argument(
        "--bookmaker",
        choices=["unibet", "betclic", "all"],
        default="all",
        help="Bookmaker à scraper (défaut: all)",
    )
    parser.add_argument(
        "--league",
        choices=_ALL_LEAGUES,
        default=None,
        help="Ligue (défaut: toutes)",
    )
    parser.add_argument(
        "--output",
        choices=["table", "json"],
        default="table",
        help="Format de sortie (défaut: table)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Logs détaillés",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    asyncio.run(_main(args))
