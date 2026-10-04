# Changelog

All notable changes to ADO Pipeline Insight. Versions follow [Semantic Versioning](https://semver.org):
**MAJOR** = breaking change, **MINOR** = new feature, **PATCH** = bug fix only.
The number lives in the `VERSION` file; change it with `python scripts/bump_version.py minor|patch|major`.

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
