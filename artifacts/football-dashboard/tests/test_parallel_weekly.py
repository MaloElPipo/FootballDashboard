import csv
from datetime import datetime, timedelta, timezone
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import parallel_collection as p
import tm_collection_queue as q
import tm_waf


def stamp(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def record(pid, campaign, minutes_ago=0):
    return {"version": 1, "campaign": campaign, "player_id": pid,
            "collected_at": stamp(minutes_ago), "data": {"performance": []}}


def write_squad(root, code, rows):
    path = root / f"live/data/tm_scrap/{code}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["player_id", "team_id", "season", "appearances"])
        writer.writeheader()
        for pid, season, apps in rows:
            writer.writerow({"player_id": pid, "team_id": "1", "season": season,
                             "appearances": apps})


class FakeCheckpoints:
    """Per-campaign store; the fake career process fills it like the real one."""
    records = {}

    def __init__(self, root, campaign, remote=False):
        self.campaign = campaign

    def get(self, pid):
        return FakeCheckpoints.records.get(self.campaign, {}).get(pid)


class Harness:
    """Clock, queue store, subprocesses and gh, all injected; no network."""

    def __init__(self, root, codes, squads, career_rc=None):
        self.root = root
        self.now = [1000.0]
        self.calls = []
        self.fetched = {}
        self.reused = {}
        self.envs = []
        self.career_rc = career_rc or {}
        self.assets = {}
        self.league_seconds = 60
        self.main = threading.get_ident()
        self.store = Mock()
        self.store.save.side_effect = lambda *a: self._assert_main()
        for code, ids in squads.items():
            write_squad(root, code, [(pid, 2026, 1) for pid in ids])
        self.leagues = {c: {"code_tm": c.upper(), "slug": c} for c in codes}
        FakeCheckpoints.records = {}

    def _assert_main(self):
        assert threading.get_ident() == self.main

    def clock(self):
        return self.now[0]

    def run(self, cmd, **kwargs):
        self.envs.append(kwargs.get("env") or {})
        if "tm_league_scraper.py" in cmd:
            self.calls.append(("squad", cmd[cmd.index("--comp") + 1].lower()))
            return Mock(returncode=0)
        code = cmd[cmd.index("--league") + 1]
        campaign = cmd[cmd.index("--campaign") + 1]
        folder = Path(cmd[cmd.index("--checkpoint-dir") + 1]) / campaign
        self.calls.append(("career", code, campaign, cmd[cmd.index("--budget-seconds") + 1],
                           cmd[cmd.index("--workers") + 1]))
        rc = self.career_rc.get(code, 0)
        if callable(rc):
            rc = rc()
        if rc:
            self.now[0] += 60
            return Mock(returncode=rc)
        store = FakeCheckpoints.records.setdefault(campaign, {})
        ids = p.league_ids(self.root / f"live/data/tm_scrap/{code}.csv")
        for pid in sorted(ids):
            local = folder / f"{pid}.json"
            if local.exists():
                store[pid] = json.loads(local.read_text())
                self.reused.setdefault(code, set()).add(pid)
            else:
                store[pid] = record(pid, campaign)
                self.fetched.setdefault(code, set()).add(pid)
        self.now[0] += self.league_seconds
        return Mock(returncode=0)

    def gh(self, *args):
        if args[:2] == ("release", "upload"):
            path = Path(args[3])
            self.assets[path.name] = path.read_bytes()
            return Mock(returncode=0)
        if args[:2] == ("release", "download"):
            target = Path(args[args.index("--dir") + 1])
            if not self.assets:
                return Mock(returncode=1)
            for name, data in self.assets.items():
                (target / name).write_bytes(data)
            return Mock(returncode=0)
        raise AssertionError(args)

    def metadata(self, _folder, code):
        return {"last_success": {"campaign": f"week-{code}", "sha256": {"x": "y"}}}

    def collect(self, state, remote=True, hours=3):
        env = {"TM_CHECKPOINT_REMOTE": "github" if remote else ""}
        with patch.object(p, "Checkpoints", FakeCheckpoints), \
             patch.object(p, "read_metadata", side_effect=self.metadata), \
             patch.object(p, "fingerprints", return_value={"x": "y"}), \
             patch.dict(os.environ, env):
            p.collect(self.store, 1, state, self.root, self.leagues, clock=self.clock,
                      run=self.run, hours=hours, gh=self.gh)


def campaign(codes):
    state = q.new_campaign("week", codes, True)
    state["owner"] = "1"
    return state


class WeeklyCollectionTests(unittest.TestCase):
    def test_zero_budget_is_accepted_without_source_request(self):
        import tm_player_career as career
        with patch.object(sys, "argv", ["scraper", "--league", "x1", "--budget-seconds", "0"]), \
             patch.object(career, "collect") as collect:
            career.cli()
        self.assertEqual(collect.call_args.args[0].budget_seconds, 0)

    def test_seed_keeps_dates_filters_ids_and_never_overwrites(self):
        rec = {"player_id": "1", "campaign": "old", "collected_at": "original"}
        source = Mock()
        source._all_records.return_value = [rec, {**rec, "player_id": "2"}]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            p.seed_checkpoints(source, dest, "new", {"1"})
            self.assertEqual(json.loads((dest / "1.json").read_text()),
                             {**rec, "campaign": "new"})
            self.assertFalse((dest / "2.json").exists())
            (dest / "1.json").write_text("newer")
            p.seed_checkpoints(source, dest, "new", {"1"})
            self.assertEqual((dest / "1.json").read_text(), "newer")

    def test_single_flow_one_token_file_and_cross_league_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0", "x1", "x2"],
                        {"x0": ["1", "2"], "x1": ["2", "3"], "x2": ["4"]})
            state = campaign(["x0", "x1", "x2"])
            h.collect(state)
        careers = [c for c in h.calls if c[0] == "career"]
        self.assertEqual([c[1] for c in careers], ["x0", "x1", "x2"])
        self.assertEqual(h.calls[0], ("squad", "x0"))           # squads then careers
        self.assertEqual(len({c[2] for c in careers}), 3)      # one campaign per league
        self.assertTrue(all(c[3] == "0" and c[4] == "2" for c in careers))
        self.assertEqual(h.fetched, {"x0": {"1", "2"}, "x1": {"3"}, "x2": {"4"}})
        self.assertEqual(h.reused, {"x1": {"2"}})               # not requested twice
        reused = FakeCheckpoints.records["week-x1"]["2"]
        self.assertEqual(reused["collected_at"],               # original date kept
                         FakeCheckpoints.records["week-x0"]["2"]["collected_at"])
        self.assertEqual(reused["campaign"], "week-x1")
        token_files = {e.get("TM_WAF_TOKEN_FILE") for e in h.envs}
        self.assertEqual(len(token_files), 1)                  # one token per run
        self.assertTrue(all(e.get("TM_PAUSE_MIN") and e.get("TM_PAUSE_MAX") for e in h.envs))
        self.assertTrue(all(i["state"] == "collected" for i in state["leagues"].values()))
        self.assertEqual(state.get("refusals"), 0)
        q.validate(state)

    def test_refusal_holds_whole_campaign_and_stops_all_traffic(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0", "x1"], {"x0": ["1"], "x1": ["2"]},
                        career_rc={"x0": 75})
            state = campaign(["x0", "x1"])
            h.collect(state)
            self.assertEqual([c[1] for c in h.calls if c[0] == "career"], ["x0"])
            self.assertNotIn(("squad", "x1"), h.calls)          # no other league, no probe
            hold = state["hold_until"]
            self.assertEqual(hold, h.now[0] + 2 * 3600)
            self.assertEqual(state["refusals"], 1)
            self.assertEqual(state["leagues"]["x0"]["state"], "retry")
            self.assertEqual(q.due_codes(state, hold - 1), [])  # prepare: no browser
            self.assertEqual(q.due_codes(state, hold), ["x0", "x1"])
            before = len(h.calls)
            h.now[0] = hold - 1
            h.collect(state)                                   # still held: nothing
            self.assertEqual(len(h.calls), before)

    def test_holds_escalate_then_operator_after_third(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0"], {"x0": ["1"]}, career_rc={"x0": 75})
            state = campaign(["x0"])
            waits = []
            for _ in range(3):
                h.collect(state)
                waits.append(state["hold_until"] - h.now[0])
                h.now[0] = state["hold_until"]
            self.assertEqual(waits, [7200, 21600, 86400])
            self.assertEqual(state["status"], "active")
            h.collect(state)
            self.assertEqual(state["status"], "suspended")
            self.assertTrue(state["access_hold"])
            self.assertEqual(state["leagues"]["x0"]["state"], "suspended")
            q.validate(state)

    def test_success_and_deadline_reset_refusals_without_new_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = iter([76, 0])
            h = Harness(Path(tmp), ["x0"], {"x0": ["1"]},
                        career_rc={"x0": lambda: next(outcomes)})
            state = campaign(["x0"])
            state.update(refusals=2, hold_until=h.now[0] - 1)
            h.collect(state)
            item = state["leagues"]["x0"]
            self.assertEqual((item["state"], item["reason"]), ("retry", "run_deadline"))
            self.assertEqual(item["due"], h.now[0])             # next run, no penalty
            self.assertEqual(state["refusals"], 0)
            self.assertLess(state["hold_until"], h.now[0])
            h.collect(state)
            self.assertEqual(item["state"], "collected")

    def test_checkpoint_storage_outage_retries_the_league_without_suspending(self):
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = iter([78, 0])
            h = Harness(Path(tmp), ["x0", "x1"], {"x0": ["1"], "x1": ["2"]},
                        career_rc={"x0": lambda: next(outcomes)})
            state = campaign(["x0", "x1"])
            h.collect(state)
            item = state["leagues"]["x0"]
            self.assertEqual((item["state"], item["reason"]), ("retry", "checkpoint_storage"))
            self.assertEqual(item["due"], 1060 + p.STORAGE_RETRY)
            self.assertEqual(state["leagues"]["x1"]["state"], "collected")   # the queue goes on
            self.assertEqual(state["status"], "active")
            self.assertEqual(state.get("refusals", 0), 0)                   # not the source
            self.assertNotIn("hold_until", state)
            self.assertGreater(state["pace"]["clean_seconds"], 0)
            h.now[0] = item["due"]
            h.collect(state)
            self.assertEqual(item["state"], "collected")
            self.assertNotIn("storage_failures", item)                      # success clears it
            q.validate(state)

    def test_persistent_checkpoint_storage_outage_asks_for_the_operator(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0"], {"x0": ["1"]}, career_rc={"x0": 78})
            state = campaign(["x0"])
            item = state["leagues"]["x0"]
            for failures in (1, 2):                                         # two retries
                h.collect(state)
                self.assertEqual((item["state"], item["storage_failures"]), ("retry", failures))
                h.now[0] = item["due"]
            h.collect(state)                                                # the third failure
            self.assertEqual((item["state"], item["reason"]), ("suspended", "checkpoint_storage"))
            self.assertEqual((state["status"], state["reason"]),
                             ("suspended", "checkpoint_storage"))
            self.assertFalse(state.get("access_hold"))                      # not a refusal
            self.assertEqual(state.get("refusals", 0), 0)
            q.validate(state)

    def test_share_failure_never_fails_a_validated_league(self):
        class Broken(FakeCheckpoints):
            def get(self, pid):
                raise RuntimeError("GitHub unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0", "x1"], {"x0": ["1"], "x1": ["1"]})
            state = campaign(["x0", "x1"])
            calls = {"n": 0}
            def factory(root, camp, remote=False):
                calls["n"] += 1
                return FakeCheckpoints(root, camp) if calls["n"] == 1 else Broken(root, camp)
            with patch.object(p, "Checkpoints", side_effect=factory), \
                 patch.object(p, "read_metadata", side_effect=h.metadata), \
                 patch.object(p, "fingerprints", return_value={"x": "y"}), \
                 patch.dict(os.environ, {"TM_CHECKPOINT_REMOTE": ""}):
                p.collect(h.store, 1, state, h.root, h.leagues, clock=h.clock,
                          run=h.run, hours=3, gh=h.gh)
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["leagues"]["x0"]["state"], "collected")

    def test_seed_assets_restore_dedupe_across_runs_with_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0", "x1"], {"x0": ["2"], "x1": ["2", "3"]})
            state = campaign(["x0", "x1"])
            state["leagues"]["x0"].update(state="done", checkpoint_campaign="week-x0")
            good = record("2", "week-x0", minutes_ago=600)
            lines = [good, record("9", "week-x0"), record("3", "other-x0"),
                     {**record("3", "week-x0"), "data": {}}]
            h.assets["seed-x0.ndjson.gz"] = gzip.compress(
                "".join(json.dumps(r) + "\n" for r in lines).encode())
            h.collect(state)                                     # a later run
        self.assertEqual(h.fetched, {"x1": {"3"}})              # 2 reused, 3 requested
        self.assertEqual(FakeCheckpoints.records["week-x1"]["2"]["collected_at"],
                         good["collected_at"])

    def test_completed_league_without_asset_is_still_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0", "x1"], {"x0": ["2"], "x1": ["2", "3"]})
            state = campaign(["x0", "x1"])
            state["leagues"]["x0"].update(state="collected", checkpoint_campaign="week-x0")
            original = record("2", "week-x0", minutes_ago=300)
            FakeCheckpoints.records = {"week-x0": {"2": original}}
            h.collect(state)
        self.assertEqual(h.fetched, {"x1": {"3"}})
        self.assertIn("seed-x0.ndjson.gz", h.assets)          # uploaded for next runs
        self.assertEqual(FakeCheckpoints.records["week-x1"]["2"]["collected_at"],
                         original["collected_at"])

    def test_priority_block_is_published_first_then_queue_continues(self):
        codes = ["x1", "es1", "gb1", "it1", "fr1", "nl1"]
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), codes, {c: [str(i)] for i, c in enumerate(codes)})
            state = campaign(codes)
            h.collect(state)                                   # first run stops early
            self.assertEqual([c[1] for c in h.calls if c[0] == "career"], codes[:5])
            self.assertTrue(state["priority_published"])
            self.assertEqual(state["leagues"]["nl1"]["state"], "pending")
            h.collect(state)                                   # next run: the rest
        self.assertEqual([c[1] for c in h.calls if c[0] == "career"], codes)
        self.assertTrue(all(i["state"] == "collected" for i in state["leagues"].values()))

    def test_squad_seasons_skip_only_closed_seasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_squad(root, "aut", [("1", 2025, 30), ("1", 2026, 9)])
            write_squad(root, "cal", [("1", 2025, 30), ("1", 2026, 0)])
            squads = root / "live/data/tm_scrap"
            self.assertEqual(p.squad_seasons(squads / "aut.csv", 2026), [2026])
            self.assertEqual(p.squad_seasons(squads / "cal.csv", 2026), [2025, 2026])
            self.assertEqual(p.squad_seasons(squads / "missing.csv", 2026), [2025, 2026])
            self.assertEqual(p.squad_seasons(squads / "aut.csv", 2027), [2026, 2027])

    def test_parallel_retries_not_exhausted_at_four(self):
        state = q.new_campaign("week", ["x1"])
        state["parallel"] = True
        state["leagues"]["x1"].update(state="retry", attempts=5, due=120)
        q.validate(state)
        self.assertEqual(q.due_codes(state, 119), [])
        self.assertEqual(q.due_codes(state, 120), ["x1"])

    def test_pace_cannot_exceed_two_requests_per_second(self):
        cases = {("1.0", "1.5"): (1.0, 1.5), ("0.4", "0.6"): (0.4, 0.6),
                 ("0.3", "0.5"): (1.0, 1.5), ("0.35", "0.65"): (1.0, 1.5),
                 ("0.2", "0.4"): (1.0, 1.5), ("x", "1"): (1.0, 1.5)}
        for (low, high), expected in cases.items():
            with patch.dict(os.environ, {"TM_PAUSE_MIN": low, "TM_PAUSE_MAX": high}):
                self.assertEqual(tm_waf.pace_from_env((1.0, 1.5)), expected)

    def test_every_ladder_level_is_really_applied_by_the_collectors(self):
        """Invariant: a level the collectors would reject would silently run at 0.8."""
        for rate in p.RATES:
            low, high = p.pause_bounds(rate)
            env = {"TM_PAUSE_MIN": f"{low:.3f}", "TM_PAUSE_MAX": f"{high:.3f}"}
            with patch.dict(os.environ, env):
                applied = tm_waf.pace_from_env((9.0, 9.0))
            self.assertEqual(applied, (low, high))
            self.assertAlmostEqual(2 / (low + high), rate, delta=0.01)
        self.assertEqual(max(p.RATES), p.RATE_CEILING)

    def test_ceiling_setting_can_only_lower_the_ladder(self):
        pace = p.new_pace(0)
        for value, expected in (("0.8", 0), ("1.2", 2), ("2.0", 4), ("5", 4), ("x", 4)):
            with patch.dict(os.environ, {"TM_RATE_CEILING": value}):
                self.assertEqual(p.max_level(pace, 0), expected)

    def test_ladder_promotes_one_level_after_six_clean_hours(self):
        codes = [f"x{i}" for i in range(6)]
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), codes, {c: [str(i)] for i, c in enumerate(codes)})
            h.league_seconds = 2 * 3600
            state = campaign(codes)
            with patch.dict(os.environ, {"TM_RATE_CEILING": "2.0"}):
                h.collect(state, remote=False, hours=100)
        careers = [(c[1], e["TM_PAUSE_MIN"]) for c, e in zip(h.calls, h.envs) if c[0] == "career"]
        self.assertEqual(careers, [("x0", "1.000"), ("x1", "1.000"), ("x2", "1.000"),
                                   ("x3", "0.800"), ("x4", "0.800"), ("x5", "0.800")])
        self.assertEqual([state["leagues"][c]["rate"] for c in codes],
                         [0.8, 0.8, 0.8, 1.0, 1.0, 1.0])
        self.assertEqual([e["event"] for e in state["pace"]["history"]],
                         ["promote", "promote"])
        self.assertEqual(p.RATES[state["pace"]["level"]], 1.2)   # after the 6th league
        q.validate(state)

    def test_refusal_steps_down_and_caps_two_weeks_then_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = Harness(Path(tmp), ["x0", "x1", "x2"], {"x0": ["1"], "x1": ["2"], "x2": ["3"]},
                        career_rc={"x0": 75})
            h.league_seconds = 4 * 3600
            state = campaign(["x0", "x1", "x2"])
            state["pace"] = {**p.new_pace(0), "level": 3, "clean_seconds": 5 * 3600}
            h.collect(state)                                    # refused at 1.5 req/s
            pace = state["pace"]
            self.assertEqual((pace["level"], pace["cap"]), (2, 2))
            self.assertEqual(pace["clean_seconds"], 0)
            self.assertEqual(pace["cap_until"], h.now[0] + p.DEMOTION_CAP)
            self.assertEqual(state["hold_until"], h.now[0] + 2 * 3600)
            h.career_rc = {}
            h.now[0] = state["hold_until"]
            h.collect(state, hours=100)                         # 3 leagues x 4 h, all clean
            self.assertEqual(pace["level"], 2)                 # capped: no promotion
            self.assertGreaterEqual(pace["clean_seconds"], p.PROMOTE_AFTER)
            self.assertEqual({state["leagues"][c]["rate"] for c in ["x0", "x1", "x2"]}, {1.2})
            p.account_clean(pace, pace["cap_until"] + 1, 60)   # cap expired: resumes
            self.assertEqual(pace["level"], 3)
            self.assertEqual([e["event"] for e in pace["history"]], ["demote", "promote"])

    def test_repeated_refusals_at_a_rate_space_out_the_retests(self):
        pace = {**p.new_pace(0), "level": 2}
        week = 7 * 86400
        p.account_refusal(pace, 0)                       # 1.2 refused: 2 weeks at 1.0
        self.assertEqual((pace["level"], pace["cap_until"]), (1, 2 * week))
        pace["level"] = 2                                # re-tested later, refused again
        p.account_refusal(pace, 10 * week)
        self.assertEqual(pace["cap_until"], 10 * week + 4 * week)
        pace["level"] = 2
        p.account_refusal(pace, 20 * week)
        self.assertEqual(pace["cap_until"], 20 * week + 8 * week)
        pace["level"] = 2
        p.account_refusal(pace, 40 * week)               # never more than 8 weeks
        self.assertEqual(pace["cap_until"], 40 * week + 8 * week)
        self.assertEqual(pace["refusals_by_rate"], {"1.2": 4})
        pace.update(level=2, cap_until=0, clean_seconds=0)
        p.account_clean(pace, 50 * week, p.PROMOTE_AFTER)  # 1.2 finally clean: forgiven
        self.assertEqual((pace["level"], pace["refusals_by_rate"]), (3, {}))

    def test_refusal_at_the_lowest_level_stays_at_lowest(self):
        pace = p.new_pace(0)
        p.account_refusal(pace, 100)
        self.assertEqual((pace["level"], pace["cap"]), (0, 0))
        p.account_clean(pace, 200, 10 * 3600)
        self.assertEqual(pace["level"], 0)

    def test_new_weekly_campaign_inherits_the_latest_ladder(self):
        from scripts import collection_queue as runner
        old = q.new_campaign("run-1", ["l1"]); old["status"] = "complete"
        old["pace"] = {**p.new_pace(100), "level": 1}
        newer = q.new_campaign("run-2", ["l1"]); newer["status"] = "complete"
        newer["pace"] = {**p.new_pace(200), "level": 3, "cap": 3, "cap_until": 999}

        class Store:
            def __init__(self):
                self.saved = None
            def inventory(self):
                return [(1, old), (2, newer)]
            def create(self, state):
                self.saved = state
                return 3
            def save(self, release_id, state):
                self.saved = state
        with tempfile.TemporaryDirectory() as tmp:
            clearance = Path(tmp) / "access.json"
            clearance.write_text(json.dumps({
                "version": 1, "status": "reconciled", "resolution": "offline test",
                "reviewed_at": "2026-10-29T00:00:00+00:00"}))
            store = Store()
            with patch.object(runner, "ACCESS_FILE", clearance):
                release_id, state = runner.prepare(store, "3", create=True)
        self.assertEqual(release_id, 3)
        self.assertEqual(state["campaign"], "run-3")
        self.assertEqual((state["pace"]["level"], state["pace"]["cap_until"]), (3, 999))
        self.assertIsNot(state["pace"], newer["pace"])       # copy, not shared


class SharedTokenTests(unittest.TestCase):
    def setUp(self):
        self.saved = (tm_waf._token, tm_waf._gave_up, tm_waf._consecutive_failures)
        tm_waf._token, tm_waf._gave_up, tm_waf._consecutive_failures = None, False, 0
        tm_waf._access_refused.clear()

    def tearDown(self):
        tm_waf._token, tm_waf._gave_up, tm_waf._consecutive_failures = self.saved
        tm_waf._access_refused.clear()

    def test_one_browser_session_per_run_and_refresh_is_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "token"
            path.write_text("T1")
            with patch.dict(os.environ, {"TM_WAF_TOKEN_FILE": str(path)}), \
                 patch.object(tm_waf, "_disabled", False), \
                 patch.object(tm_waf, "_launch_and_get_token", return_value="T2") as launch:
                self.assertEqual(tm_waf.get_waf_token(), "T1")      # no browser
                launch.assert_not_called()
                self.assertEqual(tm_waf.get_waf_token(force_refresh=True, stale="T1"), "T2")
                self.assertEqual(path.read_text(), "T2")            # shared with others
                self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
                tm_waf._token = "T1"                               # another process
                self.assertEqual(tm_waf.get_waf_token(force_refresh=True, stale="T1"), "T2")
                self.assertEqual(launch.call_count, 1)

    def test_without_shared_file_behaviour_is_unchanged(self):
        with patch.dict(os.environ, {"TM_WAF_TOKEN_FILE": ""}), \
             patch.object(tm_waf, "_disabled", False), \
             patch.object(tm_waf, "_launch_and_get_token", return_value="T9") as launch:
            self.assertEqual(tm_waf.get_waf_token(), "T9")
            launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
