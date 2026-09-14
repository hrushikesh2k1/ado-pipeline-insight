# ADO Pipeline Insight.

ADO Pipeline Insight analyzes Azure DevOps pipeline performance, stage and task duration, failures, retries, queue time, trends and AI generated optimization recommendations.

## Target architecture

React + TypeScript frontend -> FastAPI backend -> Azure SQL

Azure DevOps -> Azure Function ingestion -> Azure SQL

FastAPI or background analysis -> structured metrics -> Azure OpenAI -> validated recommendations -> Azure SQL

The browser never connects directly to Azure SQL and never receives Azure DevOps credentials.

## New application

`frontend/` contains the React application.

`backend/` contains the FastAPI application, service layer, repository layer and API contracts.

`functions/` contains Azure Functions for ingestion and recommendation workloads.

`sql/` contains the Azure SQL schema and analytical views.

`infra/` contains Azure infrastructure definitions.

`web_dashboard/` is the legacy Flask dashboard retained temporarily as a reference during migration.

## Local development

### Backend

Create a Python 3.11 environment and install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
```

Set `SQL_CONNECTION_STRING` in `backend/.env` or the process environment. The connection string should reference ODBC Driver 18 or 17 for SQL Server.

Start FastAPI:

```powershell
uvicorn backend.app.main:app --reload --port 8000
```

API documentation is available at `http://127.0.0.1:8000/docs`.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

Vite proxies `/api` requests to FastAPI during local development.

### Production style single process

Build React first:

```powershell
cd frontend
npm install
npm run build
cd ..
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

FastAPI serves the generated React application when `frontend/dist` exists.

## Configuration

Required backend setting:

`SQL_CONNECTION_STRING`

Optional:

`CORS_ORIGINS`
`MIN_HISTORY_RUNS`

Azure OpenAI and Azure DevOps credentials stay in the existing Function configuration for ingestion and AI workloads. They should use Key Vault and Managed Identity in Azure.

## Validation order

1. `GET /api/v1/health`
2. `GET /api/v1/options`
3. `GET /api/v1/summary`
4. `GET /api/v1/trends`
5. `GET /api/v1/runs`
6. React selectors
7. Pipeline charts
8. AI recommendations
9. Azure Function ingestion
10. Full end-to-end deployment


## Historical Azure DevOps backfill

The dashboard should not depend on service-hook uptime for historical accuracy. Use `scripts/backfill_ado_history.py` to pull completed Azure DevOps builds and their timelines directly into Azure SQL. Set `SQL_CONNECTION_STRING`, `ADO_ORGANIZATION`, `ADO_PROJECT`, and `ADO_PAT`. Optionally set `ADO_PIPELINE_ID` and `ADO_DAYS`. The operation is idempotent because runs and timeline records are upserted by their Azure DevOps IDs.

The ingestion path stores Azure DevOps build `startTime` and `finishTime` as the canonical pipeline run boundaries. Stage, job, and task durations continue to come from the Azure DevOps timeline. This prevents the dashboard from using the first timeline record as the pipeline duration.

## V7 self-service ADO connection

V7 adds the self-service connection flow:

1. Enter an Azure DevOps organization and PAT in the dashboard.
2. The FastAPI backend validates the PAT and discovers projects and pipelines.
3. Select the project, pipeline and history window.
4. FastAPI sends the scoped ingestion request to the Azure Function.
5. The Azure Function reads completed runs and timelines from Azure DevOps and upserts Stage -> Job -> Task telemetry into Azure SQL.
6. The existing dashboard and AI analysis operate on that measured telemetry.

The PAT is accepted only for the connection/ingestion request and is not written to SQL or application data. For production ongoing webhook ingestion, use Key Vault via `KEY_VAULT_URL` and `ADO_PAT_SECRET_NAME`.

Set `INGEST_FUNCTION_URL` in the backend environment to the deployed `ingest_pipeline` function endpoint.

### Multiple Azure DevOps organizations

The backend and Azure Functions resolve the PAT by organization without exposing credentials to the browser. Set `ADO_PAT_SECRET_TEMPLATE` in the Azure Function App and backend environment to a Key Vault secret naming convention, for example:

```text
ADO_PAT_SECRET_TEMPLATE=ado-pat-{organization}
```

For organization `cicd-analysis`, the resolver reads the Key Vault secret `ado-pat-cicd-analysis`. Organization names are normalized to lowercase and hyphen-separated. Grant the Function App and FastAPI host managed identities permission to read every organization secret. For local development without `KEY_VAULT_URL`, `ADO_PAT` remains the local fallback.


## V7 telemetry correction

V7 treats a successful Azure DevOps timeline as the source of truth for a run. Re-ingestion replaces stale child stage/job/task telemetry, updates previously degraded runs to complete, and removes fallback child records. This fixes the earlier condition where existing 0-5 second child durations could survive a real ADO ingestion.

After deploying the Function, select the pipeline in the dashboard and use Ingest History. The dashboard queries Azure SQL again after ingestion. Use scripts/verify_ingested_run.py <run_id> to compare the normalized ADO timeline with stored SQL records.

## Clean V8 end-to-end setup

The application has three processes in local development:

1. React frontend on port 5173.
2. FastAPI backend on port 8000.
3. Azure Functions Core Tools on port 7071.

The React dashboard sends the selected ADO organization, project, pipeline and PAT to FastAPI over HTTPS. FastAPI forwards that scoped request to the Azure Function. The Function calls Azure DevOps, reads the completed build timeline, and writes authoritative Stage -> Job -> Task telemetry to Azure SQL.

### Required FastAPI setting

Set `INGEST_FUNCTION_URL` in `.env` to the Azure Function `ingest_pipeline` endpoint. For Azure use the HTTPS function URL with its function key. If this value is missing, `/api/v1/ado/ingest` intentionally returns HTTP 503 instead of silently pretending ingestion succeeded.

### Clean start

1. Execute `sql/reset_data.sql` in Azure SQL Query Editor.
2. Configure `.env` with the real SQL connection string and Azure OpenAI values. Do not commit secrets.
3. Set `INGEST_FUNCTION_URL` to the deployed `ingest_pipeline` endpoint.
4. Start FastAPI.
5. Start the frontend.
6. Use Connect & Discover, select project and pipeline, then click Ingest History.
7. Run `scripts/verify_ingested_run.py <run_id>` to compare ADO timeline records with SQL.

### Telemetry correctness

A real Azure DevOps timeline is authoritative. Re-ingestion replaces stale Stage/Job/Task rows for the run, skips fallback records when a real timeline is available, and writes the Azure DevOps build startTime and finishTime as the pipeline run boundaries.
