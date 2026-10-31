"""Offline checks for full benchmark isolation and cold-restore validation."""
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


class FullBenchmarkTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "benchmark_under_test", Path(__file__).resolve().parents[1] / "scripts/benchmark_collection.py")
        self.mod = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"BENCHMARK_PROFILE": "full", "BENCHMARK_SAMPLE": "20"}):
            spec.loader.exec_module(self.mod)
        self.env = patch.dict(os.environ, {"GITHUB_RUN_ID": "1234", "GITHUB_RUN_ATTEMPT": "2"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_full_exports_are_isolated_and_verified(self):
        mod = self.mod
        commands = []

        class Process:
            def __init__(self, cmd, **kwargs):
                commands.append(cmd)
                assert "--test" not in cmd and "--checkpoint-remote" in cmd
                assert kwargs["env"]["TM_CHECKPOINT_REMOTE"] == "github"
                code = cmd[cmd.index("--league") + 1]
                identity = cmd[cmd.index("--campaign") + 1]
                assert identity == f"benchmark-full-1234-2-{code}"
                exports = Path(cmd[cmd.index("--out-dir") + 1])
                exports.mkdir(parents=True)
                hashes = {}
                for suffix in ("summary", "career", "matches", "competitions_seen"):
                    content = b"player_id\n1\n2\n"
                    (exports / f"{code}_{suffix}.csv").write_bytes(content)
                    hashes[suffix] = hashlib.sha256(content).hexdigest()
                (exports / f"{code}_collection.json").write_text(json.dumps({
                    "last_attempt": {"status": "success"},
                    "last_success": {"campaign": identity, "sha256": hashes},
                }))

            def poll(self):
                return 0

        with tempfile.TemporaryDirectory() as tmp, patch.object(mod.subprocess, "Popen", Process), \
                patch.object(mod, "expected_ids", return_value={"1", "2"}), \
                patch.object(mod.time, "sleep"), patch("builtins.print"):
            result = mod.run_profile(5, Path(tmp))
        self.assertTrue(result["success"])
        self.assertEqual(sum(r["players"] for r in result["results"]), 10)
        self.assertEqual(len(set(c[c.index("--campaign") + 1] for c in commands)), 5)

    def test_cold_restore_rejects_missing_or_changed_records(self):
        mod = self.mod
        for restored, succeeds in [({"player_id": "1", "data": "original"}, True),
                                   (None, False), ({"player_id": "1", "data": "different"}, False)]:
            with self.subTest(restored=restored), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                local = folder / "cdn1/checkpoints" / mod.campaign(5, "cdn1")
                local.mkdir(parents=True)
                (local / "1.json").write_text(json.dumps({"player_id": "1", "data": "original"}))
                class Remote:
                    tag = "test-only"
                    def __init__(self, root, campaign, remote):
                        assert remote and not Path(root).exists()
                    def get(self, pid):
                        return restored
                fake = types.SimpleNamespace(Checkpoints=Remote, valid_record=lambda r, c, p: r is not None)
                results = [{"league": "cdn1"}]
                with patch.dict("sys.modules", {"tm_career_checkpoints": fake}), \
                        patch.object(mod, "expected_ids", return_value={"1"}), patch("builtins.print"):
                    if succeeds:
                        mod.verify_remote(5, folder, results)
                        self.assertEqual(results[0]["remote_restored_players"], 1)
                    else:
                        with self.assertRaises(AssertionError):
                            mod.verify_remote(5, folder, results)


if __name__ == "__main__":
    unittest.main()
