"""Weekly collection in ONE source flow; only the coordinator writes the queue.

Leagues run one after another (squads, then careers) under a single pace and a
single WAF token shared by the run's subprocesses. A source refusal stops ALL
traffic and holds the whole campaign (2 h, then 6 h, then 24 h) before ONE
probe; a refusal after the third hold suspends the campaign for the operator.
Never switch league to dodge a refusal, never open another session after one.

Responses already validated THIS WEEK for another league are reused with their
original collection dates instead of being requested again (cross-league
deduplication). Each league keeps its own checkpoint campaign, as before.

Rate ladder (one session, one flow, always): 0.8, 1.0, 1.2, 1.5, 2.0 req/s.
One level up after six clean collection hours at the current level; a refusal
means one level down, and that lower level becomes the cap for two weeks. The
ladder survives from one weekly campaign to the next. Absolute ceiling 2.0.
"""
import copy
import csv
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from tm_career_checkpoints import Checkpoints, valid_record
from collection_metadata import read_metadata, fingerprints

WIDTH = 1                                  # one source flow, never five
HOLDS = (2 * 3600, 6 * 3600, 24 * 3600)    # campaign-wide pauses after refusals
TEMPORARY_RETRY = 600                      # 5xx/timeouts: same run, 10 min later
STORAGE_RETRY = 300                        # checkpoint storage outage (exit 78): 5 min later
MAX_STORAGE_FAILURES = 2                   # the third failure of one league is the operator's
DEFAULT_HOURS = 3.0
MAX_HOURS = 4.5                            # job timeout is 350 min
SEED_PATTERN = "seed-*.ndjson.gz"          # never *.jsonl.gz: invisible to Checkpoints
# Published as soon as they are all collected (the run ends early once per
# campaign so the workflow publishes them; the next run continues the queue).
PRIORITY = ("l1", "es1", "gb1", "it1", "fr1")

RATES = (0.8, 1.0, 1.2, 1.5, 2.0)          # requests/s for the whole run (one flow)
RATE_CEILING = 2.0                         # absolute, whatever the settings say
PROMOTE_AFTER = 6 * 3600                   # clean collection seconds before a level up
DEMOTION_CAP = 14 * 24 * 3600              # first refusal at a rate: 2 weeks of cap
MAX_CAP_FACTOR = 4                         # repeated refusals at that rate: 4, then 8 weeks


def rate_ceiling():
    """Operator setting TM_RATE_CEILING may only LOWER the absolute ceiling."""
    try:
        value = float(os.environ.get("TM_RATE_CEILING", RATE_CEILING))
    except ValueError:
        return RATE_CEILING
    return min(RATE_CEILING, value) if value > 0 else RATE_CEILING


def max_level(pace, now):
    ceiling = rate_ceiling()
    allowed = max([i for i, rate in enumerate(RATES) if rate <= ceiling + 1e-9] or [0])
    if pace.get("cap_until", 0) > now:
        allowed = min(allowed, pace.get("cap", allowed))
    return allowed


def new_pace(now):
    return {"level": 0, "clean_seconds": 0.0, "cap": len(RATES) - 1, "cap_until": 0,
            "updated_at": now, "history": []}


def current_level(pace, now):
    """Effective level: a lowered setting or an active cap applies immediately."""
    return max(0, min(pace.get("level", 0), max_level(pace, now)))


def pause_bounds(rate):
    """Shared pause around 1/rate (±20 %), same shape as the historical 1.0-1.5 s."""
    mean = 1.0 / rate
    return round(0.8 * mean, 3), round(1.2 * mean, 3)


def pace_event(pace, now, event, **extra):
    pace["updated_at"] = now
    rate = RATES[pace["level"]]
    pace["history"] = (pace.get("history", []) + [
        {"at": round(now), "event": event, "rate": rate, **extra}])[-20:]
    print("TM_PACE " + json.dumps({"event": event, "rate": rate, **extra}), flush=True)


def account_clean(pace, now, seconds):
    pace["clean_seconds"] = pace.get("clean_seconds", 0.0) + max(0.0, seconds)
    pace["updated_at"] = now
    level = current_level(pace, now)
    if pace["clean_seconds"] >= PROMOTE_AFTER and level < max_level(pace, now):
        # Six clean hours at this rate: earlier refusals at it are forgiven.
        pace.get("refusals_by_rate", {}).pop(str(RATES[level]), None)
        pace["level"] = level + 1
        pace["clean_seconds"] = 0.0
        pace_event(pace, now, "promote")


def account_refusal(pace, now):
    """One level down; the cap lasts 2 weeks, 4 weeks if this rate was already
    refused, then 8 weeks: re-tests of a rate the source keeps refusing get rarer."""
    refused = current_level(pace, now)
    counts = pace.setdefault("refusals_by_rate", {})
    key = str(RATES[refused])
    counts[key] = counts.get(key, 0) + 1
    factor = min(MAX_CAP_FACTOR, 2 ** (counts[key] - 1))
    pace["level"] = max(0, refused - 1)
    pace["cap"] = pace["level"]
    pace["cap_until"] = now + DEMOTION_CAP * factor
    pace["clean_seconds"] = 0.0
    pace_event(pace, now, "demote", refused_rate=RATES[refused],
               cap_weeks=2 * factor, cap_until=round(pace["cap_until"]))


def latest_pace(queues):
    """Carry the ladder from the most recently updated campaign to a new one."""
    paces = [s["pace"] for _, s in queues if isinstance(s.get("pace"), dict)]
    return copy.deepcopy(max(paces, key=lambda p: p.get("updated_at", 0))) if paces else None


def checkpoint_campaign(state, code):
    return state["leagues"][code].get("checkpoint_campaign", state["campaign"])


def collection_hours():
    try:
        hours = float(os.environ.get("TM_COLLECTION_HOURS", DEFAULT_HOURS))
    except ValueError:
        return DEFAULT_HOURS
    return hours if 0 < hours <= MAX_HOURS else DEFAULT_HOURS


def squad_seasons(squad, year):
    """Skip the previous season only once the new one has league appearances.

    Autumn-spring leagues: the closed season never changes again. Calendar-year
    leagues keep both (their live season is labelled year-1 by Transfermarkt).
    """
    seasons = [year - 1, year]
    try:
        with open(squad, newline="", encoding="utf-8") as stream:
            present, apps = set(), 0
            for row in csv.DictReader(stream):
                season = int(row.get("season") or 0)
                present.add(season)
                if season == year:
                    apps += int(row.get("appearances") or 0)
    except (OSError, ValueError):
        return seasons
    return [year] if apps > 0 and year - 1 in present else seasons


def league_ids(squad):
    """Exactly the player set tm_player_career collects (AUTO season filter)."""
    from tm_player_career import max_season_in_csv, load_player_meta_from_league_csv
    season = max_season_in_csv(str(squad))
    return set(load_player_meta_from_league_csv(
        str(squad), {season, season - 1} if season > 0 else None))


def seed_checkpoints(source, destination, campaign, ids=None):
    """Copy acquired responses, retaining collection dates, without source traffic."""
    destination.mkdir(parents=True, exist_ok=True)
    for record in source._all_records():
        if record and (ids is None or record["player_id"] in ids):
            target = destination / (record["player_id"] + ".json")
            if not target.exists():
                target.write_text(json.dumps({**record, "campaign": campaign}))


class SeedPool:
    """This week's validated responses, gzip on local disk, newest date wins."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def _path(self, pid):
        return self.folder / f"{pid}.json.gz"

    def get(self, pid):
        try:
            with gzip.open(self._path(pid), "rt", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            return None

    def add(self, record):
        current = self.get(record["player_id"])
        if current and (datetime.fromisoformat(current["collected_at"])
                        >= datetime.fromisoformat(record["collected_at"])):
            return False
        path = self._path(record["player_id"])
        temporary = path.with_suffix(".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(temporary, path)
        return True

    def seed(self, destination, campaign, ids):
        """Copy pooled responses into one league campaign; never overwrite."""
        destination.mkdir(parents=True, exist_ok=True)
        copied = 0
        for pid in sorted(ids):
            record = self.get(pid)
            target = destination / f"{pid}.json"
            if record and not target.exists():
                target.write_text(json.dumps({**record, "campaign": campaign}))
                copied += 1
        return copied


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=900)


def family(state, campaign):
    return campaign == state["campaign"] or campaign.startswith(state["campaign"] + "-")


def load_seed_assets(state, pool, needed, gh=gh):
    """Durable deduplication across runs; a failure only costs requests.

    Returns (records added to the pool, league codes whose asset was read).
    """
    with tempfile.TemporaryDirectory() as tmp:
        proc = gh("release", "download", f"tm-checkpoints-{state['campaign']}",
                  "--dir", tmp, "--pattern", SEED_PATTERN)
        if proc.returncode:
            return 0, set()
        added, codes = 0, set()
        for path in sorted(Path(tmp).glob("seed-*.ndjson.gz")):
            codes.add(path.name[len("seed-"):-len(".ndjson.gz")])
            try:
                with gzip.open(path, "rt", encoding="utf-8") as stream:
                    for line in stream:
                        record = json.loads(line)
                        campaign = record.get("campaign", "")
                        if (record.get("player_id") in needed and family(state, campaign)
                                and valid_record(record, campaign)):
                            added += pool.add(record)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                codes.discard(path.name[len("seed-"):-len(".ndjson.gz")])
                print(f"TM_SEED_ASSET_IGNORED {path.name}", flush=True)
        return added, codes


def publish_seed_asset(state, code, records, gh=gh):
    """One small asset per collected league: only players shared with others."""
    if not records:
        return True
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"seed-{code}.ndjson.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
        proc = gh("release", "upload", f"tm-checkpoints-{state['campaign']}",
                  str(path), "--clobber")
        return proc.returncode == 0


def refusal(state, item, now):
    from tm_collection_queue import suspend
    state["refusals"] = state.get("refusals", 0) + 1
    if state["refusals"] > len(HOLDS):
        item.update(state="suspended", reason="access_blocked")
        suspend(state, "access_blocked")
        return
    state["hold_until"] = now + HOLDS[state["refusals"] - 1]
    item.update(state="retry", due=state["hold_until"], reason="access_blocked")


def collect(store, release_id, state, root, leagues, clock=time.time,
            sleep=time.sleep, run=subprocess.run, hours=None, gh=gh):
    from tm_collection_queue import suspend
    full = root / "live/data/tm_career"
    if state.get("hold_until", 0) > clock():
        print(f"TM_HOLD campaign held until {state['hold_until']:.0f}; no source traffic",
              flush=True)
        return
    stop_at = clock() + (collection_hours() if hours is None else hours) * 3600
    state["parallel"] = True       # attempts are not capped at four (queue semantics)
    store.save(release_id, state)
    remote = os.environ.get("TM_CHECKPOINT_REMOTE") == "github"
    token_file = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / (
        f"tm-waf-{state['campaign']}.token")
    env = {**os.environ, "TM_COLLECTION_DEADLINE": str(stop_at),
           "TM_WAF_TOKEN_FILE": str(token_file)}
    pace = state.setdefault("pace", new_pace(clock()))

    def env_at(rate):
        low, high = pause_bounds(rate)
        return {**env, "TM_PAUSE_MIN": f"{low:.3f}", "TM_PAUSE_MAX": f"{high:.3f}"}

    squads = {code: root / f"live/data/tm_scrap/{code}.csv" for code in state["leagues"]}
    ids_cache = {}

    def ids_of(code):
        if code not in ids_cache:
            ids_cache[code] = league_ids(squads[code]) if squads[code].exists() else set()
        return ids_cache[code]

    def open_items():
        return [c for c, i in state["leagues"].items() if i["state"] in {"pending", "retry"}]

    needed = set().union(set(), *(ids_of(c) for c in open_items()))
    pool = SeedPool(root / "live/data/tm_seed_pool" / state["campaign"])

    def share(code):
        """After success: pool + durable seed asset for players of open leagues.

        Best effort by design: a failure here costs requests later, never data,
        and must never turn a validated league into a campaign failure.
        """
        try:
            others = set().union(set(), *(ids_of(c) for c in open_items() if c != code))
            shared = ids_of(code) & others
            if not shared:
                return
            item = state["leagues"][code]
            store_ = Checkpoints(root / "live/data/tm_parallel_checkpoints" / code,
                                 item["checkpoint_campaign"], remote)
            records = [r for r in (store_.get(pid) for pid in sorted(shared)) if r]
            for record in records:
                pool.add(record)
            uploaded = publish_seed_asset(state, code, records, gh) if remote else False
            print("TM_PHASE " + json.dumps({"phase": "share", "league": code,
                                            "shared": len(records), "uploaded": uploaded}),
                  flush=True)
        except Exception as exc:  # noqa: BLE001 - deduplication is optional
            print(f"TM_SHARE_SKIPPED {code}: {type(exc).__name__}", flush=True)

    # Responses acquired before the per-league campaigns (legacy parent): on demand.
    legacy = Checkpoints(root / "live/data/tm_checkpoints", state["campaign"], remote)
    seeded_from_legacy = 0
    for pid in sorted(needed):
        record = legacy.get(pid) if pid.isdigit() else None
        if record:
            seeded_from_legacy += pool.add(record)
    from_assets, with_asset = load_seed_assets(state, pool, needed, gh) if remote else (0, set())
    # Safety net: a league collected without a readable seed asset (upload
    # failure, or collected before this mechanism) is shared from its own
    # checkpoint campaign, so its players are still not requested twice.
    for code, item in state["leagues"].items():
        if (item["state"] in {"collected", "publishing", "done"} and code not in with_asset
                and item.get("checkpoint_campaign", state["campaign"]) != state["campaign"]):
            share(code)
    print("TM_PHASE " + json.dumps({"phase": "seed_pool", "needed": len(needed),
                                    "legacy": seeded_from_legacy, "assets": from_assets,
                                    "leagues_with_asset": len(with_asset)}),
          flush=True)

    def worker(code, env):
        item = state["leagues"][code]
        squad = squads[code]
        if not item["squad_done"] or not squad.exists():
            league = leagues[code]
            seasons = squad_seasons(squad, time.gmtime().tm_year)
            p = run([sys.executable, "tm_league_scraper.py", "--comp", league["code_tm"],
                     "--slug", league["slug"], "--workers", "2", "--seasons",
                     ",".join(map(str, seasons)), "--merge", "--out", str(squad)],
                    cwd=root, timeout=3600, check=False, env=env)
            if p.returncode:
                return p.returncode, False
            ids_cache.pop(code, None)
        campaign = item["checkpoint_campaign"]
        folder = root / "live/data/tm_parallel_checkpoints" / code
        ids = ids_of(code)
        if not ids:
            raise ValueError("Empty squad")
        copied = pool.seed(folder / campaign, campaign, ids)
        print("TM_PHASE " + json.dumps({"phase": "dedupe", "league": code,
                                        "players": len(ids), "reused_from_week": copied}),
              flush=True)
        p = run([sys.executable, "-u", "tm_player_career.py", "--league", code,
                 "--workers", "2", "--budget-seconds", "0",
                 "--campaign", campaign, "--checkpoint-dir", str(folder),
                 "--checkpoint-remote"], cwd=root, check=False, env=env)
        return p.returncode, True

    try:
        while state["status"] == "active" and clock() < stop_at:
            now = clock()
            if state.get("hold_until", 0) > now:
                break
            due = [c for c in open_items() if state["leagues"][c]["due"] <= now]
            if not due:
                break
            code = due[0]                  # league order = priority order
            item = state["leagues"][code]
            item.update(state="running", attempts=item["attempts"] + 1,
                        started=now, run_id=state["owner"])
            item.setdefault("checkpoint_campaign", state["campaign"] + "-" + code)
            rate = RATES[current_level(pace, now)]
            item["rate"] = rate
            print("TM_PACE " + json.dumps({"event": "use", "league": code, "rate": rate,
                                           "clean_hours": round(pace.get("clean_seconds", 0) / 3600, 2)}),
                  flush=True)
            store.save(release_id, state)  # sole writer, before source traffic
            try:
                rc, squad_done = worker(code, env_at(rate))
                if rc == 75:
                    account_refusal(pace, clock())
                elif rc in (0, 76, 77, 78):
                    account_clean(pace, clock(), clock() - now)
                item["squad_done"] = item["squad_done"] or squad_done
                if rc == 0:
                    evidence = read_metadata(full, code).get("last_success", {})
                    if (evidence.get("campaign") != item["checkpoint_campaign"]
                            or evidence.get("sha256") != fingerprints(full, code)):
                        raise ValueError("Collection evidence mismatch")
                    item.update(state="collected", reason="success")
                    item.pop("storage_failures", None)
                    state["refusals"] = 0
                    share(code)
                elif rc == 75:
                    refusal(state, item, clock())
                elif rc == 76:
                    # Run deadline, not a failure: resume next run, from checkpoints.
                    item.update(state="retry", due=clock(), reason="run_deadline")
                    state["refusals"] = 0
                elif rc == 77:
                    item.update(state="retry", due=clock() + TEMPORARY_RETRY,
                                reason="temporary_network")
                elif rc == 78:
                    # GitHub checkpoint storage, not the source: what was collected
                    # is kept locally and re-sent by the next attempt. An outage that
                    # outlasts two retries of the same league is the operator's.
                    item["storage_failures"] = item.get("storage_failures", 0) + 1
                    if item["storage_failures"] > MAX_STORAGE_FAILURES:
                        item.update(state="suspended", reason="checkpoint_storage")
                        suspend(state, "checkpoint_storage")
                    else:
                        item.update(state="retry", due=clock() + STORAGE_RETRY,
                                    reason="checkpoint_storage")
                else:
                    raise RuntimeError(f"Unclassified collector exit {rc}")
            except Exception as exc:
                item.update(state="suspended", reason="unclassified_failure")
                suspend(state, "unclassified_failure")
                print(f"COLLECTOR_ERROR {code}: {type(exc).__name__}: {exc}", flush=True)
            store.save(release_id, state)
            print(f"LEAGUE_RESULT {code} {item['state']}", flush=True)
            if item.get("reason") == "run_deadline":
                break                      # run over: next run resumes from checkpoints
            block = [c for c in PRIORITY if c in state["leagues"]]
            if (item["state"] == "collected" and code in block
                    and not state.get("priority_published")
                    and all(state["leagues"][c]["state"] in {"collected", "publishing", "done"}
                            for c in block)):
                state["priority_published"] = True
                store.save(release_id, state)
                print("TM_PRIORITY_BLOCK collected: publishing now, next run continues",
                      flush=True)
                break
    finally:
        try:
            token_file.unlink()
        except OSError:
            pass
