# ADO Pipeline Insight

ADO Pipeline Insight stores Azure DevOps build timing history in Azure SQL, then generates Azure OpenAI recommendations only when someone requests them for one pipeline. The code has two HTTP Functions: `ingest_run` receives Azure DevOps Service Hooks; `get_recommendations` is the on-demand endpoint used from Power BI/Power Automate.

## Local setup

Install Python 3.11, Azure Functions Core Tools, Azurite, and the ODBC Driver 18 for SQL Server. Create a local SQL database, run `sql/schema.sql` then `sql/views.sql`, and copy `functions/local.settings.example.json` to `functions/local.settings.json`. Fill only local development values; do not commit that file. Install and run:

```powershell
python -m pip install -r requirements-dev.txt
cd functions
func start
```

Run the tests with `python -m pytest -q` from the repository root.

## Azure deployment

Deploy `infra/main.bicep`, then run both SQL scripts against the new database. Put the organization-level Azure DevOps PAT in Key Vault as `ado-pat`. The PAT needs Build (Read), Release (Read), and Project and Team (Read). Set `SQL_CONNECTION_STRING` as a Key Vault reference or managed-identity database connection after creating a least-privilege data read/write user for the Function identity. Azure OpenAI is intentionally referenced by endpoint/deployment rather than provisioned.

Retrieve a function key with `az functionapp keys list --name <app> --resource-group <rg>`; use it in the Power Automate HTTP endpoint. Keep CORS restricted: Power Automate calls the Function server-side and normally needs no browser CORS allowance. Azure AD authentication may replace the function key when an app registration and supported Power Automate HTTP connector are available.

## Azure DevOps Service Hook

In Azure DevOps, open **Organization settings > Service hooks > Create subscription**. Select **Web Hooks**, choose **Build completed** (or **Run stage state changed** for YAML pipelines if available), scope it to the intended project or repeat per project, and set the consumer URL to `https://<app>.azurewebsites.net/api/ingest_run?code=<function-key>`. Use the Test action once, then confirm Application Insights has an `ingest_run completed` event.

See [powerbi/README.md](powerbi/README.md) for the dashboard build and on-demand button flow.