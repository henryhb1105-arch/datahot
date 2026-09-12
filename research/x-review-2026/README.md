# One-off 2026 X research preview

Requested under [Issue #204](https://github.com/henryhb1105-arch/datahot/issues/204). Scope: bounded collection, editorial screening, and a reviewable preview. No production content publication or recurring collection was requested for this step.

- `review.md`: Chinese editorial review, all 20 candidates, cost, limitations, deduplication, and display proposal.
- `preview.html`: static review cards with original links; no remote runtime assets or API calls.
- `candidates.json`: reviewed content, original URLs, X discovery links where observed, dates, caveats, and recommendations.
- `coverage.json`: observed collection counts and conservative price calculation. Invoice not verified.
- `budget.json`: durable per-query reservations/results, now closed.
- `queries.json`: exactly 30 bounded searches; it is a stratified sample, not a complete archive.
- `existing-index.json`: snapshot of existing DataHot source links used for duplicate checking.
- `collect_x.py`, `test_collect.py`: retired one-off collection implementation and budget tests. Do not rerun against X; the closed ledger rejects it.
- `curate.py`, `render_review.py`: local-only curation and rendering. No model calls. They expect the original combined API response index at `/tmp/datahot-x-review-2026/posts.json`; outputs are already checked in, so opening the review does not require regeneration.

Collection runs:

1. [34674397604](https://github.com/henryhb1105-arch/datahot/actions/runs/34674397604): two completed searches, 6 returned posts; stopped before another X request because the GitHub budget write could not be confirmed.
2. [34674484504](https://github.com/henryhb1105-arch/datahot/actions/runs/34674484504): resumed only previously unexecuted query IDs, completed the remaining 28 searches with 187 returned posts.

Raw responses were returned through access-controlled Actions artifacts (7-day retention), not committed to the public research branch. The reference IDs are recorded in `coverage.json`. Credentials stayed in Actions secrets and process memory, and were not included in artifacts or logs.

The ephemeral push-triggered workflow was removed after collection at commit `b26c4d6d`. The ledger is closed. There is no scheduled trigger, no X posting path, and no need to merge this branch into the production branch to read the results.

Verification: six cost/isolation/failure tests passed in both collection runs; the ledger contains 30 complete requests and 193 returned resources; 178 distinct post IDs; 20 candidate sources distinct from the existing URL index; HTML structure checked for 20 cards, valid section anchors and absence of remote runtime assets. Source content was reviewed through official web pages and public HTML. No vendor product benchmarks were independently reproduced. Browser visual inspection was not performed because desktop access was locked during this task.
