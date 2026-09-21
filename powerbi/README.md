# Power BI Dashboard

Connect Power BI Desktop to Azure SQL using **Get data > SQL Server**. Use the server name `<server>.database.windows.net`, database `ado-pipeline-insight`, and Microsoft Entra ID authentication. Load these views:

- `dbo.vw_pipeline_duration_trend` as Import, with a daily scheduled refresh.
- `dbo.vw_task_duration_trend` as Import, with a daily scheduled refresh.
- `dbo.vw_flaky_jobs` and `dbo.vw_flaky_tasks` as Import.
- `dbo.vw_latest_ai_recommendations` as DirectQuery, so it can display newly generated findings immediately.

Create an **Overview** page with pipeline/project slicers, a duration trend line, high-severity finding card, and flaky task table. Create a **Pipeline Drilldown** page with a stage/job/task matrix, duration trend, retry rate, and `% of parent duration` bar chart. Create an **AI Recommendations** page with category and severity slicers plus stage/task/recommendation/evidence columns.

## Get Recommendations button

1. Add the **Power Automate for Power BI** visual to Pipeline Drilldown and bind `pipeline_id` from the selected pipeline.
2. Create a flow with trigger **Power BI button clicked** and an HTTP POST action to `https://<function-app>.azurewebsites.net/api/get_recommendations?code=<function-key>`.
3. Send `{ "organization": "<org>", "project": "<project>", "pipeline_id": <selected ID> }` as JSON. Store the URL/key in a Power Automate environment variable or Azure Key Vault-backed connector configuration.
4. Configure the AI-recommendations visual for DirectQuery and refresh the visual after the flow returns.

The HTTP action normally requires a Power Automate Premium license. Without it, call the same endpoint from Postman or curl:

```powershell
Invoke-RestMethod -Method Post -Uri 'https://<function-app>.azurewebsites.net/api/get_recommendations?code=<key>' -ContentType 'application/json' -Body '{"organization":"<org>","project":"<project>","pipeline_id":123}'
```