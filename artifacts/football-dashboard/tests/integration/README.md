# Real GitHub checkpoint recovery (synthetic data only)

This opt-in test exercises the **unmodified** `Checkpoints` storage implementation
using real GitHub draft releases and the runner's scoped `GITHUB_TOKEN` (exposed
to `gh` as `GH_TOKEN`). It never imports the scraper or calls Transfermarkt.

## Safety and execution

The workflow and script both restrict execution to the explicitly authorized
test repository `MaloElPipo/ViveLaPiscine`. Do not broaden this allowlist without
authorization. There are no scheduled runs.

Create an isolated `tm-checkpoint-integration/<unique-suffix>` branch **in that
test repository**, containing only these files from the version being tested:

- `.github/workflows/tm-checkpoint-integration.yml`
- `.github/workflows/tm-checkpoint-integration-resume.yml`
- `.github/workflows/scrape-weekly.yml` (contract fixture, never dispatched)
- `artifacts/football-dashboard/tm_career_checkpoints.py`
- `artifacts/football-dashboard/tm_checkpoint_retention.py`
- `artifacts/football-dashboard/tests/integration/checkpoint_runner.py`

Pushing that branch triggers the integration workflow. Leave the test
repository's default branch and existing application untouched. A unique
`it-<run_id>-<run_attempt>` campaign prevents collisions between runs. Do not
reuse a failed run's campaign for a new run.

No Python dependencies beyond the standard library are required; Ubuntu GitHub
runners supply Python and `gh`. `contents: write` is required for draft releases.
The parent workflow runs three jobs:

1. **First runner:** executes the actual retry shell command extracted from
   `scrape-weekly.yml`, intercepting only the `gh workflow run` invocation.
   Its `campaign_id` argument becomes the job output passed into the reusable
   second-runner workflow. That workflow evaluates the same input expression
   as the collector. The first runner creates a draft, waits for the real
   15-second periodic upload, records the original timestamp, leaves one
   response unpublished, then uses `os._exit(23)` to bypass graceful shutdown.
   The job checks that exact exit status and removes its local checkpoint files.
2. **Fresh runner:** restores exclusively from GitHub (no Actions artifact,
   cache, or workspace transfer), checks the original response and timestamp,
   and proves the unpublished tail was lost. It seeds 98 extra synthetic
   journals alongside the two initial batches to reach the real 100-asset
   compaction threshold. A deliberately failed upload must preserve all old
   assets. During the successful retry, the observer downloads and verifies
   the replacement from GitHub **before the first deletion**. Finally it
   restores the compacted snapshot in another empty local directory.
3. **Cleanup:** an `always()` job deletes only the exact run's draft release,
   verifies its assets/release are gone, and verifies that no Git tag remains.
   It refuses to delete a non-draft release.

The collector itself and its publication steps are deliberately not executed.
The retry command's argument forwarding is a contract test with an intercepted
dispatch; storage, the two runner jobs, workflow input evaluation and token
permissions are real.

## Evidence and cleanup

All assertions fail the job explicitly; `PASS` lines identify each verified
property. Success requires all three jobs to be green, not just cleanup.
Retain the Actions run URL and commit SHA in the verification report.

After the jobs finish, delete the dedicated branch. The Actions execution log
remains as evidence; no synthetic response files are committed to Git history.
If someone force-cancels the entire workflow before cleanup can run, manually
remove only the draft named `tm-checkpoints-it-<run_id>-<run_attempt>` after
checking its identity. Never apply the production retention purge to clean up
an integration test.

Local regression checks (no live GitHub access):

```sh
python -m unittest discover -s artifacts/football-dashboard/tests \
  -p test_tm_career_checkpoints.py
```
