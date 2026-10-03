# Changelog

All notable changes to ADO Pipeline Insight. Versions follow [Semantic Versioning](https://semver.org):
**MAJOR** = breaking change, **MINOR** = new feature, **PATCH** = bug fix only.
The number lives in the `VERSION` file; change it with `python scripts/bump_version.py minor|patch|major`.

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
