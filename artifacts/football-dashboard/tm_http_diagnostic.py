"""Bounded, read-only experiment. Never invokes the export or recovery pipeline."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from urllib.parse import urlparse
from collections import Counter
from pathlib import Path

import tm_player_career as career

LEAGUES = ("a1", "l1", "alb1", "alg1", "arg1", "aus1",
           "az1", "be1", "gb1", "fr1", "bos1", "bra1")
STAGES = (6, 18, 36)
PAUSE = 5
STAGE_PAUSE = 30
MAX_SECONDS = 900
BOOTSTRAP_BUDGET = 40


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def select_sample(root):
    """Three distinct current-season IDs per league, ordered round-robin."""
    selected, seen, sources = {}, set(), {}
    for league in LEAGUES:
        path = root / f"{league}.csv"
        season = career.max_season_in_csv(str(path))
        ids = sorted((p for p in career.load_player_meta_from_league_csv(
            str(path), {season}) if p.isdecimal() and p not in seen), key=int)
        if season <= 0 or len(ids) < 3:
            raise ValueError("Insufficient sample")
        picks = [ids[0], ids[len(ids) // 2], ids[-1]]
        selected[league] = picks
        seen.update(picks)
        sources[league] = {"season": season, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return [(league, selected[league][i]) for i in range(3) for league in LEAGUES], sources


def bootstrap():
    """One homepage session, no interaction/CAPTCHA solving, no refresh.

    Count ALL browser requests (assets included); stop at 40. No cookie, URL,
    response body or exception text is emitted.
    """
    from playwright.sync_api import sync_playwright
    stats = {"requests": 0, "skipped_resources": 0, "http": {}, "stop": None}
    started = time.monotonic()
    token = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=career.tm_waf.WAF_USER_AGENT, service_workers="block")

                def route_request(route):
                    host = (urlparse(route.request.url).hostname or "").lower()
                    allowed = any(host == domain or host.endswith("." + domain)
                                  for domain in ("transfermarkt.com", "awswaf.com"))
                    if not allowed or route.request.resource_type in (
                            "image", "stylesheet", "font", "media"):
                        stats["skipped_resources"] += 1
                        route.abort()
                        return
                    if stats["stop"] or stats["requests"] >= BOOTSTRAP_BUDGET:
                        stats["stop"] = stats["stop"] or "bootstrap_budget"
                        route.abort()
                    else:
                        stats["requests"] += 1
                        route.continue_()

                def response_received(response):
                    status = str(response.status)
                    stats["http"][status] = stats["http"].get(status, 0) + 1
                    action = response.headers.get("x-amzn-waf-action", "").lower()
                    if action == "captcha" or response.status in (403, 405, 429):
                        stats["stop"] = "captcha" if action == "captcha" else f"http_{status}"

                context.route("**/*", route_request)
                context.on("response", response_received)
                page = context.new_page()
                page.goto(career.BASE_URL + "/", wait_until="domcontentloaded", timeout=45000)
                # Let the ordinary JS session initialize, but never click a challenge.
                for _ in range(12):
                    if stats["stop"]:
                        break
                    page.wait_for_timeout(500)
                if not stats["stop"]:
                    token = next((c["value"] for c in context.cookies()
                                  if c["name"] == "aws-waf-token"), None)
                    if not token:
                        stats["stop"] = "session_unavailable"
            finally:
                browser.close()
    except Exception:
        stats["stop"] = stats["stop"] or "bootstrap_error"
    stats["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return token, stats


def classify(payload, status, error, challenge):
    if "captcha" in (error or "").lower():
        return "captcha"
    if challenge:
        return "waf_challenge"
    if status != 200:
        return f"http_{status}" if isinstance(status, int) else "transport_error"
    if not (isinstance(payload, dict) and payload.get("success") is True
            and isinstance(payload.get("data"), dict)
            and isinstance(payload["data"].get("performance"), list)):
        return "invalid_payload"
    return "success"


def probe(sample, token, *, fetch=None, sleep=time.sleep, clock=time.monotonic):
    if len(sample) != STAGES[-1] or len({pid for _, pid in sample}) != len(sample):
        raise ValueError("Expected exactly 36 distinct players")
    career._blocked.clear()
    opener = urllib.request.build_opener(NoRedirect())
    if fetch is None:
        def fetch(url):
            return career._fetch_json_once(
                url, token_provider=lambda: token, open_request=opener.open)
    started = clock()
    rows, completed = [], []
    stop = "completed"
    for index, (league, pid) in enumerate(sample, 1):
        if index > 1:
            sleep(STAGE_PAUSE if index - 1 in STAGES else PAUSE)
        if clock() - started >= MAX_SECONDS:
            stop = "time_budget"
            break
        before = clock()
        try:
            payload, status, error, challenge, _ = fetch(
                career.BASE_URL + career.CEAPI_PATH.format(pid=pid))
            kind = classify(payload, status, error, challenge)
        except Exception:
            status, kind = None, "transport_error"
        row = {"request": index, "league": league, "player_id": pid,
               "status": status, "classification": kind,
               "elapsed_seconds": round(clock() - before, 3)}
        rows.append(row)
        print(json.dumps(row), flush=True)
        if kind != "success":
            career._blocked.set()
            stop = kind
            break
        if index in STAGES:
            completed.append(index)
    durations = [r["elapsed_seconds"] for r in rows]
    return {"requests": rows, "attempted": len(rows),
            "successes": sum(r["classification"] == "success" for r in rows),
            "classifications": dict(Counter(r["classification"] for r in rows)),
            "completed_stages": completed, "stop_reason": stop,
            "circuit_open": career._blocked.is_set(),
            "circuit_triggers": int(career._blocked.is_set()),
            "elapsed_seconds": round(clock() - started, 3),
            "request_seconds_mean": round(sum(durations) / len(durations), 3) if durations else None,
            "request_seconds_max": max(durations) if durations else None}


def main():
    # Output is fixed beneath runner temp, never a caller-selected production path.
    out = Path(os.environ["RUNNER_TEMP"]) / "tm-http-diagnostic.json"
    report = {"schema_version": 1, "github_run_id": os.environ.get("GITHUB_RUN_ID"),
              "commit": os.environ.get("GITHUB_SHA"),
              "limits": {"ceapi_requests": 36, "bootstrap_requests": 40,
                         "pause_seconds": PAUSE, "stage_pause_seconds": STAGE_PAUSE,
                         "stages": STAGES, "ceapi_seconds": MAX_SECONDS},
              "scope": "Small sequential sample, not evidence for eleven full leagues or a full collection."}
    try:
        sample, sources = select_sample(Path(__file__).parent / "live/data/tm_scrap")
        report.update(sample=sample, sources=sources)
        token, startup = bootstrap()
        report["bootstrap"] = startup
        if startup["stop"]:
            report.update(stop_reason=startup["stop"], attempted=0, successes=0,
                          circuit_open=True, circuit_triggers=1, completed_stages=[])
        else:
            report.update(probe(sample, token))
    except (ValueError, FileNotFoundError):
        report.update(stop_reason="invalid_sample", completed_stages=[])
    except Exception:
        # Deliberately omit exception strings (URLs, headers or bodies may occur).
        report.update(stop_reason="setup_error", completed_stages=[])
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("sample", "sources", "requests")}))
    return 0 if report["stop_reason"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
