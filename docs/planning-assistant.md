# Planning Assistant and saved reports (1.11.0)

Deliverables snapshots are scoped by organization, project, team and iteration. Opening a saved report reuses its timestamp; Regenerate replaces it only after generation succeeds. Team recipients refresh separately. Filters include stories, bugs and tasks; email reports include stories and bugs only. Group identities are expanded to individual email addresses and missing addresses are disclosed. Capacity records show daily hours, working days and leave separately from cumulative task effort.

Backlog uses native team backlog levels and order. Capacity reads Azure DevOps activities and days off. Analytics shows historical remaining task hours from daily UTC ASOF queries; today's point is provisional and missing remaining-hour fields are disclosed. This is not full parity with all Azure DevOps Analytics widgets.

Planning settings persist per team, responses and proposals per sprint. Manual reminders open local mail drafts; all test reminders are restricted to hrushikeshboora@gmail.com. Links require app sign-in and a signed, scoped token, expire after 45 days, and restore saved responses. Settings do not run a background scheduler. Automatic delivery remains disabled until a sending provider is implemented.

Proposals require explicit ranked work item IDs, use recorded hour estimates and leave scenarios, preserve owners when capacity permits and flag missing estimates, unanswered forms and dependencies. Skills and dependency review remain human decisions. Proposals require approval and never update Azure DevOps.

## Deployment configuration

Use the existing Linux Python App Service. Enable SCM_DO_BUILD_DURING_DEPLOYMENT=true to install requirements from the ZIP. Existing authentication, PAT configuration and startup command must remain configured. Require app login (REQUIRE_LOGIN=true and existing Easy Auth configuration) for response forms.

Preferred persistence: set REPORT_STORAGE_ACCOUNT_URL to the Azure Blob endpoint and REPORT_STORAGE_CONTAINER to a provisioned private container. Enable the web app managed identity and grant Storage Blob Data Contributor for that container. Do not configure public container access. The app does not provision storage or RBAC.

For a test app without a separate storage account, explicitly set REPORT_STORAGE_DIR=/home/data/planning-reports and WEBSITES_ENABLE_APP_SERVICE_STORAGE=true. Data is outside the deployment directory and survives ZIP replacement. This is a test fallback; back up data and use Blob for multi-instance production. The process lock only serializes report regeneration within one process.

Set PLANNING_LINK_SECRET to a persistent random secret of at least 32 bytes. Preserve it on redeployment; rotating it invalidates existing links. Never put it in git. Without storage, generation can display an unsaved Deliverables report but settings and responses cannot be saved.

Run scripts/deploy-test-webapp.ps1 locally with the downloaded ZIP path. It validates the file before changing Azure, preserves an existing link secret, enables the explicit test persistence fallback only when neither storage option exists, and deploys. Azure login and the correct subscription are prerequisites. Verify the live tabs and save/reload/regenerate flow after deployment; local tests do not verify tenant permissions or live Easy Auth.
