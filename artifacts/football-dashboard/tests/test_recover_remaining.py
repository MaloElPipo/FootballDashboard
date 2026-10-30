import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "scripts/recover_remaining.py"
spec = importlib.util.spec_from_file_location("recover_remaining", PATH)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def run_case(self, codes, verification):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"GITHUB_OUTPUT": directory + "/out",
                                     "GITHUB_STEP_SUMMARY": directory + "/summary"}), \
             patch.object(recovery, "REMAINING", ["mex1"]), \
             patch.object(recovery.os, "chdir"), \
             patch.object(recovery, "git"), \
             patch.object(recovery, "verified", side_effect=verification), \
             patch.object(recovery, "persist") as persist, \
             patch.object(recovery.time, "sleep") as sleep, \
             patch.object(recovery.subprocess, "run", side_effect=[
                 subprocess.CompletedProcess([], code) for code in codes]) as run:
            try:
                result = recovery.main()
            except (SystemExit, RuntimeError) as exc:
                result = exc
            return result, run.call_count, persist.call_count, sleep.call_args_list

    def test_temporary_failure_resumes_after_two_minutes(self):
        result, requests, saved, waits = self.run_case([77, 0], [False, True])
        self.assertEqual((result, requests, saved), (0, 2, 1))
        self.assertEqual([x.args for x in waits], [(120,)])

    def test_budget_resumes_after_two_minutes(self):
        result, requests, saved, waits = self.run_case([76, 0], [False, True])
        self.assertEqual((result, requests, saved), (0, 2, 1))
        self.assertEqual([x.args for x in waits], [(120,)])

    def test_refusal_and_unknown_failure_never_retry(self):
        for code in (75, 1):
            result, requests, saved, waits = self.run_case([code], [False])
            self.assertIsInstance(result, SystemExit)
            self.assertEqual(result.code, code)
            self.assertEqual((requests, saved, waits), (1, 0, []))

    def test_success_without_valid_exports_stops(self):
        result, _, saved, _ = self.run_case([0], [False, False])
        self.assertIsInstance(result, RuntimeError)
        self.assertEqual(saved, 0)

    def test_verified_league_is_not_collected_again(self):
        self.assertEqual(self.run_case([], [True]), (0, 0, 0, []))

    def test_repeated_transient_error_is_bounded(self):
        result, requests, saved, waits = self.run_case([77] * 4, [False])
        self.assertIsInstance(result, SystemExit)
        self.assertEqual((requests, saved, len(waits)), (4, 0, 3))


if __name__ == "__main__":
    unittest.main()
