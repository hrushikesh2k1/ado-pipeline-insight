# Ingestion validation

Azure DevOps build/timeline data is the source of truth. Verify one run before a large backfill:

`python scripts/verify_ingested_run.py <run_id>`

Then verify several recent runs:

`python scripts/verify_ingested_run.py --latest 5`

The verifier compares run metadata and each normalized Stage/Job/Task by Azure DevOps timeline `record_id`, including timestamps, durations, result, and degraded state.
