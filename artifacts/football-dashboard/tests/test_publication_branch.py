"""Publication proved from the gh-pages BRANCH, so the public site can be offline.

Offline only: local git repositories, no GitHub, no source request.
"""
import functools
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tm_collection_queue as q

WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/scrape-weekly.yml"


def archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, value in files.items():
            z.writestr(name, value)
    return out.getvalue()


def done(returncode=0, stdout=b""):
    return Mock(returncode=returncode, stdout=stdout)


class BranchFetcherUnitTests(unittest.TestCase):
    def test_one_lazy_shallow_fetch_then_exact_bytes(self):
        run = Mock(side_effect=[done(), done(stdout=b"A"), done(stdout=b"B")])
        fetch = q.branch_fetcher(run=run)
        run.assert_not_called()                             # lazy: nothing before use
        self.assertEqual(fetch("data/x0_all.zip"), b"A")
        self.assertEqual(fetch("data/x0_current.zip"), b"B")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0], ["git", "fetch", "--quiet", "--no-tags", "--depth=1",
                                       "origin", "+refs/heads/gh-pages:refs/tm-publication/gh-pages"])
        self.assertEqual(commands[1], ["git", "show", "refs/tm-publication/gh-pages:data/x0_all.zip"])
        self.assertEqual(sum(c[1] == "fetch" for c in commands), 1)
        self.assertTrue(all(call.kwargs["capture_output"] for call in run.call_args_list))
        self.assertNotIn("text", run.call_args_list[1].kwargs)   # bytes, never decoded

    def test_every_failure_is_an_oserror(self):
        cases = {
            "fetch refused": [done(returncode=128)],
            "file absent": [done(), done(returncode=128)],
            "fetch timeout": [subprocess.TimeoutExpired("git", 600)],
            "show timeout": [done(), subprocess.TimeoutExpired("git", 120)],
            "git missing": [FileNotFoundError("git")],
        }
        for label, effects in cases.items():
            with self.subTest(label):
                fetch = q.branch_fetcher(run=Mock(side_effect=effects))
                with self.assertRaises(OSError):
                    fetch("data/x0_all.zip")


class StoreModeTests(unittest.TestCase):
    def store(self):
        store = q.GitHubStore()
        store.api = Mock(return_value={"html_url": "https://example.github.io/Repo/"})
        return store

    def test_branch_is_the_default_and_never_asks_for_the_site(self):
        store = self.store()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TM_PUBLICATION_CHECK", None)
            with patch.object(q, "branch_fetcher", return_value="BRANCH") as branch:
                self.assertEqual(store.public_fetcher(), "BRANCH")
        branch.assert_called_once_with()
        store.api.assert_not_called()                       # Pages may be disabled

    def test_site_mode_keeps_the_previous_behaviour(self):
        store = self.store()
        with patch.dict(os.environ, {"TM_PUBLICATION_CHECK": "site"}):
            fetch = store.public_fetcher()
        store.api.assert_called_once_with("repos/{owner}/{repo}/pages")
        self.assertTrue(callable(fetch))

    def test_unknown_mode_fails_loudly(self):
        with patch.dict(os.environ, {"TM_PUBLICATION_CHECK": "cdn"}):
            with self.assertRaises(ValueError):
                self.store().public_fetcher()


class RealGitTests(unittest.TestCase):
    """A real origin with a gh-pages branch, a shallow main checkout, as on a runner."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.git = lambda cwd, *args: subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "init.defaultBranch=main",
             *args], cwd=cwd, check=True, capture_output=True)
        origin = root / "origin.git"
        self.git(root, "init", "-q", "--bare", str(origin))
        work = root / "work"
        self.git(root, "init", "-q", str(work))
        (work / "README.md").write_text("code\n")
        self.git(work, "add", "README.md")
        self.git(work, "commit", "-q", "-m", "main")
        self.git(work, "push", "-q", str(origin), "HEAD:refs/heads/main")
        self.files = {"x0_summary.csv": b"player_id\n1\n", "x0_career.csv": b"season\n2026\n"}
        self.zip_bytes = archive(self.files)
        self.git(work, "checkout", "-q", "--orphan", "gh-pages")
        self.git(work, "rm", "-q", "-rf", "--cached", ".")
        (work / "README.md").unlink()
        (work / "data").mkdir()
        (work / "data/x0_all.zip").write_bytes(self.zip_bytes)
        (work / "index.html").write_text("<html>portail</html>")
        self.git(work, "add", "data", "index.html")
        self.git(work, "commit", "-q", "-m", "pages")
        self.git(work, "push", "-q", str(origin), "HEAD:refs/heads/gh-pages")
        self.runner = root / "runner"
        self.git(root, "clone", "-q", "--depth=1", "--branch", "main",
                 origin.as_uri(), str(self.runner))
        self.run = functools.partial(subprocess.run, cwd=self.runner)

    def campaign(self, expected):
        state = q.new_campaign("c", ["x0"], refresh=False)
        state["leagues"]["x0"].update(state="publishing", expected=expected,
                                      publication_started=1000)
        return state

    def test_exact_bytes_from_the_branch(self):
        fetch = q.branch_fetcher(run=self.run)
        self.assertEqual(fetch("data/x0_all.zip"), self.zip_bytes)
        with self.assertRaises(OSError):
            fetch("data/x9_all.zip")

    def test_verified_publication_completes_the_campaign(self):
        hashes = {name: q.digest(value) for name, value in self.files.items()}
        state = self.campaign({"all": hashes})
        q.verify_publication(state, q.branch_fetcher(run=self.run), 2000)
        self.assertEqual(state["leagues"]["x0"]["state"], "done")
        self.assertEqual(state["status"], "complete")

    def test_mismatch_is_never_success_and_still_times_out(self):
        state = self.campaign({"all": {"x0_summary.csv": "0" * 64,
                                       "x0_career.csv": q.digest(self.files["x0_career.csv"])}})
        q.verify_publication(state, q.branch_fetcher(run=self.run), 2000)
        self.assertEqual(state["leagues"]["x0"]["state"], "publishing")
        q.verify_publication(state, q.branch_fetcher(run=self.run), 1000 + q.PUBLICATION_LIMIT)
        self.assertEqual(state["leagues"]["x0"]["state"], "suspended")
        self.assertEqual(state["status"], "suspended")

    def test_missing_branch_is_not_verified(self):
        self.git(self.runner, "remote", "set-url", "origin",
                 (Path(self.temp.name) / "absent.git").as_uri())
        state = self.campaign({"all": {name: q.digest(v) for name, v in self.files.items()}})
        q.verify_publication(state, q.branch_fetcher(run=self.run), 2000)
        self.assertEqual(state["leagues"]["x0"]["state"], "publishing")


class WorkflowTests(unittest.TestCase):
    def test_weekly_workflow_checks_the_branch(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML absent")
        env = yaml.safe_load(WORKFLOW.read_text())["jobs"]["scrape-and-publish"]["env"]
        self.assertEqual(env["TM_PUBLICATION_CHECK"], "branch")


if __name__ == "__main__":
    unittest.main()
