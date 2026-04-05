from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from playwright.async_api import async_playwright


PROXY_URL = os.environ.get("WEBSHARE_PROXY_URL", "")

_BF_COMP_SLUGS = {
    "serie_a": "italian-serie-a",
    "premier_league": "english-premier-league",
    "la_liga": "spanish-la-liga",
    "bundesliga": "german-bundesliga",
    "ligue_1": "french-ligue-1",
    "champions_league": "uefa-champions-league",
    "europa_league": "uefa-europa-league",
    "world_cup_2026": "fifa-world-cup",
}

_BF_COMPETITION_IDS = {
    "serie_a": 81,
    "premier_league": 10932509,
    "la_liga": 117,
    "bundesliga": 59,
    "ligue_1": 55,
    "champions_league": 228,
    "europa_league": 2005,
    "world_cup_2026": 1,
}


@dataclass
class BetfairCSData:
    home_team: str = ""
    away_team: str = ""
    correct_scores: dict[str, float] = field(default_factory=dict)
    match_odds: dict[str, float] = field(default_factory=dict)
    over_under: dict[str, float] = field(default_factory=dict)
    timestamp: float = 0.0
    match_url: str = ""
    error: str = ""


def _parse_proxy():
    url = os.environ.get("WEBSHARE_PROXY_URL", "")
    if not url:
        return None
    m = re.match(r"https?://([^:]+):([^@]+)@([^:]+):(\d+)", url)
    if m:
        return {
            "server": f"http://{m.group(3)}:{m.group(4)}",
            "username": m.group(1),
            "password": m.group(2),
        }
    m2 = re.match(r"https?://([^:]+):(\d+)", url)
    if m2:
        return {"server": f"http://{m2.group(1)}:{m2.group(2)}"}
    return None


def _team_slug(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


async def _find_match_url(page, competition_key: str, home: str, away: str) -> str | None:
    comp_id = _BF_COMPETITION_IDS.get(competition_key)
    if not comp_id:
        return None

    comp_url = f"https://www.betfair.com/exchange/plus/en/football/competition/{comp_id}"
    try:
        await page.goto(comp_url, timeout=25000, wait_until="domcontentloaded")
    except Exception:
        return None
    await asyncio.sleep(6)

    match_href = await page.evaluate(
        """(args) => {
            const [home, away] = args;
            const hLow = home.toLowerCase();
            const aLow = away.toLowerCase();
            const allLinks = document.querySelectorAll('a');
            for (const a of allLinks) {
                const href = a.getAttribute("href") || "";
                const text = (a.innerText || "").toLowerCase();
                const hPre = hLow.substring(0, Math.min(4, hLow.length));
                const aPre = aLow.substring(0, Math.min(4, aLow.length));
                if ((href.toLowerCase().includes(hPre) && href.toLowerCase().includes(aPre)) ||
                    (text.includes(hPre) && text.includes(aPre))) {
                    const h = a.getAttribute("href") || "";
                    if (h.includes("betting-") || h.includes("football")) return h;
                }
            }
            return null;
        }""",
        [home, away],
    )

    if match_href:
        if not match_href.startswith("http"):
            match_href = "https://www.betfair.com/exchange/plus/" + match_href.lstrip("/")
        return match_href

    return None


async def _extract_match_data(page) -> dict:
    return await page.evaluate(r"""() => {
        const text = document.body.innerText;
        const lines = text.split('\n');
        const scores = {};
        const overUnder = {};
        const matchOdds = {};

        for (let i = 0; i < lines.length; i++) {
            const t = lines[i].trim();
            const scoreMatch = t.match(/^(\d+)\s*-\s*(\d+)$/);
            if (scoreMatch) {
                const key = scoreMatch[1] + "-" + scoreMatch[2];
                if (scores[key]) continue;
                for (let j = i + 1; j < Math.min(i + 6, lines.length); j++) {
                    const odds = lines[j].trim();
                    const oMatch = odds.match(/^(\d+\.?\d*)$/);
                    if (oMatch) {
                        const v = parseFloat(oMatch[1]);
                        if (v >= 1.01) { scores[key] = v; break; }
                    }
                    const moneyMatch = odds.match(/^£[\d,]+$/);
                    if (moneyMatch) continue;
                    if (odds && !/^£/.test(odds) && !/^\d+\.?\d*$/.test(odds)) break;
                }
            }
        }

        for (let i = 0; i < lines.length; i++) {
            const t = lines[i].trim();
            for (const th of ["0.5", "1.5", "2.5", "3.5", "4.5", "5.5"]) {
                if (t.includes("Over/Under " + th)) {
                    for (let j = i + 1; j < Math.min(i + 15, lines.length); j++) {
                        const lt = lines[j].trim();
                        if (lt.startsWith("Under") && lt.includes(th)) {
                            for (let k = j + 1; k < Math.min(j + 4, lines.length); k++) {
                                const m = lines[k].trim().match(/^(\d+\.?\d*)$/);
                                if (m) { overUnder["under_" + th] = parseFloat(m[1]); break; }
                            }
                        }
                        if (lt.startsWith("Over") && lt.includes(th)) {
                            for (let k = j + 1; k < Math.min(j + 4, lines.length); k++) {
                                const m = lines[k].trim().match(/^(\d+\.?\d*)$/);
                                if (m) { overUnder["over_" + th] = parseFloat(m[1]); break; }
                            }
                        }
                    }
                    break;
                }
            }
        }

        const title = document.title || "";
        const tm = title.match(/(?:Best\s+)?(.+?)\s+v\s+(.+?)\s+(Odds|Betting)/i);
        const home = tm ? tm[1].trim() : "";
        const away = tm ? tm[2].trim() : "";

        return {scores, overUnder, matchOdds, home, away};
    }""")


async def _scrape_betfair_match(
    competition_key: str,
    home_team: str,
    away_team: str,
    match_url: str | None = None,
) -> BetfairCSData:
    proxy = _parse_proxy()
    if not proxy:
        return BetfairCSData(error="WEBSHARE_PROXY_URL non configuré", timestamp=time.time())

    result = BetfairCSData(timestamp=time.time())

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, proxy=proxy)
        except Exception as e:
            return BetfairCSData(error=f"Proxy connection failed: {e}", timestamp=time.time())

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-GB",
            timezone_id="Europe/London",
        )
        page = await context.new_page()

        try:
            target_url = match_url
            if not target_url:
                target_url = await _find_match_url(page, competition_key, home_team, away_team)

            if not target_url:
                comp_slug = _BF_COMP_SLUGS.get(competition_key, "")
                if comp_slug:
                    h_slug = _team_slug(home_team)
                    a_slug = _team_slug(away_team)
                    guess_url = f"https://www.betfair.com/exchange/plus/en/football/{comp_slug}/{h_slug}-v-{a_slug}"
                    try:
                        resp = await page.goto(guess_url, timeout=20000, wait_until="domcontentloaded")
                        if resp and resp.status == 200:
                            await asyncio.sleep(4)
                            cur = page.url
                            if "betting-" in cur:
                                target_url = cur
                    except Exception:
                        pass

            if not target_url:
                result.error = "Match non trouvé sur Betfair Exchange"
                await browser.close()
                return result

            result.match_url = target_url
            resp = await page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
            if not resp or resp.status != 200:
                result.error = f"HTTP {resp.status if resp else 'no response'}"
                await browser.close()
                return result

            await asyncio.sleep(6)

            data = await _extract_match_data(page)

            for score_key, odds_val in data.get("scores", {}).items():
                result.correct_scores[score_key] = odds_val
            for ou_key, ou_val in data.get("overUnder", {}).items():
                result.over_under[ou_key] = ou_val
            for mo_key, mo_val in data.get("matchOdds", {}).items():
                result.match_odds[mo_key] = mo_val

            result.home_team = data.get("home", "") or home_team
            result.away_team = data.get("away", "") or away_team

        except Exception as e:
            result.error = f"Scraping error: {e}"
        finally:
            await browser.close()

    return result


def fetch_betfair_cs(
    competition_key: str,
    home_team: str,
    away_team: str,
    match_url: str | None = None,
) -> BetfairCSData:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(
                asyncio.run,
                _scrape_betfair_match(competition_key, home_team, away_team, match_url),
            ).result(timeout=90)
    else:
        return asyncio.run(
            _scrape_betfair_match(competition_key, home_team, away_team, match_url)
        )


def cs_to_exact_score_odds(
    cs_data: BetfairCSData,
    team_is_home: bool,
) -> dict[tuple[int, int], float]:
    result = {}
    for score_str, odds in cs_data.correct_scores.items():
        parts = score_str.split("-")
        if len(parts) != 2:
            continue
        try:
            h, a = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            continue
        if team_is_home:
            result[(h, a)] = odds
        else:
            result[(a, h)] = odds
    return result


def derive_team_u05_from_cs(
    cs_data: BetfairCSData,
    team_is_home: bool,
) -> float | None:
    zero_scores = []
    for score_str, odds in cs_data.correct_scores.items():
        parts = score_str.split("-")
        if len(parts) != 2:
            continue
        try:
            h, a = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            continue
        team_goals = h if team_is_home else a
        if team_goals == 0:
            zero_scores.append(1.0 / odds)

    if not zero_scores:
        return None
    p_zero = sum(zero_scores)
    if p_zero <= 0 or p_zero >= 1:
        return None
    return round(1.0 / p_zero, 2)


def derive_00_from_cs(cs_data: BetfairCSData) -> float | None:
    odds = cs_data.correct_scores.get("0-0")
    if odds and odds > 1.0:
        return odds
    return None
