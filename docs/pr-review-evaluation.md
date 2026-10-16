# Evaluating PR review quality

The repository's mocked review tests validate orchestration, grounding, filtering,
lookups and error handling. They do not measure a live model's defect recall.

Before using a collection of human PR comments as a benchmark, retain the PR's
reviewed commit, base commit, relevant source files, comment text and resolution.
Have an engineer label each candidate independently:

| Label | Meaning | Include in defect recall? |
| --- | --- | --- |
| verified_defect | Reproducible regression with source evidence and a concrete failure | Yes |
| preference | Style or design preference without a demonstrated failure | No |
| process_request | Documentation, ownership, sign-off or workflow request | No |
| deferred_work | Existing issue or agreed future enhancement | No |
| disputed | Claim unresolved or contradicted; requires adjudication | No |

Keep separate tuning and held-out sets, splitting related PRs from the same change
or defect together to avoid leakage. Do not tune prompts on the held-out set.

Run the same model, deployment settings, guidance, commit and time budget for both
baseline and candidate. Preserve the full report, rejected candidates, lookup
coverage, failures, latency and token usage. Human reviewers must match findings
by underlying defect, not by exact phrasing or number of comments.

Report verified defects found and missed; recall = found / (found + missed).
Independently adjudicate every reported finding (including newly discovered real
defects absent from human comments). Report false positives and precision = true
findings / (true findings + false positives). Mark incomplete runs separately;
do not exclude them silently or call a zero-finding result a clean PR. Break down
results by language, pipeline/cloud/UI domain, PR size and review coverage.

The supplied count of historical reviews is not a measured accuracy result. No
recall percentage should be published until the labeled, held-out run is complete.
