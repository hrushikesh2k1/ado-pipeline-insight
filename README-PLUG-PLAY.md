# Plug-and-play v1 follow-up

Run the backend with Python 3.11 and the frontend with Node.js.

Required local `.env` values:

- SQL_CONNECTION_STRING
- MIN_HISTORY_RUNS
- AZURE_OPENAI_ENDPOINT
- AZURE_OPENAI_DEPLOYMENT
- AZURE_OPENAI_API_VERSION (optional)
- AZURE_OPENAI_API_KEY

The AI endpoint now loads Azure OpenAI settings from the same `.env` used by the FastAPI application. The recommendation query is disabled until a pipeline is selected. If completed run history is below `MIN_HISTORY_RUNS`, the UI reports the exact history requirement instead of returning a misleading empty panel.


## V7 telemetry correction

V7 treats a successful Azure DevOps timeline as the source of truth for a run. Re-ingestion replaces stale child stage/job/task telemetry, updates previously degraded runs to complete, and removes fallback child records. This fixes the earlier condition where existing 0-5 second child durations could survive a real ADO ingestion.

After deploying the Function, select the pipeline in the dashboard and use Ingest History. The dashboard queries Azure SQL again after ingestion. Use scripts/verify_ingested_run.py <run_id> to compare the normalized ADO timeline with stored SQL records.

## V8 clean-start requirements

`INGEST_FUNCTION_URL` is required by the FastAPI historical-ingestion route. Configure it in the project `.env` using the HTTPS Azure Function `ingest_pipeline` endpoint and its function key. A missing value returns a clear 503 configuration error.

For a clean validation, run `sql/reset_data.sql` once, ingest the selected pipeline history, then run `scripts/verify_ingested_run.py <run_id>`.
