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
The canonical SQL schema includes `pipeline_runs.build_number`. A fresh database does not require an additional migration script for this column.

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

The dashboard sends the PAT over HTTPS to the FastAPI backend for the connection and selected historical ingestion. The PAT is kept only in browser memory and request memory and is never persisted by the application. For ongoing server-side webhook ingestion, the backend and Azure Functions resolve the PAT by organization from Key Vault. Set `ADO_PAT_SECRET_TEMPLATE` in the Azure Function App and backend environment to a Key Vault secret naming convention, for example:

```text
ADO_PAT_SECRET_TEMPLATE=ado-pat-{organization}
```

For organization `cicd-analysis`, the resolver reads the Key Vault secret `ado-pat-cicd-analysis`. Organization names are normalized to lowercase and hyphen-separated. Grant the Function App and FastAPI host managed identities permission to read every organization secret. For local development without `KEY_VAULT_URL`, `ADO_PAT` remains the local fallback.


## Sprint planning team roster

Sprint Planning initially lists available people across all teams in the selected Azure DevOps project,
including expanded team groups, with duplicate users shown only once. Project/team read permissions
are required; expanding groups also requires identity read access. Incomplete discovery is shown as a warning.
Use **Edit team roster** to search for people, select the members to plan for, and **Save team roster**.
The saved selection is restored separately for each organization, project and team in the same browser.
It does not change Azure DevOps team membership or synchronize between browsers.

**Refresh available people** reloads available members without resetting the saved roster, capacity,
leave or planning settings. Newly discovered people can be selected in **Edit team roster**; saved
members remain selected even if a refresh no longer returns them. The **In plan** checkbox temporarily
includes or excludes a saved member from a plan without changing the saved roster. When a roster has
been saved, people added manually must also be selected in **Edit team roster** to appear in the table.
Opening the editor or refreshing people invalidates the current plan; generate a new plan afterward.

The **Sprints and rules** section contains only the sprint, a display-only story count reference and active-days
threshold. Planning uses the standard work item types supplied by setup, with no additional backlog
tag or area filter. The selected team's normal scope still applies. There is no per-person area
dropdown: everyone is eligible for any area within that scope, including people with previously saved
personal area restrictions. Saved roster preferences are unchanged; old planning-only Days/PTO values
are no longer used.

### Capacity and individual velocity

The **Capacity tab** is the shared source for Working Days, Days Off (PTO) and Total Capacity.
Azure DevOps iteration capacities are read from the response's `teamMembers` collection
(with compatibility for `value`-wrapped responses); a valid empty collection means no members
are configured for that team and sprint.
Planning shows these values read-only; change them in Capacity for the relevant team and sprint,
then use **Refresh Capacity data**. Working Days use the same inclusive weekdays as Capacity;
available days are `max(0, working days - PTO)` and hours are available days multiplied by the
person's Capacity/Day. Zero values remain zero. Reports reuse Capacity totals instead of
assuming every person has the same number of hours. People without an entry must be configured
in Capacity; a roster entry alone does not imply eight hours/day.

Capacity overrides are saved locally, scoped by organization, project, team ID and sprint ID.
Existing Capacity-tab settings remain readable. Overrides are shared with planning in the same
browser, not written to Azure DevOps or synchronized across browsers. Missing or unreadable data
is reported rather than replaced with default working days, hours or points.
If ADO Capacity cannot be read, saved Capacity-tab entries can still be used with valid sprint dates;
people without a saved entry remain unavailable.

Each person's automatic assignment budget is:

`previous completed points × upcoming available days ÷ previous available days`

The baseline is the most recent **completed** team sprint before the planned sprint. Completion
state, story points and owner are read as of that sprint's final UTC day, so later reassignments
do not change attribution. Only the process's Completed category counts, not merely Resolved or
Removed; unavailable or unmapped process states pause the forecast rather than guessing completion.
Capacity settings for both sprints must be present. This is a one-sprint baseline;
unusual incidents or blocking can make it noisy. A rolling average is not implemented yet.

Existing commitments remain assigned. Carryover is **assumed 50% complete**, reserving half its
original points; existing target-sprint stories and new backlog stories reserve full points.
This does not change ADO story points or record actual progress. The UI distinguishes original
story size from remaining reserved points. New automatic assignments must fit the remaining
forecast exactly; there is no 15% overage or fixed eight-point budget, and the story-count view
does not impose a separate story-count limit.

Unknown history, missing point estimates on completed or existing work, missing Capacity entries,
or zero previous availability pause automatic new assignment for the affected person. Zero upcoming
availability gives a zero budget. Unestimated backlog work stays available for manual planning.
Manual dropdown moves remain possible and update reserved totals and warnings immediately;
overriding a forecast is explicit. No multiple-active-work-item flag is added.

Story comments in the sprint plan are hidden by default. Each story has **View Recent Comments**
to reveal its latest three comments (or fewer if fewer exist), displayed oldest first.
Use **Hide Recent Comments** to collapse them again. Comments not included in the plan are loaded
from Azure DevOps only when opened; read failures are shown explicitly and can be retried.

**Look at these first** has an **All / Blocked / Active too long** display filter and a visible count.
Stories with both flags appear in either filtered view. Filtering does not change workloads, totals
or commit assignments. A newly generated plan starts with **All** selected.

**Team Workload Swimlanes** uses two panes (stacked on smaller screens):

- **Team workloads** shows carryovers, existing commitments and automatically planned work per person.
- **Available backlog** shows all remaining candidates read by the planner, including work left after
  capacity is filled, not just the legacy truncated "Not placed" list. The existing limit of 300
  backlog candidates per plan still applies.

Sprint Goal matching treats comma-, semicolon-, newline-, "and"- or "or"-separated entries as topics.
Multiword topics must match as a phrase within one title, plain-text description or tag; isolated
words from different fields do not combine into a match. Single-word topics must occur in a title
or tag, not merely somewhere in a description. Generic-only topics such as "high" or "data" do not
qualify. Matching ignores case, punctuation, common linking/action words and high/low modifiers;
"cost" and "costs" are equivalent. For example, `cost, high data ingestion` matches the cost topic
or the data-ingestion phrase, not "high" or "data" alone.

Matching items are highlighted and ranked by distinct matched topics, with ties retaining backlog
order. Each match shows its topic, source field and an evidence excerpt. No matches is a valid
result; unrelated items remain available without highlights. This is conservative text matching,
not semantic or AI assessment, so synonyms and differently worded goals may require revised topics.
Automatic assignment order is unchanged. With no goal, original backlog order is retained.

Select a roster member from a backlog item's assignee dropdown to move it immediately into that
person's workload and update totals, capacity warnings and the draft commit assignments. Selecting
**(Not in plan)** in a workload returns the item to the available pane. These are local draft changes;
only **Commit to Azure DevOps** writes assignments and the target iteration to Azure DevOps.

## V7 telemetry correction

V7 treats a successful Azure DevOps timeline as the source of truth for a run. Re-ingestion replaces stale child stage/job/task telemetry, updates previously degraded runs to complete, and removes fallback child records. This fixes the earlier condition where existing 0-5 second child durations could survive a real ADO ingestion.

After deploying the Function, select the pipeline in the dashboard and use Ingest History. The dashboard queries Azure SQL again after ingestion. Use scripts/verify_ingested_run.py <run_id> to compare the normalized ADO timeline with stored SQL records.

## Clean V8 end-to-end setup

The application has three processes in local development:

1. React frontend on port 5173.
2. FastAPI backend on port 8000.
3. Azure Functions Core Tools on port 7071.

The React dashboard sends the selected ADO organization, project, pipeline and PAT to FastAPI over HTTPS. FastAPI uses the PAT for discovery and forwards the same scoped request to the Azure Function for historical ingestion. The Function calls Azure DevOps, reads the completed build timeline, and writes authoritative Stage -> Job -> Task telemetry to Azure SQL. The PAT is never written to Azure SQL or application data.

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

## Versioning and releases

The version number lives in one file: `VERSION` (for example `1.4.0`). Nothing else hardcodes it; the app header and
`GET /api/v1/version` read it at runtime.

```bash
python scripts/bump_version.py patch    # bug fix:   1.4.0 -> 1.4.1
python scripts/bump_version.py minor    # feature:   1.4.0 -> 1.5.0
python scripts/bump_version.py major    # breaking:  1.4.0 -> 2.0.0
```

Release steps: bump the version, add a `CHANGELOG.md` entry, commit, build the frontend (`cd frontend && npm run build`),
then `python scripts/package_webapp.py` (stamps commit and build time into the zip) and
`az webapp deploy -g <resource-group> -n <app-name> --src-path webapp-deploy.zip --type zip`.
