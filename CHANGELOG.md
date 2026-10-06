# Changelog

All notable changes to ADO Pipeline Insight. Versions follow [Semantic Versioning](https://semver.org):
**MAJOR** = breaking change, **MINOR** = new feature, **PATCH** = bug fix only.
The number lives in the `VERSION` file; change it with `python scripts/bump_version.py minor|patch|major`.

## [1.9.0] - 2026-10-06

### Changed
- **The AI PR review reads the real changes, file by file.** Each changed file is compared with its earlier version and the
  reviewer is shown the diff with line numbers (`+` added or changed, `-` removed), so it can tell new code from old. Up to 20
  files are reviewed per pull request, Python and PowerShell first; a large file shows its changed parts with the lines around
  them. Every file that is not reviewed is listed with the reason (documentation, deleted, lock or generated file, too large,
  over the limit). Before, the review read the first 4 source files, 200 lines each, as whole files with no diff.
- **Python and PowerShell guidance.** PowerShell files (`.ps1`, `.psm1`, `.psd1`) are now read at all. The PowerShell guidance
  names PSScriptAnalyzer rules and the slow patterns Microsoft documents (`+=` on arrays and strings in loops, repeated
  `Where-Object` filtering instead of a hashtable lookup, `Write-Host`); the Python guidance covers quadratic loops, statuses
  that should be an Enum, annotations narrower than what is returned, substring parsing, averages of averages, missing
  timeouts, HTML built from data and more. Other languages get a general review.
- **Alerts written as ARM templates are reviewed as alerts.** A `.json` file is reviewed when its content is an ARM template
  (other JSON, such as `package.json`, is skipped with that reason, and its earlier version is not even fetched), and `.kql`
  files are read. For an alert template the reviewer is also given each alert in plain words (when it fires, how often, over
  what window, who is notified, with its query laid out over several lines) and a list of exactly what changed: threshold,
  window, frequency, severity, action groups, the query before and after, new and removed alerts. This uses the same reader as
  IRP Studio, which now also reads log alerts in the older `2018-04-16` format (query in `source`, timing in `schedule`, severity
  and action group in `action`) next to the newer one, as Microsoft documents it. The long query line in the JSON is no longer cut. The guidance follows Microsoft's `scheduledQueryRules` reference
  and alert documentation: changes to when an alert fires, `minFailingPeriodsToAlert` above `numberOfEvaluationPeriods`,
  `overrideQueryTimeRange`, a log alert meant to detect a lack of data, a disabled alert, no action group, `autoMitigate` off,
  `skipQueryValidation`, metric alerts whose conditions must all be true, query mistakes, and secrets that are not `securestring`.
- **Short, concrete findings.** Each finding names the exact input or situation that goes wrong, what happens, and what to
  change, and may carry a replacement for the exact lines it points at. The AI may return no findings.
- **The author's explanation is read.** The reviewer and the second check are given the pull request description (the
  checklist lines, images and HTML comments are taken out, since the code reads the checklist itself; up to 8,000 characters
  are kept) and are told not to report something the description, a comment in the code or the alert's own description says
  is intended unless they can show a case where it gives a wrong result. Before, only the first 1,200 characters were sent, so
  an explanation further down never reached the AI.
- **Every finding is checked before it is shown.** In code: the file must be in the pull request, the line must be a line the
  pull request changed, and a suggested replacement is kept only when every line it replaces was changed. Then a second AI call
  reads each finding against the code, the description and the existing comments, and removes the ones it cannot confirm,
  the ones that only say something "could" or "may" go wrong without a concrete case, and the ones that repeat an earlier
  finding (the repeat is merged into the first: "The same applies at line N."). What was removed, and why, is listed in the
  review. A finding the second check could not run for is marked "not double-checked".
- **The verdict, the scorecard and the summary are worked out from the findings,** not written by the AI. The verdict reads
  "No issues found", "Suggestions" or "Changes suggested" (a review of code changes does not approve a pull request), and a
  scorecard row with no finding says "No findings" instead of "Excellent".
- **Existing pull request comments are read.** The AI is told what people already said on each file and on the pull request
  as a whole, with the last reply of each thread (so a point the author deferred is not raised again), and does not repeat it.
  A finding that matches an existing comment, on the same lines or, judged by the second check, anywhere, is marked "Already
  raised by <name> (resolved)", and findings people already resolved do not count toward the verdict.
- **The PR checklist is checked against the pull request.** Ticked boxes about the changelog, tests created and a linked work
  item are compared with the changed files and the linked work items; the run linked in the description is compared with the
  newest run of the same pipeline on the source branch. Everything else on the checklist is listed as something that cannot be
  verified here. The AI also names substantial changes the description does not mention.
- **A review knows which commit it was made at.** After new commits the page offers "Review again (new commits)", and the
  review has a **Review again** button. The review shows the commit and the push it covers.
- **Copy** gives text ready for an Azure DevOps comment, with a suggestion block when there is a replacement, and the review says
  which lines to place it on so that **Apply Change** replaces exactly those lines. Comments are still shown on screen only and
  are not posted to Azure DevOps.
- The review says plainly that it reads code changes only and cannot judge how a result looks or behaves when run.

### Fixed
- **JSON files were skipped as data, so an alert written as an ARM template was never reviewed** ("Reviewed 0 of 1 changed
  files"). See "Alerts written as ARM templates are reviewed as alerts" above.
- **A log alert in the older `2018-04-16` format was read as having no window, no query, no severity and no action group,**
  so the reviewer was told "nobody is notified" and "no alert rule changed" for an alert that had an action group and a changed
  query. IRP Studio's Analyze had the same gap for such templates. A flag written as the text `"true"` or `"false"` (which that
  format requires) was not read as a flag either.
- **The AI never saw the author's explanation** when it was past the first 1,200 characters of the description, so it reported
  deliberate choices (a two-minute delay for logs to arrive, a window raised to fit the query's look-back) as mistakes.
- **When nothing could be reviewed the summary said "(none)" and "see the file list".** It now names the files that were skipped
  and the reason for each. The limit of 20 files counts only the files that are reviewed, not the ones skipped.
- **A checklist item with a link showed the raw link** (`[Alert Inventory wiki] (https://...)`); it now shows the link's words.
- **No more canned review.** When Azure OpenAI was not configured, or the call failed for any reason, a built-in fallback
  returned fixed advice about HTML report generation, rated performance "EXCELLENT" for every pull request and said it adhered
  to branch conventions, with nothing on screen to say the AI had not been used. Now the request fails with a clear message
  (HTTP 503 when the AI is not configured) and nothing is made up. If the AI fails for some files only, those files are listed
  as not reviewed; if it fails for all of them, there is no review (HTTP 502).
- **A review was made even when the pull request could not be read.** After an Azure DevOps failure that was not an HTTP error
  (a network failure, for example) the error was only logged and the AI was asked to review an empty pull request. The pull
  request must now be readable; a missing pull request is a 404, one with no pushes or no file changes a 422.
- **The review used the server's own Azure DevOps token for any organization** when the caller sent none. It now follows the same
  rule as the other pull request routes: the server's token only for allow-listed organizations.
- **Only the first 100 changed files were read, and the earlier version of a file was never fetched** (the file fetch the old
  review fell back to did not send the file path). All changes are read, page by page.
- Test files were recognised by the word "test" anywhere in the path (`latest.py`, `contest.md`); they are now recognised by
  file and folder name.

### Notes
- No new dependency, table or setting. The token needs Code (Read). If it lacks the read scope for the existing comments, the
  linked work items or the builds, the review still runs and says what it could not read.
- A review looks at no more than 100 files; the rest are listed as not examined.
- A review makes one AI call per file, a second call for each file that has findings, and one for the description, five at a
  time. It stops starting new files after 170 seconds (Azure App Service ends a request after 230) and lists the files it did not
  reach.
- `POST /api/v1/ado/pullrequests/review` returns `method`, `source_commit`, `iterations`, `files`, `checklist`, `notes` and
  `scope_note`; each comment gains `end_line`, `language`, `existing_thread`, `existing_status` and `verified`; the verdict can
  be `NOT_REVIEWED`. `GET /api/v1/ado/pullrequests` returns `last_source_commit`.
- The unused `PullRequestReviewComment` and `PullRequestReviewResponse` classes were removed from `core/models.py`.

## [1.8.1] - 2026-10-06

Accuracy fixes for the IRP writer, found by testing 1.8.0 on a real AKS memory alert in Azure Government.

### Fixed
- **The alert query is no longer repeated in every step.** It is shown once, in Prerequisites, as a code block. A step that
  runs it says "the alert query (see Prerequisites)", and a step that adds to it shows only what is added ("with this added at
  the end: `| where ...`"). The writer refers to the query by a reference that the code expands, so the query can no longer be
  retyped with a mistake in it; a query the writer retyped anyway is turned back into the reference. QA still sees the full
  query in the command list.
- **A name taken from part of the alert's scope is no longer used as a resource name.** The scope of a log alert is its Log
  Analytics workspace, not the resource it watches, and the writer was using part of the workspace name as the AKS cluster
  name. The writer is told so, and a name in a command that is only part of the scope's name (or its resource group) is flagged
  in the checklist.
- **One spelling for each `<value>`.** `<DeploymentName>` and `<deployment_name>` in different rows of one IRP are now written
  one way, so Prerequisites lists each blank once.
- **Preparation that was missing.** Prerequisites now say how to connect `kubectl` (`az aks get-credentials`) and which roles
  the changes need whenever the steps use `kubectl` or `az aks`, and, when the alert is in Azure Government, to run
  `az cloud set --name AzureUSGovernment` and sign in again (Microsoft documents both).
- **The closing row says how long the alert can take to resolve** after a fix, from how often the template evaluates it (or
  that it does not resolve by itself when `autoMitigate` is off), so a late resolution is not taken for a failed fix.
- **Causes that are the same fix, and causes that only restate the alert, are caught.** A cause must not repeat the symptom in
  the alert name, and a fix must change what the alert measures (adding nodes does not change memory used per container limit).
- "Queries are well formed" is now "Quotes and brackets balance in queries". It never proved that a query runs, and the new
  name says what it checks.

### Added
- **A second review of every IRP.** After the cases are written, a second model call reads each fix against what the alert
  measures. A case it doubts is rewritten once with the reason, then reviewed again. A doubt that remains is reported in the
  checklist with the reviewer's reason; if the review itself fails, the checklist says "not checked" instead of passing.
- **Checklist:** *Each fix changes what the alert measures*, *The root causes are distinct*, *Names are not guessed from the
  alert's scope*, *Prerequisites list a role that can make the changes*, and *Queries written by the AI, not copied from the
  alert* (information only).
- **Commands for QA** show where each query came from ("The alert's own query", "The alert query, with operators added",
  "Written by the AI: test first"), and the queries the AI wrote are listed right after the commands with a known problem.
- **Analyze the alert** shows how far back the query looks next to the alert's window ("looks back 10m (the alert window is
  10 minutes)"), so a mismatch is visible before the IRP is written.

### Changed
- Writing an IRP makes one more model call for the review, and one per case that is rewritten.

### Notes
- No new endpoint, setting, table or dependency. The `commands` in the `/api/v1/irp/generate` response gain an `origin` field.

## [1.8.0] - 2026-10-06

### Added
- **IRP Studio reads the alert's own ARM template and KQL query.** Paste or upload the alert's ARM template (JSON; log alerts
  `Microsoft.Insights/scheduledQueryRules` and metric alerts `Microsoft.Insights/metricAlerts`) and, optionally, its KQL
  query. The alert's name, type, condition, window, frequency, severity, scope and action groups are read from the template,
  ARM expressions (`parameters()`, `variables()`, `concat()`, `format()`, `resourceId()`, nested deployments) are resolved
  where the template gives the values, and a value it does not give is shown as a `<placeholder>`, never invented. The query
  is read for the tables, filters, aggregates and output columns it uses.
- **Analyze the alert.** A new card shows what was read from the alert, in words ("the number of rows returned by the alert
  query is greater than 0, measured over 10 minutes and evaluated every 5 minutes"), lists anything that could not be read, and
  proposes the root causes of the alert from its query or metric. The causes can be edited, removed and added before the IRP is
  written. The step is optional: Generate does it itself.
- **The IRP is written case by case.** One call proposes the causes, one writes the Alert Details values, the Prerequisites
  and the opening and closing rows, and one focused call writes the row of each cause, which must say how to confirm it, fix it,
  verify the fix and what to do if the fix fails. The table is then built in code: the approval step is put before every change,
  every command goes in a code span with where to run it, the Root Cause cell is made from the same causes as the rows, and the
  Severity row comes from the ARM template. A row that is missing a fix or a verification is asked for once more.
- **Quality checklist.** Every IRP written this way is checked against the IRP authoring checklist: every cause has a check, a
  fix, a verification and a fallback; every command says where to run it; every row says what to expect; approval comes before
  every change; every `<value>` is listed in Prerequisites (any the writer left out are added); a step reads the table the alert
  query reads; the IRP is about 10 rows long; queries are well formed. The result is shown beside the IRP, not inside it.
- **Known-wrong commands.** A list of commands and queries that are known to be wrong (it starts with the VPN Gateway log
  category `VpnGatewayDiagnosticLog`, which Microsoft does not document, and reading a shared key from `vpn-connection show`),
  each with its documentation. It is checked in every IRP and can be extended whenever QA finds a command that does not work.
- **Commands for QA to test.** Every command in the IRP is listed under it, with its language, where it runs and an
  "Unverified" mark (shown in the app only, not in the IRP document). Commands with a known problem come first, and every
  command can be copied one by one or all together.
- **API.** `POST /api/v1/irp/analyze`. `/api/v1/irp/generate` accepts `alert_kql` and `cases`, and returns `method`
  (`case-by-case`, `single-pass` or `built-in`), `facts`, `cases`, `scorecard` and `commands`.

### Changed
- Without an ARM template or a query the IRP is written in one pass, as before. If the case-by-case writer fails, the one-pass
  writer takes over and the page says so.
- The Alert Name, Alert Output Columns, Description and Trigger Condition boxes start empty (they were filled with a VPN
  example, which was sent to the AI as context for every alert), and so does the ARM box (it held a gateway, not an alert).
  Analyzing a template fills the alert name in when nothing is typed. A blank trigger condition is no longer sent to the AI as
  if it were a fact about the alert.
- Writing an IRP this way makes several model calls (one for the causes, one for the frame, one per cause), so it takes longer
  than the one-pass writer.

### Fixed
- **IRP requests larger than 64 KB were refused** ("Request body too large"). The approved example, the template and the ARM
  template together can pass that, so the IRP routes now accept up to 600 KB (every other route keeps 64 KB). This also makes
  the 1.6.0 note about example and template sizes true.

### Notes
- Nothing new is stored and there is no new dependency. Commands are shown as unverified until QA has tested them.

## [1.7.0] - 2026-10-05

### Added
- **Work Item Insights.** A new page that shows what a team's work items are about, who closes them, where bugs come
  from and how many alerts exist. It works for any team or project: pick a **Team** (its area paths), a **Tag** (for
  example `monitoring`), or both, or neither for the whole project. It reads everything still open, whatever its age,
  plus everything that closed in the last 6 months. Which states mean "closed" comes from Azure DevOps itself (the
  state categories of each work item type), so it does not depend on one team's process. The team and tag are
  remembered per organization and project.
  1. **Work items closed per sprint**, one colour per person, with filters for people and work item types.
  2. **Work items by area** (for example VPN, login, AKS restarts), split into backlog, active and closed.
  3. **Bugs raised by area**, by area and over time. The bug types can be chosen; open bugs raised before the
     6 months are counted in a note instead of the charts.
  4. **Alert scope.** Upload your alert inventory (`.xlsx`, `.csv`, `.tsv`, `.md` or `.txt`, up to 5 MB, with a header
     row) to see how many alerts exist, grouped by a column such as Service, next to the work items that were raised to
     build new alerts. The alert-name and grouping columns can be changed after the upload.
  Clicking any bar lists the work items behind it, with links to Azure DevOps.
- **Areas come from the AI reading each work item's title and description.** The AI proposes the list of areas once
  from a spread of the work items and the list is saved; every work item is then put in exactly one of those areas.
  Only new or changed work items are sent to the AI on later refreshes, so the counts stay stable and a refresh is
  cheap. **Regroup areas** asks for a new list. The same pass decides whether a work item asks for a new alert, but only
  when an alert inventory has been uploaded. Without Azure OpenAI the areas follow the Azure DevOps Area Path and the
  page says so. Work items the AI could not answer for are shown as "Not grouped", never guessed.
- **A refresh runs in the background** and reports its progress; the saved result opens straight away on the next visit.
- **API endpoints** `/api/v1/insights/work-items` (read), `.../refresh`, `.../status` and `.../inventory` (upload and
  remove).

### Changed
- The request size guard can give a named route a larger limit. Only the alert inventory upload has one (the file is
  sent inside the request); every other route keeps the 64 KB limit.

### Notes
- It needs a personal access token with the **Work Items: Read** scope. Azure OpenAI is optional.
- It saves the work items' id, type, title, state, assignee, dates, sprint, area path and area (not their descriptions)
  in a new table, `dbo.wi_insight_scopes`, which is created in the app's database on first use, like the release
  tables. Titles and descriptions are sent to the configured Azure OpenAI deployment to be grouped.
- `openpyxl` is a new dependency (it reads Excel files).

## [1.6.0] - 2026-10-05

### Added
- **Incident Response Plan (IRP) Studio.** A new page that writes an IRP for an alert from the alert's name, CVRD, output
  columns, description, ARM/Bicep context, severity, trigger condition and owning team. The plan can be previewed as a
  wiki page, copied to the clipboard or downloaded as Markdown.
- **The IRP follows the organisation's IRP example exactly.** The result is the alert title plus three sections only:
  **Alert Details**, **Prerequisites** and **Remediation Steps**. The Remediation Steps table has exactly three columns,
  **STEPS | ACTIONS | ADDITIONAL INFO**, and about ten rows (a guide, not a limit). The expected outcome of an action goes
  in ADDITIONAL INFO.
- **Upload your own IRP example and template.** The example is the skeleton: its first three sections are sent to the AI
  whole (up to 60,000 characters; the old 5,000-character cap is gone) and the sections after Remediation Steps are not
  used. The template is optional and is read as writing guidelines only (up to 30,000 characters); where it disagrees with
  the example about sections or columns, the example wins. Only `.md` and `.txt` files are accepted.
- **The page says which engine wrote the plan.** When Azure OpenAI is not configured or its call fails, a built-in plan for
  AKS/container, App Service or VPN alerts is used instead (any other alert gets the VPN plan), and a notice says why and
  that the uploaded files were not read.
- **API endpoints** `/api/v1/irp/generate` and `/api/v1/irp/publish`, and the Azure DevOps wiki endpoints
  `/api/v1/wiki/list`, `/api/v1/wiki/pages` and `/api/v1/wiki/page`. The page itself offers copy and download; publishing
  to the wiki is available through the API.

### Changed
- **The shape of the IRP is enforced in code, not only requested in the prompt.** Whatever the AI returns is cut down to
  the three sections: extra sections (Post-Incident Analysis, Testing Scenarios, Lessons learned and the rest, however
  they are written), the authoring checklist, notes and second tables are removed; a fourth "Expected outcome" column is
  folded into ADDITIONAL INFO; and a pipe inside a query is escaped so that Azure DevOps wiki and GitHub keep three columns.
- The formatted preview shows exactly the Markdown the server returned (it no longer rewrites table headers).
- **The IRP Studio form is shorter.** The quick-fill alert presets, the CVRD / Alert Identifier field and the Target
  Resource / Service field are gone; the request no longer sends them (the API still accepts them).
- **Severity uses Azure Monitor's scale:** Sev0 (Critical), Sev1 (Error), Sev2 (Warning), Sev3 (Informational) and
  Sev4 (Verbose), with Sev0 (Critical) selected by default. The IRP's Severity row shows the plain name, for example
  Critical, as in the IRP example.

### Fixed
- The dashboard no longer goes blank on a machine with no database configured (the local `/runs` and `/trends` answers
  had the wrong shape).
- Sign-in credentials come only from Key Vault (or `AUTH_USERNAME` / `AUTH_PASSWORD` for local development). There is no
  built-in default account or session secret: with neither configured, nobody can sign in.

## [1.5.0] - 2026-10-03

### Added
- **AI Analysis now reads your real pipeline YAML.** It fetches the pipeline file from Azure Repos and every template it
  includes (relative paths, rooted paths and `file.yml@repository` templates from other repositories, up to 8 levels deep
  and 60 files) and gives the model the complete files. It needs the Azure DevOps PAT you connected with to have the
  **Code (Read)** scope; if the files cannot be read the analysis still runs, and its message says why and names any
  template that could not be read.
- **Every insight shows a root cause, a remediation and a YAML block to paste.** A block is shown as a real change to your
  file ("Change to your pipeline YAML", with **Copy diff** and **Copy new lines**) only when its lines were checked against
  your files. Anything else is labelled "Example to adapt (not from your file)".
- **Each insight says exactly where the step is:** the file, the template's repository, how many stages use it, and the
  step's line number. Steps named with template expressions (for example `Deploy ... ${{ parameters.region }}`) are matched
  to the step names in the run data. When a name fits several steps, or none, the insight says so and lists the candidates
  instead of guessing.
- **Known failure causes are recognised from the error text** and explained precisely: unset pipeline variables (also when
  Azure reports them as an authorization error because the scope contains `$(variable)`), missing permissions (with the
  `az role assignment create` command), resources that do not exist, empty resource group names, a stopped AKS cluster, and
  ARM template parameter type mismatches. For these the cause's diagnosis, remediation and YAML replace the model's own
  wording, so the text and the example always agree.
- **Every failing step above the high-severity thresholds gets an insight** (the old limit of four is gone; up to 15 are
  shown), and insights for the same step failing in several stages, or for one shared cause, are merged into one.

### Changed
- **Severity, impact and retries now follow the measurements.** Severity comes from the thresholds (high: failure rate of
  15% or more, or retry rate of 20% or more; medium: 5% or more). Impact states what was measured and never promises a
  reduction. Retries (`retryCountOnTaskFailure`) are only advised when the error looks transient, and a failure is only
  called transient or deterministic when the error text shows it. When the log does not show the cause, the insight says so
  and offers verbose logging instead of a guess.
- **No invented YAML on a failing step.** A diff that does not match your file, YAML we could not verify, and "YAML" that is
  really a comment or a shell command are removed and replaced by a block derived from the error text.
- The Analyze request sends the PAT in the `X-ADO-PAT` header; recommendations keep a stable order; `PyYAML` is a new
  dependency.

### Fixed
- **The header no longer runs off the screen on windows narrower than 1500px.** The Org / Project / Pipeline / Window
  dropdowns move to a second row, so the status, theme toggle and Admin menu stay visible, and the sidebar follows the
  header's height.

### Notes
- These changes were first deployed inside the untagged 1.4.3 build (commit `6912ca9`); 1.5.0 is their release label.

## [1.4.3] - 2026-10-03

### Fixed
- **Fixed page width and layout bounds across all views.** Constrained the Sprint Board and subpages to the standard 1500px centered layout with consistent container margins and padding, matching Pipeline Insights and Pull Requests.

## [1.4.2] - 2026-10-03

### Changed
- **Sprint report email lists the flagged work items.** Under Check 1 (closed tasks without completed hours) and
  Check 2 (user stories in review for more than 4 work days) the report now lists each work item with its link and
  who it is assigned to ("Assigned to: Name", or "Unassigned"). The rest of the report is unchanged.
- **Copy to Clipboard** now copies a rich version, so pasting into Outlook, Teams or webmail keeps each work item
  number as a real hyperlink. (A `mailto:` email can only carry plain text, so the Outlook draft shows the work item
  URL, which Outlook makes clickable.)
- Very long reports no longer get cut off by the email link length limit: the report is copied to the clipboard and
  the draft asks the sender to paste it.

## [1.4.1] - 2026-10-03

### Fixed
- **Sprint dates were wrong or missing on the Sprint Board** ("Sprint Dates Pending" with a placeholder
  "1 work day remaining"). The board now fills the selected sprint's start and finish dates from the team's sprint
  list, then the team iteration, then the project's iteration node, so it shows what Azure DevOps shows.
  The range is formatted like Azure DevOps ("October 1 - October 31"), uses the UTC calendar day so a viewer's
  timezone cannot shift it, and the page no longer invents "1 work day remaining" when it has no value.

## [1.4.0] - 2026-10-03

### Added
- **Sign-in.** Username and password are stored in Azure Key Vault (`app-auth-username`, `app-auth-password`);
  signed HttpOnly session cookies, failed-login throttling, and every `/api/` route except health and sign-in requires a session.
  Changing the password in Key Vault takes effect within a minute and signs everyone out.
- **Release Readiness Scorecard** with a user-selectable branch per repository.
- **Sprint Board:** milestone summary grouped by Feature/Epic and Area Path (no fixed vocabulary).
- **Single source of truth for the version** (`VERSION` file). The header badge now shows the version the running
  backend reports; `scripts/package_webapp.py` builds the deploy zip and stamps the commit and build time.

### Fixed
- **Sprint Board showed "No sprint tasks found".** A request to Azure DevOps combined `fields` with `$expand`, which it
  rejects with HTTP 400. The same defect broke the milestone summary and Release Readiness work-item lookups.
- **Sprint Board showed other teams' work.** Sprints are shared across a project; items are now limited to the selected
  team's area paths.
- **Release Readiness pipeline health** no longer pools runs from different pipelines; the worst pipeline wins.
- The milestone AI summary always fell back to the plain template because its client class was never imported.
- Project names are escaped in WIQL queries.

### Quality
- Quality gate and Playwright suites sign in with `QG_USERNAME` / `QG_PASSWORD`; a deployed-site check verifies the login gate.

## [1.3.0] - 2026-10-01
- Baseline before versioning was formalized.
