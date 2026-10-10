# Sprint Deliverables

Azure Boards now has a **Deliverables** tab next to Milestone. Select a team and sprint in the existing selectors.

An August-assigned work item first completed during September appears in September even if its assigned iteration still says August. August's deliverables exclude it. Milestone continues to describe the planned scope.

## Calculation

- Completion means entering a state whose Azure DevOps category is `Completed`, including custom state names. `Resolved` and `Removed` are not treated as completion.
- The report reads revision history without restricting discovery to the assigned iteration or current area. Current project membership is required for candidate discovery.
- The completion revision supplies the owner, title, area and assigned iteration. The selected team's **current** area configuration is used to check the historical completion area.
- Sprint dates use UTC calendar days, with the finish day fully included. State and effort are taken from the last revision before the next day begins. Later owner changes and later effort changes do not rewrite historical attribution.
- Non-task work items and completed tasks have separate counts. Only the cumulative `Completed Work` of completed tasks is summed, once per task. Parent effort is displayed for context and excluded from totals. Child task owners receive their own task contributions.
- These values are **recorded effort on completed tasks**, not a time sheet or hours worked during this sprint. Effort spent on a still-open task is outside this delivery report.
- Missing task effort is flagged separately; a recorded zero is valid.
- Items reopened before sprint end appear but are excluded from delivery totals. Items reopened after sprint end retain the historical delivery and are flagged. A completion after any pre-period completion is labeled `recompleted` and excluded from new-delivery and effort totals, conservatively preventing duplicate credit. Multiple closures inside the period are counted once.
- Available capacity uses Azure DevOps daily capacity, configured team working days and the union of individual and team days off. It is separate from effort. Missing capacity is shown as unavailable rather than assuming an eight-hour day.
- Open or future sprints are marked provisional. Team membership and configuration are current; this is a reconstructed report, not a saved immutable sprint-close snapshot.

## Copy and email

Copy Report and Report Preview include the full team report, regardless of view filters. Email addresses come exclusively from the selected team's current Azure DevOps membership; the visible `To` list is a preview. Missing email addresses or an unsuccessful membership lookup disable email drafting.

Open Outlook Draft uses `mailto:` and opens the computer's default mail app. Outlook must be configured as that default. Short reports populate recipients, subject and body. For a long report, the entire body is copied to the clipboard, the draft has recipients and subject prefilled, and the page tells the user to paste the body. Clipboard failures show a selectable full report preview. Nothing is sent automatically.

## API

`GET /api/v1/ado/sprints/deliverables?organization=...&project=...&team=...&iteration_id=...`

The optional caller PAT travels in `X-ADO-PAT`, not in the URL. Existing authentication and organization credential rules apply. The PAT needs work-item, iteration and team membership read permissions. No Azure DevOps items, states, hours or iterations are modified.

Missing dates, unknown team areas or unknown completed state definitions reject the report. Required history read failures return 503 rather than partial totals. Candidate IDs and revision/member lists are paginated. History reads have bounded concurrency; large projects may take time. The implementation currently scans all project items changed since sprint start (up to 50,000). Deleted items are unavailable. A persistent indexed event store would be needed for larger historical projects and immutable reports.

## Deployment

This feature is based on `master` at `8d0a80d`, which contains the live Azure Boards functionality. The older `main` branch is not the source for this change. Existing GitHub workflows target Function Apps; they do not deploy this web app.

Build the frontend, then run `python scripts/package_webapp.py`. The resulting `webapp-deploy.zip` uses the repository's existing App Service package layout.

Deploy with your authenticated Azure CLI:

```powershell
az webapp deploy --resource-group <resource-group> --name app-ado-pipeline-insight-test --src-path webapp-deploy.zip --type zip
```

Use the resource group that actually owns the test web app. Keep the existing App Service environment settings and startup configuration. Verify the version endpoint and the Deliverables tab with real Azure DevOps data after deployment, particularly an item assigned in August and closed in September. Test the Outlook draft on a Windows machine with Outlook configured as its mail handler.
