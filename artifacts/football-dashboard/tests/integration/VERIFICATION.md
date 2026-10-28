# GitHub runner verification — 2026-10-28

- Authorized test repository: `MaloElPipo/ViveLaPiscine`
- Successful run: https://github.com/MaloElPipo/ViveLaPiscine/actions/runs/40651056821
- Tested commit: `a25bc7941eabd9f25e39aa07fa16fe3cb317d0b7`
- Result: **success**, all three jobs successful.
- Storage credentials: each runner's `GITHUB_TOKEN`, with `contents: write`.
  The workspace credential was used only to prepare the isolated test branch,
  read execution results and remove the branch; it was not injected into jobs.

## Observed assertions (UTC)

| Time | Evidence |
| --- | --- |
| 07:35:29 | Actual collector retry shell preserved `campaign_id`; dispatch intercepted |
| 07:35:49 | Real periodic timer uploaded a sub-threshold batch to a draft release |
| 07:35:50 | First process exited abruptly with code 23 and an unpublished response |
| 07:36:04 | Separate runner restored responses and original timestamps; unpublished tail absent |
| 07:36:19 | Injected compaction upload failure preserved all 100 real assets |
| 07:38:06 | Successful replacement downloaded and checked before first deletion; compacted restore succeeded |
| 07:38:17 | Cleanup verified no release/assets or tag remained |

The temporary branch was subsequently deleted and its absence checked through
the GitHub API. The first development run also completed its cleanup successfully.
No production repository files, default branch, portal or data were changed.

## Scope and limits

Only synthetic response data was used. There was no scraper import and no
Transfermarkt request. Runner loss is represented by abrupt process termination,
discarding local state, completing that job, and restoring in a separate fresh
GitHub-hosted runner. This does not claim to simulate a physical host outage.

The collector's real retry command was executed against an intercepted `gh`
dispatcher, not against the production scraping workflow. Its extracted campaign
argument was passed through a real reusable-workflow input, using the exact
collector input expression. This verifies forwarding without accidentally
scraping or publishing.

An initial harness run exposed that the intentional upload failure can occur
inside `put()` itself once 15 seconds have elapsed, rather than only inside the
explicit `flush()`. The harness now handles both entry points. The storage
implementation required no change.

Local existing regression suite: **10 tests passed** with
`python -m unittest discover -s artifacts/football-dashboard/tests -p test_tm_career_checkpoints.py`.
The final harness also passed Python compilation. GitHub parsed and executed
both workflow files successfully.
