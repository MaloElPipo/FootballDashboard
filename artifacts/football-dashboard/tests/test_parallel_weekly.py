import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import parallel_collection as p
import tm_collection_queue as q


class ParallelTests(unittest.TestCase):
    def test_zero_budget_is_accepted_without_source_request(self):
        import tm_player_career as career
        with patch.object(sys, "argv", ["scraper", "--league", "l1", "--budget-seconds", "0"]), \
             patch.object(career, "collect") as collect:
            career.cli()
        self.assertEqual(collect.call_args.args[0].budget_seconds, 0)

    def test_seed_keeps_dates_filters_ids_and_never_overwrites(self):
        record = {"player_id": "1", "campaign": "old", "collected_at": "original"}
        source = Mock()
        source._all_records.return_value = [record, {**record, "player_id": "2"}]
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)
            p.seed_checkpoints(source, dest, "new", {"1"})
            self.assertEqual(json.loads((dest / "1.json").read_text()),
                             {**record, "campaign": "new"})
            self.assertFalse((dest / "2.json").exists())
            (dest / "1.json").write_text("newer")
            p.seed_checkpoints(source, dest, "new", {"1"})
            self.assertEqual((dest / "1.json").read_text(), "newer")

    def test_five_parallel_isolated_and_one_queue_writer(self):
        codes = [f"l{i}" for i in range(5)]
        state = q.new_campaign("week", codes, True)
        state["owner"] = "1"
        barrier = threading.Barrier(5, timeout=5)
        calls = []
        main = threading.get_ident()
        store = Mock()
        store.save.side_effect = lambda *a: self.assertEqual(threading.get_ident(), main)
        def run(cmd, **kwargs):
            if "tm_player_career.py" in cmd:
                calls.append(cmd)
                barrier.wait()
                return Mock(returncode=0)
            return Mock(returncode=0)
        def metadata(_, code):
            return {"last_success": {"campaign": f"week-{code}", "sha256": {"x": "y"}}}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(p, "Checkpoints") as checkpoints, \
             patch.object(p, "read_metadata", side_effect=metadata), \
             patch.object(p, "fingerprints", return_value={"x": "y"}), \
             patch("tm_player_career.max_season_in_csv", return_value=2026), \
             patch("tm_player_career.load_player_meta_from_league_csv", return_value={"1": {}}):
            checkpoints.return_value._all_records.return_value = []
            p.collect(store, 1, state, Path(tmp),
                      {c: {"code_tm": c.upper(), "slug": c} for c in codes}, run=run)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len({c[c.index("--campaign")+1] for c in calls}), 5)
        self.assertTrue(all(c[c.index("--budget-seconds")+1] == "0" for c in calls))
        self.assertTrue(all(i["state"] == "collected" for i in state["leagues"].values()))
        q.validate(state)

    def test_parallel_retries_not_exhausted_at_four(self):
        state = q.new_campaign("week", ["l1"])
        state["parallel"] = True
        state["leagues"]["l1"].update(state="retry", attempts=5, due=120)
        q.validate(state)
        self.assertEqual(q.due_codes(state, 119), [])
        self.assertEqual(q.due_codes(state, 120), ["l1"])

    def test_refusal_waits_two_minutes_then_reuses_same_campaign(self):
        state = q.new_campaign("week", ["l1"], True)
        state["owner"] = "1"
        now = [0]
        attempts = []
        def sleep(seconds):
            now[0] += seconds
        def run(cmd, **kwargs):
            if "tm_player_career.py" in cmd:
                attempts.append((now[0], cmd[cmd.index("--campaign")+1]))
                return Mock(returncode=75 if len(attempts) == 1 else 0)
            return Mock(returncode=0)
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(p, "Checkpoints") as checkpoints, \
             patch.object(p, "read_metadata", return_value={
                 "last_success": {"campaign": "week-l1", "sha256": {}}}), \
             patch.object(p, "fingerprints", return_value={}), \
             patch("tm_player_career.max_season_in_csv", return_value=2026), \
             patch("tm_player_career.load_player_meta_from_league_csv", return_value={"1": {}}):
            checkpoints.return_value._all_records.return_value = []
            p.collect(Mock(), 1, state, Path(tmp), {"l1": {"code_tm": "L1", "slug": "x"}},
                      clock=lambda: now[0], sleep=sleep, run=run)
        self.assertEqual(attempts, [(0, "week-l1"), (120, "week-l1")])
        self.assertEqual(state["leagues"]["l1"]["state"], "collected")


if __name__ == "__main__":
    unittest.main()
