from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import async_playwright

_bf_logger = logging.getLogger(__name__)

def _ensure_playwright_browsers() -> None:
    cache_dir = Path.home() / ".cache" / "ms-playwright"
    if any(cache_dir.glob("chromium*/chrome-linux/chrome")) or any(cache_dir.glob("chromium_headless_shell*/chrome-headless-shell-linux64/chrome-headless-shell")):
        return
    _bf_logger.info("Playwright Chromium not found, installing...")
    try:
        subprocess.run(
            ["python", "-m", "playwright", "install", "chromium"],
            check=True, capture_output=True, text=True, timeout=120,
        )
        _bf_logger.info("Playwright Chromium installed successfully")
    except Exception as e:
        _bf_logger.warning("Failed to install Playwright Chromium: %s", e)


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
class BetfairSelection:
    name: str = ""
    back: float = 0.0
    back_vol: float = 0.0
    lay: float = 0.0
    lay_vol: float = 0.0

    @property
    def mid_price(self) -> float:
        if self.back <= 0 and self.lay <= 0:
            return 0.0
        if self.back <= 0:
            return self.lay
        if self.lay <= 0:
            return self.back
        total = self.back_vol + self.lay_vol
        if total <= 0:
            return (self.back + self.lay) / 2
        w_back = self.back_vol / total
        return self.back * w_back + self.lay * (1 - w_back)


@dataclass
class BetfairCSData:
    home_team: str = ""
    away_team: str = ""
    correct_scores: dict[str, float] = field(default_factory=dict)
    cs_detail: dict[str, BetfairSelection] = field(default_factory=dict)
    match_odds_1x2: dict[str, float] = field(default_factory=dict)
    match_odds_1x2_detail: dict[str, "BetfairSelection"] = field(default_factory=dict)
    btts: dict[str, BetfairSelection] = field(default_factory=dict)
    ou25: dict[str, BetfairSelection] = field(default_factory=dict)
    ou05: dict[str, BetfairSelection] = field(default_factory=dict)
    ou05_home: dict[str, BetfairSelection] = field(default_factory=dict)
    ou05_away: dict[str, BetfairSelection] = field(default_factory=dict)
    over_under: dict[str, float] = field(default_factory=dict)
    timestamp: float = 0.0
    match_url: str = ""
    error: str = ""


def _parse_proxy():
    url = os.environ.get("BETFAIR_PROXY_URL", "") or os.environ.get("WEBSHARE_PROXY_URL", "")
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


_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_BLOCKED_URL_PATTERNS = ["google-analytics", "googletagmanager", "facebook", "doubleclick", "hotjar", "sentry"]

async def _block_unnecessary(route):
    req = route.request
    if req.resource_type in _BLOCKED_RESOURCE_TYPES:
        await route.abort()
    elif any(p in req.url for p in _BLOCKED_URL_PATTERNS):
        await route.abort()
    else:
        await route.continue_()


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
        await page.goto(comp_url, timeout=60000, wait_until="domcontentloaded")
    except Exception:
        return None
    await asyncio.sleep(3)

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


_EXTRACT_JS = r"""() => {
    const text = document.body.innerText;
    const rawLines = text.split('\n');
    const L = [];
    for (const l of rawLines) { const t = l.trim(); if (t) L.push(t); }

    const R = { mo: [], btts: [], ou25: [], ou05: [], ou05h: [], ou05a: [], cs: [], home: '', away: '' };

    const title = document.title || '';
    const tm = title.match(/(?:Best\s+)?(.+?)\s+v\s+(.+?)\s+(Odds|Betting)/i);
    R.home = tm ? tm[1].trim() : '';
    R.away = tm ? tm[2].trim() : '';

    function ep(si, mx) {
        const ps = [];
        let i = si;
        while (i < L.length && ps.length < mx) {
            const m = L[i].match(/^(\d+\.?\d*)$/);
            if (m) {
                const p = parseFloat(m[1]);
                if (p >= 1.01) {
                    let v = 0;
                    if (i + 1 < L.length) {
                        const vm = L[i + 1].match(/^£([\d,]+)$/);
                        if (vm) { v = parseFloat(vm[1].replace(/,/g, '')); i += 2; }
                        else { i++; }
                    } else { i++; }
                    ps.push({ p, v });
                    continue;
                }
            }
            if (L[i].match(/^£/) || (m && parseFloat(m[1]) < 1.01)) { i++; continue; }
            break;
        }
        return { ps, ni: i };
    }

    // 1X2 Match Odds
    const bai = L.indexOf('Back all');
    if (bai >= 0) {
        let i = bai + 1;
        while (i < L.length && i < bai + 6) {
            if (L[i] === 'Lay all' || L[i].match(/^\d+\.?\d*%$/) || L[i].includes('selections')) { i++; }
            else break;
        }
        for (let s = 0; s < 3 && i < L.length; s++) {
            const nm = L[i];
            if (nm && !nm.match(/^\d/) && !nm.match(/^£/) && nm !== 'Other Markets') {
                i++;
                const { ps, ni } = ep(i, 6);
                if (ps.length >= 6) {
                    R.mo.push({ n: nm, bb: ps[2].p, bbv: ps[2].v, bl: ps[3].p, blv: ps[3].v });
                } else if (ps.length >= 4) {
                    const mid = Math.floor(ps.length / 2);
                    R.mo.push({ n: nm, bb: ps[mid - 1].p, bbv: ps[mid - 1].v, bl: ps[mid].p, blv: ps[mid].v });
                } else if (ps.length >= 2) {
                    R.mo.push({ n: nm, bb: ps[0].p, bbv: ps[0].v, bl: ps[1].p, blv: ps[1].v });
                }
                i = ni;
            } else { i++; }
        }
    }

    // Generic 2-selection market parser
    function p2m(hdr) {
        const res = [];
        let si = -1;
        for (let i = 0; i < L.length; i++) {
            if (L[i] === hdr || L[i] === hdr + '?') {
                for (let j = i + 1; j < Math.min(i + 5, L.length); j++) {
                    if (L[j] === 'Rules' || L[j].startsWith('Matched:')) { si = i; break; }
                }
                if (si >= 0) break;
            }
        }
        if (si < 0) return res;
        let i = si;
        while (i < L.length && i < si + 10) {
            if (L[i] === 'Lay' || L[i] === 'Lay all') { i++; break; }
            i++;
        }
        for (let s = 0; s < 4 && i < L.length; s++) {
            const nm = L[i];
            if (nm === 'View full market' || nm === 'Rules' || nm.startsWith('Matched:')) break;
            if (nm && !nm.match(/^\d/) && !nm.match(/^£/)) {
                i++;
                const { ps, ni } = ep(i, 2);
                if (ps.length >= 2) {
                    res.push({ n: nm, b: ps[0].p, bv: ps[0].v, l: ps[1].p, lv: ps[1].v });
                } else if (ps.length === 1) {
                    res.push({ n: nm, b: ps[0].p, bv: ps[0].v, l: 0, lv: 0 });
                }
                i = ni;
            } else { i++; }
        }
        return res;
    }

    R.btts = p2m('Both teams to Score?');
    if (R.btts.length === 0) R.btts = p2m('Both teams to Score');
    R.ou25 = p2m('Over/Under 2.5 Goals');
    R.ou05 = p2m('Over/Under 0.5 Goals');

    // Team-specific O/U 0.5
    for (let i = 0; i < L.length; i++) {
        const line = L[i];
        const m05 = line.match(/Over\s*\/\s*Under\s+0\.5\s+(.+?)\s+Goals?/i);
        if (!m05) continue;
        const teamInHeader = m05[1].trim();
        let isMarket = false;
        for (let j = i + 1; j < Math.min(i + 5, L.length); j++) {
            if (L[j] === 'Rules' || L[j].startsWith('Matched:')) { isMarket = true; break; }
        }
        if (!isMarket) continue;
        const mkt = p2m(line);
        if (mkt.length === 0) continue;
        const hNorm = R.home.toLowerCase().replace(/[^a-z]/g, '');
        const aNorm = R.away.toLowerCase().replace(/[^a-z]/g, '');
        const tNorm = teamInHeader.toLowerCase().replace(/[^a-z]/g, '');
        if (hNorm && (tNorm.includes(hNorm.slice(0,4)) || hNorm.includes(tNorm.slice(0,4)))) {
            R.ou05h = mkt;
        } else if (aNorm && (tNorm.includes(aNorm.slice(0,4)) || aNorm.includes(tNorm.slice(0,4)))) {
            R.ou05a = mkt;
        }
    }

    // Correct Score
    let csStart = -1;
    for (let i = 0; i < L.length; i++) {
        if (L[i] === 'Correct Score') {
            for (let j = i + 1; j < Math.min(i + 5, L.length); j++) {
                if (L[j] === 'Rules' || L[j].startsWith('Matched:')) { csStart = i; break; }
            }
            if (csStart >= 0) break;
        }
    }
    if (csStart >= 0) {
        let i = csStart;
        while (i < L.length && i < csStart + 10) {
            if (L[i] === 'Lay') { i++; break; }
            i++;
        }
        while (i < L.length) {
            const nm = L[i];
            if (nm === 'View full market' || nm === 'Rules' || nm.startsWith('Matched:') ||
                nm.startsWith('First Half') || nm.startsWith('Half Time')) break;
            const sm = nm.match(/^(\d+)\s*-\s*(\d+)$/);
            if (sm) {
                const key = sm[1] + '-' + sm[2];
                i++;
                const { ps, ni } = ep(i, 2);
                if (ps.length >= 2) {
                    R.cs.push({ n: key, b: ps[0].p, bv: ps[0].v, l: ps[1].p, lv: ps[1].v });
                } else if (ps.length === 1) {
                    R.cs.push({ n: key, b: ps[0].p, bv: ps[0].v, l: 0, lv: 0 });
                }
                i = ni;
            } else if (nm.startsWith('Any Other')) {
                i++;
                const { ps, ni } = ep(i, 2);
                i = ni;
            } else {
                i++;
            }
        }
    }

    return R;
}"""


async def _extract_match_data(page) -> dict:
    return await page.evaluate(_EXTRACT_JS)


async def _scrape_betfair_match(
    competition_key: str,
    home_team: str,
    away_team: str,
    match_url: str | None = None,
) -> BetfairCSData:
    proxy = _parse_proxy()
    if not proxy:
        return BetfairCSData(error="BETFAIR_PROXY_URL non configuré", timestamp=time.time())

    _ensure_playwright_browsers()

    result = BetfairCSData(timestamp=time.time())

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=True,
                proxy=proxy,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage", "--disable-extensions"],
            )
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
        await page.route("**/*", _block_unnecessary)

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
                        resp = await page.goto(guess_url, timeout=60000, wait_until="domcontentloaded")
                        if resp and resp.status == 200:
                            await asyncio.sleep(2)
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
            resp = await page.goto(target_url, timeout=60000, wait_until="domcontentloaded")
            if not resp or resp.status != 200:
                result.error = f"HTTP {resp.status if resp else 'no response'}"
                await browser.close()
                return result

            await asyncio.sleep(4)

            data = await _extract_match_data(page)

            result.home_team = data.get("home", "") or home_team
            result.away_team = data.get("away", "") or away_team

            for item in data.get("mo", []):
                result.match_odds_1x2[item["n"]] = item["bl"]
                result.match_odds_1x2_detail[item["n"]] = BetfairSelection(
                    name=item["n"],
                    back=item.get("bb", 0.0),
                    back_vol=item.get("bbv", 0.0),
                    lay=item.get("bl", 0.0),
                    lay_vol=item.get("blv", 0.0),
                )

            for item in data.get("btts", []):
                sel = BetfairSelection(
                    name=item["n"],
                    back=item["b"], back_vol=item["bv"],
                    lay=item["l"], lay_vol=item["lv"],
                )
                result.btts[item["n"]] = sel

            for item in data.get("ou25", []):
                sel = BetfairSelection(
                    name=item["n"],
                    back=item["b"], back_vol=item["bv"],
                    lay=item["l"], lay_vol=item["lv"],
                )
                result.ou25[item["n"]] = sel

            for item in data.get("ou05", []):
                sel = BetfairSelection(
                    name=item["n"],
                    back=item["b"], back_vol=item["bv"],
                    lay=item["l"], lay_vol=item["lv"],
                )
                result.ou05[item["n"]] = sel

            for item in data.get("ou05h", []):
                sel = BetfairSelection(
                    name=item["n"],
                    back=item["b"], back_vol=item["bv"],
                    lay=item["l"], lay_vol=item["lv"],
                )
                result.ou05_home[item["n"]] = sel

            for item in data.get("ou05a", []):
                sel = BetfairSelection(
                    name=item["n"],
                    back=item["b"], back_vol=item["bv"],
                    lay=item["l"], lay_vol=item["lv"],
                )
                result.ou05_away[item["n"]] = sel

            for item in data.get("cs", []):
                sel = BetfairSelection(
                    name=item["n"],
                    back=item["b"], back_vol=item["bv"],
                    lay=item["l"], lay_vol=item["lv"],
                )
                result.cs_detail[item["n"]] = sel
                result.correct_scores[item["n"]] = sel.mid_price

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


def cs_to_exact_score_mids(
    cs_data: BetfairCSData,
    team_is_home: bool,
) -> dict[tuple[int, int], float]:
    result = {}
    for score_str, sel in cs_data.cs_detail.items():
        parts = score_str.split("-")
        if len(parts) != 2:
            continue
        try:
            h, a = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            continue
        mid = sel.mid_price
        if mid <= 1.0:
            continue
        if team_is_home:
            result[(h, a)] = mid
        else:
            result[(a, h)] = mid
    return result


def cs_to_exact_score_odds(
    cs_data: BetfairCSData,
    team_is_home: bool,
) -> dict[tuple[int, int], float]:
    result = {}
    source = cs_data.cs_detail if cs_data.cs_detail else {}
    if not source and cs_data.correct_scores:
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

    for score_str, sel in source.items():
        parts = score_str.split("-")
        if len(parts) != 2:
            continue
        try:
            h, a = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            continue
        mid = sel.mid_price
        if mid <= 1.0:
            continue
        if team_is_home:
            result[(h, a)] = mid
        else:
            result[(a, h)] = mid
    return result


def get_btts_yes_mid(cs_data: BetfairCSData) -> float | None:
    for key in ("Yes", "yes", "YES"):
        if key in cs_data.btts:
            mid = cs_data.btts[key].mid_price
            if mid > 1.0:
                return round(mid, 3)
    return None


def get_ou25_under_mid(cs_data: BetfairCSData) -> float | None:
    for key, sel in cs_data.ou25.items():
        if "under" in key.lower():
            mid = sel.mid_price
            if mid > 1.0:
                return round(mid, 3)
    return None


def get_ou05_under_mid(cs_data: BetfairCSData) -> float | None:
    for key, sel in cs_data.ou05.items():
        if "under" in key.lower():
            mid = sel.mid_price
            if mid > 1.0:
                return round(mid, 3)
    return None


def get_ou05_team_under_mid(cs_data: BetfairCSData, team_is_home: bool) -> float | None:
    mkt = cs_data.ou05_home if team_is_home else cs_data.ou05_away
    for key, sel in mkt.items():
        if "under" in key.lower():
            mid = sel.mid_price
            if mid > 1.0:
                return round(mid, 3)
    return None


def get_1x2_lay_team(cs_data: BetfairCSData, team_name: str) -> float | None:
    for name, lay_price in cs_data.match_odds_1x2.items():
        if team_name.lower()[:4] in name.lower() or name.lower()[:4] in team_name.lower():
            if lay_price > 1.0:
                return round(lay_price, 2)
    return None


def derive_team_u05_from_cs(
    cs_data: BetfairCSData,
    team_is_home: bool,
) -> float | None:
    zero_scores = []
    source = cs_data.cs_detail if cs_data.cs_detail else {}
    if source:
        for score_str, sel in source.items():
            parts = score_str.split("-")
            if len(parts) != 2:
                continue
            try:
                h, a = int(parts[0].strip()), int(parts[1].strip())
            except ValueError:
                continue
            team_goals = h if team_is_home else a
            mid = sel.mid_price
            if team_goals == 0 and mid > 1.0:
                zero_scores.append(1.0 / mid)
    else:
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
    if "0-0" in cs_data.cs_detail:
        mid = cs_data.cs_detail["0-0"].mid_price
        if mid > 1.0:
            return round(mid, 2)
    odds = cs_data.correct_scores.get("0-0")
    if odds and odds > 1.0:
        return odds
    return None
