# Changelog

All notable changes to ADO Pipeline Insight. Versions follow [Semantic Versioning](https://semver.org):
**MAJOR** = breaking change, **MINOR** = new feature, **PATCH** = bug fix only.
The number lives in the `VERSION` file; change it with `python scripts/bump_version.py minor|patch|major`.

## [1.9.0] - 2026-10-08

The AI pull request review was rebuilt. It now reads what really changed, works through a checklist for each kind of file (JSON
included), checks every finding before showing it, can look things up in the repository, and can use a stronger model that you
choose for each pull request. Comments are still shown on screen only: nothing is posted to Azure DevOps.

### Changed

**What the review reads**
- **It reads what really changed, file by file.** Each file is compared with its earlier version, and the AI sees which lines were
  added, changed or removed. Before, it read only the first 4 source files, 200 lines each, as whole files.
- **More files, bigger files.** Up to 50 files per pull request are reviewed (150 are looked at). Files up to 1 MB and 12,000 lines
  are read. For a large file the AI sees the changed parts and the lines around them. Python, PowerShell and alert templates come
  first, other languages next, Markdown last. Every file that is skipped is listed with the reason (changelog, deleted, lock or
  generated file, too large, over the limit).
- **PowerShell is now reviewed.** `.ps1`, `.psm1` and `.psd1` files were ignored before. The PowerShell advice uses the
  PSScriptAnalyzer rule names and the slow patterns Microsoft documents (`+=` in loops, `Where-Object` instead of a lookup table,
  `Write-Host`). The Python advice covers slow loops, statuses that should be an Enum, wrong return types, missing timeouts and
  more. C# and Markdown have their own advice too. Other languages get a general review.
- **Alerts written as ARM templates are reviewed as alerts.** A `.json` file that is an ARM template is reviewed as alerts (other
  JSON is reviewed as plain JSON, see below). `.kql` files are read too. For an alert, the AI is also given the alert in plain words (when
  it fires, how often, over what time window, who is told, the query on several lines) and a list of what changed: threshold,
  window, frequency, severity, action groups, the query before and after, new and removed alerts. The alert advice follows
  Microsoft's documentation: changes to when an alert fires, a time filter that does not match the alert's window, a disabled
  alert, no action group, an alert that never resolves, a log alert meant to detect missing data, and secrets that are not
  `securestring`. IRP Studio uses the same reader, so it now also understands the older `2018-04-16` alert format.
- **Markdown files are reviewed** (changelogs are not). The AI looks for removed content that other text still needs, broken links
  and code blocks that are never closed. It does not comment on wording.
- **It reads the author's explanation and the comments already made.** Up to 8,000 characters of the description are used (before,
  only 1,200, so explanations further down were never seen). The AI is told not to report something the description, the code or
  the alert says is intended. It also sees what people already said on each file, including the last reply, and does not repeat
  it. A finding that matches an existing comment is marked "Already raised by <name>", and findings people already resolved do not
  change the verdict.
- **It is told what it cannot know.** The AI is given today's date (it once called past dates "future"), the C# version of the
  file's project (read from the `.csproj`: a `net8.0` project uses C# 12, so `[]` is valid) and the names of the other files in the
  pull request. The alert advice now includes facts from Microsoft's documentation that the AI had wrongly called mistakes.

**How every finding is checked**
- **A finding must show a real case and quote the code.** It needs the exact input or situation, the wrong result, and the code it
  relies on, copied from the file. A finding is removed when it has no case, when it only guesses ("may", "might", "could"), when
  it asks the author to "confirm" something instead of showing a problem, when the quoted code is not in the file, when it
  quotes only code that was not changed, or when it says the code "will not compile" (only the build can show that). Naming,
  structure, style and missing-test findings are never more than a "suggestion". The review notes list what was removed and why.
  The AI may return no findings. A finding may also carry a replacement for the exact lines it points at.
- **A hostile second look at every finding that is left.** Another AI call is told to assume each finding is wrong and to find code
  that shows it: how the rest of the file or query handles the same thing, the facts it was given, what a lookup returned. A
  finding is removed only when that call quotes real code, a fact or a lookup result. A comment in the code or the description never
  counts as proof, because it shows what the author meant, not what the code does. An opinion alone removes nothing.
- **Alert timing is worked out by plain code.** For each alert the AI is told how often it runs, how far back each run reads, and
  for every `ago()` time filter in its query whether it can skip events (shorter than the time between runs), is cut off by the
  window (longer than what a run reads), or is seen by several runs. The advice no longer says that a filter shorter than the window
  is a problem: it is normal, because an event outside the filter on a later run was already seen by an earlier run.
- **SQL has its own advice,** and every language is told to follow the file's own convention before calling a name, label or value
  wrong (the labels of the other branches of the same query, for example), and not to review logic that the description says was
  only moved, renamed or brought into the repository unchanged.
- **A repeat of a code finding is merged.** When an exact check in code and the AI find the same defect, only the code's finding is
  shown. The second check is told what the code already found.
- **The code checks the position.** The file must be in the pull request, the line must be one that was changed, and a suggested
  replacement is kept only when every line it replaces was changed.
- **A second AI check reads each finding again.** It sees the code, the description and the existing comments. It removes what it
  cannot confirm and merges repeats ("The same applies at line N."). The tag says "second check agreed" or "second check did not
  run" (another AI read the code, nothing was run). A finding in an alert template or a KQL file adds "not verified by running
  the query". Before, the tag said "double-checked", which claimed more than the check does.
- **The second check can look things up in the repository.** Many findings are about something in another file: the project's
  target framework, a setting that may still use its old name, where a type is defined. The check has three read-only tools (find
  files, read a file, search the code) over the whole repository at the reviewed commit, up to six AI calls per file. A search
  says how many files it covered, and "not found" in a search that did not cover everything proves nothing. A finding that only
  holds "if" another file is wrong stays only when a lookup confirmed it. Each finding shows what was looked at, and the notes list
  the files that were read. Nothing is written to Azure DevOps.
- **Exact checks made by plain code, with no AI.** These findings say "static check (no AI)" and skip the second check:
  - a variable that is set and never read (PowerShell and Python) and an import that is never used (Python);
  - a file that was valid UTF-8 and no longer is (for example saved as Windows-1252, which shows as replacement characters);
  - a PowerShell script that lost its UTF-8 byte order mark while it has non-ASCII text (Microsoft documents that Windows
    PowerShell then reads it in the wrong code page);
  - a Markdown table row with a different number of cells than its header.
- **Less noise.** A "the description does not mention ..." note is dropped when the AI can quote the sentence of the description
  that covers the change (and the quote is really there), or when the description already uses at least half of its words. Template text left in the description, such as `[Insert Pipeline Link]`, is listed in the checklist. The same note is
  never shown twice.
- **The notes say what the AI proposed and what survived.** For example "The AI proposed 21 findings in 30 files; 18 were removed by
  the rules or the checks; 2 from the AI and 1 from exact checks in code are shown." A line cut in a lookup says it was cut, and the
  quote shown with a finding is shortened (the whole quote is still checked against the file).
- **The verdict, the scorecard and the summary are worked out by code,** not written by the AI. The verdict reads "No issues
  found", "Suggestions" or "Changes suggested" (a review of code changes does not approve a pull request). A scorecard row with no
  finding says "No findings" instead of "Excellent".

**A reviewer that works through a checklist and shows its steps** (measured on real pull requests with the real model)
- **The AI answers a checklist for each file instead of writing free comments.** Each kind of file (Python, PowerShell, C#, SQL,
  JSON, alerts, KQL, Markdown, YAML) has its own list of things that go wrong often, for example a loop that searches a list for every
  item, repeated status text instead of an Enum, a test like `"m" in text` that also matches `"10ms"`, an average of averages, an
  empty `catch`, a function on a column in a SQL `WHERE`. The AI must answer every item: problem, fine or not applicable. On one
  real pull request it found 0 of 9 problems that people had raised when it wrote free comments, and 3 or 4 of 9 with the checklist.
  Your own checks are answered the same way.
- **Every finding shows the steps by which the code goes wrong,** with the value of each variable. The AI often leaves the steps
  out of a true finding, so the second check writes them; a finding that nobody can trace is removed.
- **The second look at a finding has to quote other code.** A finding is removed only when the AI quotes code, other than the
  code the finding is about, that makes the case impossible, and the quote is really in the file. A comment in the code, a name or
  the description never counts as proof.
- **The quoted code must be where the finding points.** A finding that quotes real changed code from one place and points at a
  line 90 lines away is removed (the quoted code must be within 5 lines of the lines it points at).
- **More exact checks in code for Python:** a return type of `dict` or `list` on a function that returns `json.load(...)`, a default
  list or dict that the function changes, `except Exception: pass` with no comment, a shell command built from values with
  `shell=True`, and a `requests` call with no `timeout` (the Requests documentation says leaving it out can hang the program
  indefinitely). A `# noqa` on the line turns the check off.
- **JSON files are reviewed.** Settings, test collections (for example Postman) and data files used to be skipped unless they were alert
  templates. Now they are read as JSON. The reviewer is told where each changed part sits in the structure, for example
  `item[3] "Orders" > item[1] "Get one order" > request`, because a few changed lines in the middle of thousands say nothing
  on their own. It answers a JSON checklist: an entry copied from a neighbor that kept the neighbor's name or URL, a type or unit that
  differs from the siblings, a host or customer written in where the siblings use a variable, a test that checks less than it says,
  a note that contradicts the code it describes, a name that must agree with another file, a file that a script of the repository
  generates. Exact checks in code report a file that stopped being valid JSON (comments and trailing commas are allowed), a key
  written twice in one object (a JSON reader keeps only the last), and a secret written in the file (a token, a private key, an
  authorization header, a password or account key); the review never repeats the secret, it shows its first four characters. The
  same exact checks run on alert templates. A pull request with more files than fit reviews plain JSON after the code files.
- **For a JSON file the first read can look things up in the repository** (find files, read a file, search the code) before it
  answers. That is how a note in a test collection ("the service returns null, so expect 204") can be checked against the service.
  What was looked up is shown on the finding (**Looked at:**, which used to say "Second check looked at") and in the notes.
  With `gpt-6-sol` the lookups run with reasoning turned off, as Microsoft documents for tool calls on that model.
- **A model selector on every pull request, with a fallback.** Set `AZURE_OPENAI_REVIEW_DEPLOYMENT` to the name of a stronger
  deployment in the same Azure OpenAI resource (everything else keeps using `AZURE_OPENAI_DEPLOYMENT`). Each pull request card
  then has its own selector, **Standard** or **Strong**, next to **Review with AI**, and the review drawer has the same selector
  next to **Review again**. A pull request is reviewed with the model chosen for it; the others are not affected, and changing it
  offers "Review again (model changed)". Pull requests start on the strong model when it is set up. If the strong deployment
  cannot answer (not found, access refused, busy, down or unreachable) the standard one finishes the review, and the review says
  so in its notes and in its header; a request that is wrong in itself is not hidden by asking the other model. The header of every
  review names the model that made it. A model that refuses a temperature setting, or refuses function tools unless reasoning is turned off
  (`gpt-6-sol` does both: the first read of a file runs with the model's own reasoning, the lookups of the second check and the hostile
  look run with reasoning off, as Microsoft documents), is asked again without that setting and remembered, so it costs one failed
  call at most. Without a strong deployment the selector still shows, with Strong greyed out as "not set up", and every review uses
  the standard model.

**Your own knowledge base**
- **A box on the pull request page for your own checks.** You write what you know goes wrong often, or must always be looked at,
  one check per line, for example "Never use `Invoke-Expression` on input" or "Every alert has an action group". The review applies
  your checks to every pull request. The text stays in your browser and is sent with each review (it is not stored on the server;
  it goes to Azure OpenAI with the review, like the code does). A line can start with a scope to limit it: `[PowerShell]`,
  `[Python]`, `[C#]`, `[SQL]`, `[JSON]` (or `[Postman]`), `[alerts]`, `[Markdown]` and more, or `[PR]` for a check about the pull request itself (its
  description and its files). Words in `backticks` are searched for in the changed lines, and the review lists where they appear.
  Lines starting with `#` are notes.
- **Your checks follow the same rules as every finding.** A finding that comes from one of your checks still needs a concrete case
  and the exact code it relies on, and the second check still has to agree. It is marked "knowledge base" and shows the check it
  comes from. Your checks are only instructions about what to look for: they cannot switch the rules off.
- **The review says what became of each check.** A card lists every check: raised a finding, no problem reported (an AI read the
  changed code with that check and reported nothing; nothing was run), not applicable (no file of that kind in this pull request),
  or could not be checked. A check about the pull request needs a quoted sentence of the description, a file path or a comment to
  count as broken. If you change the knowledge base after a review, the page says so and offers **Review again**.

**Checklist and page**
- **The PR checklist is checked against the pull request.** Ticked boxes about the changelog, tests and a linked work item are
  compared with the changed files and the linked work items. The run linked in the description is compared with the newest run of
  the same pipeline on the source branch. Everything else on the checklist is listed as something that cannot be verified here.
  The AI also names big changes the description does not mention.
- **A review knows which commit it was made at.** After new commits the page offers "Review again (new commits)", and the review
  has a **Review again** button. The review shows the commit and the push it covers.
- **Copy** gives text ready to paste into an Azure DevOps comment, with a suggestion block when there is a replacement. The review
  says which lines to place it on, so that **Apply Change** replaces exactly those lines.
- **Reviews run in the background.** The page starts the review, shows its progress ("Reviewed 3 of 12 files") and gets the result
  when it is ready. A review that looks things up no longer has to finish within the 230 seconds Azure App Service gives one
  request: it has 10 minutes. A second click while a review runs follows the same review, and at most four reviews run at once.
  A review is kept in the app's memory for an hour and never written to disk, and the token is never kept. If the app restarts,
  the page says so and the review is started again.
- The review says plainly that it reads code changes only and cannot judge how a result looks or behaves when run.

### Fixed
- **A true finding was removed because a comment said the behaviour was deliberate.** A script's header comment said its 24-hour
  cutoff was "deliberately kept in lockstep" with the test's window, and the hostile second look took that as proof. The cutoff is
  worked out once, when the script starts, so the test's window starts minutes later: the edge the human reviewer had raised. Only
  real code, computed facts and lookup results can now remove a finding (in a document, every line counts, since prose has no
  comments).
- **A finding that said it had no failing case was shown** ("No failing case, but the code is unnecessarily verbose"). It is now
  removed.
- **The alert advice invited a wrong finding.** It told the AI to look for a time filter shorter than the window, and the AI then
  said an alert "misses" a crash from 20 minutes ago, although the alert runs every 5 minutes and had reported that crash when it
  was new. The advice and the timing facts above replace it.
- **A SQL label was misread.** The AI said a bucket should be labeled with its start time, although every other bucket of the same
  procedure is labeled with its end time. The AI is now told to follow the file's own convention, and the hostile second look
  looks for the convention.
- **A "the description does not mention" note was wrong** although the description said the file was renamed and its references
  updated: the words of the note and of the description hardly overlapped. The AI must now quote the covering sentence.
- **"Table row has 1 cells"** is now "1 cell".
- **Valid new syntax was reported as a critical error.** In a `net8.0` project, an empty collection (`= [];`, C# 12) was reported
  twice as invalid C#, because the AI does not reliably know newer syntax. The AI is now told the project's C# version, and
  "will not compile" claims are removed.
- **The AI guessed about other files.** It said a namespace "may not exist" and a renamed setting "may break binding", although the
  same pull request added the namespace and updated the setting. Such findings now need a lookup that confirms them.
- **A change of file encoding went unnoticed.** A file saved again as Windows-1252 reached the AI as text full of replacement
  characters, and nobody said the encoding had changed. The review now reports it.
- **An unused variable was missed** while the AI reported a long list of other things. Code now finds it.
- **Large files were skipped** (over 200 KB or 4,000 lines). The limits are now 1 MB and 12,000 lines, and the comparison is fast
  for a long file with a few changes.
- **Only 20 files were reviewed** in a pull request of 40, and then only 30. The limit is now 50, and 150 files are looked at (it was 100).
- **Guesses were shown as warnings.** One review of an alert change gave four warnings that said "may", "could" or "confirm that".
  All four were wrong, and the second check agreed with all of them. Asking the AI not to guess did not work, so it is now
  enforced by code (see above).
- **An alert's query was cut before the AI saw all of it.** The query was cut at 3,000 characters and a line of the changes at
  4,000, so a long shared query never arrived whole. The limits are now 12,000 and 20,000 characters.
- **JSON alert templates were skipped as data,** so a review said "Reviewed 0 of 1 changed files". They are now reviewed.
- **A log alert in the older `2018-04-16` format was read as having no window, no query, no severity and no action group.** The
  reviewer was told "nobody is notified" for an alert that had an action group. IRP Studio's Analyze had the same problem. A flag
  written as the text `"true"` or `"false"` (which that format uses) was not understood either.
- **The AI never saw the author's explanation** when it was past the first 1,200 characters, so it reported deliberate choices (a
  two-minute delay for logs to arrive, a window raised to fit the query's look-back) as mistakes.
- **When nothing could be reviewed, the summary said "(none)".** It now names the skipped files and the reason for each. The limit
  of files counts only the files that are reviewed.
- **A checklist item with a link showed the raw link** (`[Alert Inventory wiki] (https://...)`). It now shows the link's words.
- **No more canned review.** When Azure OpenAI was not set up, or a call failed, a built-in fallback returned fixed advice about
  HTML reports, rated performance "EXCELLENT" for every pull request, and nothing on screen said the AI had not been used. Now
  the request fails with a clear message (503 when the AI is not set up) and nothing is made up. If the AI fails for some files,
  those files are listed as not reviewed. If it fails for all of them, there is no review (502).
- **A review was made even when the pull request could not be read.** After a network failure the error was only logged and the AI
  reviewed an empty pull request. The pull request must now be readable. A missing pull request is a 404, and one with no pushes
  or no file changes is a 422.
- **The review used the server's own Azure DevOps token for any organization** when the caller sent none. It now follows the rule
  of the other pull request routes: the server's token only for allow-listed organizations.
- **Only the first 100 changed files were read, and a file's earlier version was never fetched.** Now all changes are read, page by
  page.
- Test files were recognised by the word "test" anywhere in the path (`latest.py`, `contest.md`). They are now recognised by file
  and folder name.

### Notes
- No new dependency or table, and one optional setting: `AZURE_OPENAI_REVIEW_DEPLOYMENT`, empty by default. To use a stronger model,
  create a deployment of it in the same Azure OpenAI resource (for example `gpt-6-sol`) and put its name there; the endpoint and the
  key are the same, so nothing new goes into Key Vault. The token needs Code (Read), which the lookups use too. If it lacks the
  read scope for the existing comments, the linked work items or the builds, the review still runs and says what it could not read.
- Limits: 150 files looked at, 50 reviewed, up to 400 file reads for lookups per review (each file read once). If the repository's
  file list cannot be read, only the pull request's own files are searched, and the result says so.
- How a review runs: one AI call per file (up to six more when the first read of a JSON file looks things up), a second check for
  each file that has findings (up to six calls when it looks things up), and one for the description, five files at a time. It stops starting new files when its time is up (10 minutes in the
  background, 170 seconds inside one request, because Azure App Service ends a request after 230) and lists the files it did not
  reach.
- API: `POST /api/v1/ado/pullrequests/review` returns `method`, `source_commit`, `iterations`, `files`, `checklist`, `notes`,
  `scope_note` and `knowledge_checks`. Each comment has `end_line`, `language`, `failing_case`, `evidence`, `existing_thread`,
  `existing_status`, `verified`, `source` (`ai` or `static`), `checked_with`, `knowledge` and `knowledge_number`. The review itself has `model` (`deployment`, and `fallback_deployment` and `fallback_reason` when the standard one finished it).
  `GET /api/v1/ado/pullrequests/review/models` says which models are set up (`standard`, `strong`, `default`), and the requests accept
  `model` (`standard` or `strong`; a different model is a different review). The verdict can
  be `NOT_REVIEWED`. The request, and the one that starts a background review, accept `knowledge` (the user's checks, up to 6,000
  characters, at most 40 checks are used); a different knowledge text is a different review.
  `POST /api/v1/ado/pullrequests/review/start` starts the same review in the background (202 with a job), and
  `GET /api/v1/ado/pullrequests/review/status/{job_id}` gives its progress and result.
  `GET /api/v1/ado/pullrequests` returns `last_source_commit`.
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
