# 公費流感抗病毒藥劑使用回報小工具 — SPEC

Version: Small Tool MVP v1.0

Date: 2026-10-08

Repository: [https://github.com/lemonicefate/clinic-antiviral-tool](https://github.com/lemonicefate/clinic-antiviral-tool)

## 0. Authority

This document is the ONLY active implementation specification for this repository.

Previous specifications, prototypes, repositories, experiments, and partially implemented systems are historical references only.

In particular, previous requirements involving:

- Tauri

- React

- TypeScript

- SPA architecture

- OpenAPI client generation

- authentication

- role-based access control

- device pairing

- device certificates

- requestId

- expectedRevision

- general concurrency conflict frameworks

- event sourcing

- immutable source-version graphs

- complex export versioning

- updater/signing/rollback

- backup subsystems

- automatic SMIS login/upload/query

- complex quarantine/retry workflows

MUST NOT be carried into this project unless explicitly required by this SPEC.

The implementation goal is intentionally a small internal clinic tool.

When choosing between:

1. a more generic/extensible architecture, and

2. a simpler implementation that satisfies this SPEC,

choose the simpler implementation.

Do not preserve complexity merely because an older implementation already contains it.

---

# 1. Product Goal

Reduce the daily administrative burden of reporting publicly funded influenza antiviral medication usage to Taiwan CDC SMIS.

The normal workflow should be:

Doctor:

1. Open `/doctor`.

2. Select or reuse the remembered doctor ID.

3. Load the doctor's most recent eligible antiviral prescription, or search by medical record number.

4. Confirm the patient displayed is correct.

5. Select the official medication-use reason.

6. Save.

7. The page clears and is ready for the next patient.

Pharmacist/reporting staff:

1. Open `/pharmacy`.

2. Scan today's prescriptions or a selected date/date range.

3. Review missing cases.

4. Fill or correct medication-use reason, actual dispensed quantity, and lot number.

5. Resolve any HIS changes detected before export.

6. Select exportable cases.

7. Generate the official SMIS Excel.

8. Manually upload the Excel to SMIS.

9. Mark the export batch as uploaded.

10. After verifying records appear in SMIS, mark the relevant cases as confirmed complete.

The tool does NOT automate SMIS authentication, upload, or platform verification.

---

# 2. Product Philosophy

This is a clinic utility, not a general healthcare platform.

Priorities, in order:

1. Correct patient/prescription matching.

2. Correct export data.

3. Very low daily interaction cost.

4. Fast deployment.

5. Easy maintenance by one developer.

6. Automated verification wherever practical.

7. Minimal architecture.

Avoid speculative infrastructure.

Do not build functionality only because it may be useful someday.

Future Tauri wrapping is allowed as an idea, but MVP MUST NOT add architecture specifically to prepare for Tauri.

---

# 3. Scope

## In scope

- One clinic.

- Internal clinic LAN only.

- Publicly funded influenza antiviral medications configured in a simple mapping file.

- HIS DBF read-only integration.

- Doctor reason entry.

- Pharmacy/reporting workbench.

- Actual dispensed quantity.

- One or multiple medication lot numbers per case.

- Date/date-range HIS scanning.

- Official Excel generation.

- Manual SMIS upload tracking.

- Manual SMIS confirmation tracking.

- Simple audit history for important editable fields.

- Simple export batches.

- Basic application logs.

## Out of scope

- Internet access.

- Remote access.

- VPN/Tailscale support.

- Login/authentication.

- Passwords or PINs.

- RBAC.

- Device restrictions.

- OAuth.

- Tauri in MVP.

- React.

- SPA.

- TypeScript requirement.

- Public API design.

- Automatic SMIS login.

- Automatic SMIS upload.

- Automatic SMIS scraping/querying.

- Automatic SMIS reconciliation.

- Inventory management.

- Medication stock management.

- Full audit platform.

- Event sourcing.

- Generic workflow engine.

- Complex concurrency architecture.

- Offline mode.

- Offline sync.

- Backup UI or backup subsystem.

- Data migration from prior implementations.

- Patient master-data editing.

- Fully manual case creation.

- Automatic data retention/deletion jobs.

- Dashboards/charts/analytics.

---

# 4. Deployment Architecture

Use a single central Windows development machine inside the clinic.

Technology:

- Python 3.12

- FastAPI

- Jinja2

- HTMX where useful

- minimal JavaScript only where needed

- SQLite

- openpyxl for Excel operations

- an appropriate Python DBF reader

No Node/Vite/React build pipeline is required.

Run directly from source using a Python virtual environment.

Suggested runtime layout:

clinic-antiviral-tool/

  app/

  templates/

  static/

  tests/

  official-template/

  scripts/

  [SPEC.md](http://SPEC.md)

  [README.md](http://README.md)

  .env.example

  .gitignore

Runtime/private data should live OUTSIDE the Git repository where practical:

C:\\clinic-data\\

  his-mirror\\

  app-data\\

  uploaded\\

Configuration points to these runtime directories.

Provide simple operational scripts such as:

- start.bat

- stop.bat

- update.bat

The central service should be configured to start with Windows.

No EXE packaging is required for MVP.

No Docker is required.

---

# 5. Network Model

The application is available only on the clinic LAN.

Routes:

- `/doctor`

- `/pharmacy`

There is no authentication.

Any machine on the clinic LAN that can reach the application may open either route.

This is an explicit MVP tradeoff.

Do not add:

- login

- PIN

- IP whitelist

- device identity

- session authorization

unless a future spec explicitly changes this decision.

---

# 6. HIS Safety Model

## 6.1 Production HIS

Production HIS DBF/FPT/CDX files are immutable external data sources.

The application MUST NEVER:

- write to them

- create files in the HIS production directory

- rename them

- move them

- delete them

- truncate them

- overwrite them

- open them using writable modes

Production access should use OS/share permissions that are read-only.

## 6.2 Development HIS Mirror

Developers and agents MUST NOT work directly against writable production HIS files.

Development uses a disposable mirror such as:

C:\\clinic-data\\his-mirror\\

The mirror:

- may contain copies of real HIS DBF/FPT/CDX files

- is replaceable/rebuildable

- is NEVER committed to Git

- exists outside the repository where practical

## 6.3 Today's index lifecycle

The central server may build one volatile, in-memory index for today's matching antiviral prescriptions when the service starts. The doctor page shows the shared build progress and completion state to every client.

Before a doctor lookup, the server performs a read-only metadata check. If the known DBF tables only grew by append-safe records, the index may read just the new tail records. If a table was replaced, edited in place, truncated, or otherwise cannot be proven append-safe, the index is marked stale and requires a complete rebuild; it must not guess.

The index is a lookup acceleration only. It is never the final HIS authority: saving a doctor report or exporting a pharmacy report must re-read the selected prescription from the known read-only DBF source. The index and its cursors are held outside the HIS directory; no DBF, FPT, or CDX file is created or modified.

This is request-triggered refresh plus one startup warmup, not a background HIS scanner. A recent-hour shortcut, when offered, is an in-memory filter over today's index and never permits a previous-date fallback.

`.env` contains the runtime mirror path and is ignored.

`.env.example` contains no real paths or patient information.

Git MUST ignore at least:

*.dbf

*.DBF

*.fpt

*.FPT

*.cdx

*.CDX

.env

Add a lightweight repository guard/test that fails if DBF/FPT/CDX files become staged or tracked.

Do not place real patient data in test fixtures, Git history, screenshots, or logs.

---

# 7. Existing HIS Knowledge

The new project may reuse VERIFIED KNOWLEDGE from earlier investigation, but SHOULD NOT inherit previous architecture.

Known current Eraflu mapping:

- CH012M1.MED1 = ERA

- H\_INV.ITEMN = ERA

- H\_INV.LABNUM = A059653100

- official SMIS item:

  `DDMTR2018090002:易剋冒膠囊(顆)`

- source quantity:

  `CH012M1.USE_TAMT`

- quantity unit:

  whole capsules

- report date:

  `CH011M1.SDATE`, date only

Known candidate source identity:

- RELKEY

- SYS\_2015

These identifiers may be used based on previously validated knowledge, with only lightweight production smoke testing required.

Known TREAT behavior:

- `Y`: normal candidate

- `C`: prescription may require pharmacist review

- `N` with remaining antiviral order: treat as abnormal and surface to pharmacist

- deleted DBF rows have no reporting meaning

Do not create a large generic HIS framework around these rules.

---

# 8. HIS Reader Boundary

Implement HIS access as a thin internal Python module.

It only needs to support:

1. Get the most recent configured public antiviral prescription for a doctor.

2. Find the relevant prescription using medical record number.

3. Scan prescriptions for:

   - today

   - a selected single date

   - a date range up to 31 days

4. Re-read a known prescription before pharmacist review/export.

Do not:

- create a reusable HIS SDK

- create a second service

- call the old HIS-pro application at runtime

- build a generalized DBF abstraction platform

Existing old code may be inspected for verified behavior, but this project should contain a small clean implementation appropriate to its scope.

---

# 9. Medication Configuration

Support multiple publicly funded influenza antivirals.

Use a simple source-controlled configuration mapping.

Each medication mapping should contain only what is needed, such as:

- internal HIS medication identifier

- expected NHI code if applicable

- official SMIS material value

- unit

- any required matching fields

Do not build a medication-management UI.

Currently verified Eraflu should be included.

Adding a future antiviral should mean:

1. add mapping

2. add/update automated tests

3. perform one lightweight real-world verification

—not redesigning the application.

---

# 10. Official Excel Template

The official SMIS Excel is an external template file, not hard-coded workbook construction.

Example location:

official-template/smis_report.xlsx

Export process:

1. Copy the official template.

2. Populate required cells/rows.

3. Save the result.

4. Re-open the generated workbook.

5. Perform lightweight structural/content validation.

6. Return/download the generated file.

The program should verify expected template structure before export, including key worksheet/header expectations.

If the official template becomes structurally incompatible:

- fail clearly

- show an understandable error

- do NOT silently attempt to adapt

Do not build a template-management UI.

---

# 11. Medication-Use Reasons

The doctor/pharmacy reason dropdown MUST be read directly from the official Excel template's code table.

Do not:

- duplicate the reason list into application code

- maintain a separate reason configuration

- hard-code current reason strings

If the code-table structure changes incompatibly, fail with a clear template-compatibility error.

---

# 12. Case Model

One stable HIS medication-order item corresponds to one reporting case.

A case represents one actual dispensing event.

Multiple physical medication lots are quantity allocations within the same case, not separate cases.

The application MUST NOT create duplicate cases for the same identified HIS order.

Store a small snapshot when a case is created, containing only reporting-relevant values such as:

- HIS source identity

- medical record number

- patient name

- patient ID

- birth date

- sex

- report/dispense date

- doctor ID

- medication

- source quantity

- other required official-export fields

Also store editable reporting values:

- medication-use reason

- actual dispensed quantity

- lot allocation(s)

- case state

- exclusion reason

- uploaded/confirmed status as needed

Do not implement full source snapshot history.

---

# 13. Doctor Page

Route: `/doctor`

This is intentionally a single minimal page.

Show only:

- doctor ID selector

- button to load most recent matching prescription

- medical record number search

- patient identity summary

- medication/date/quantity summary

- medication-use reason dropdown

- Save

Doctor ID:

- no login

- remember the last selected doctor ID in the browser

- allow quick switching

## Recent prescription behavior

"Most recent" on the doctor page means:

the most recent HIS prescription dated today, belonging to the selected doctor, that matches configured publicly funded influenza antiviral mappings.

The doctor lookup MUST NOT fall back to an earlier date when today has no matching prescription. Pharmacy date and date-range scans remain separate operations and may query their explicitly selected dates within the existing 31-day limit.

Do NOT prioritize incomplete cases.

Incomplete-case follow-up belongs to pharmacy/reporting staff.

## Patient confirmation

Before reason selection/saving, the page must make patient identity clear.

Keep confirmation extremely simple.

Do NOT add:

- multi-step wizards

- repeated confirmation dialogs

- historical lists

- dashboards

- incomplete-case notifications

## Existing case

If the same HIS order already has a case:

- show the existing reason

- allow the doctor to modify it

- do not create another case

## Save behavior

After successful save:

1. briefly show success

2. clear patient-specific content

3. return to the ready state

Do not auto-load the next patient.

Doctors do not handle lot numbers.

---

# 14. Pharmacy Page

Route: `/pharmacy`

This is one single-page operational workbench.

No separate:

- dashboard

- case-detail page

- export-history page

- audit page

The table itself is the primary UI.

Default view shows unfinished work.

Default-visible states:

- missing reason

- missing lot/quantity

- ready to export

- uploaded but not confirmed

Completed cases are hidden by default but can be shown via filter.

Excluded cases can be shown via filter.

Useful lightweight filters may include:

- date

- state

- doctor

- medication

Do not build a generalized search system.

---

# 15. Pharmacy Scan

Provide:

- Scan today

- Scan selected date

- Scan date range

Maximum date range: 31 days.

No background scanning.

When a scan finds a matching HIS prescription without an existing case:

- create the case automatically

- mark it missing reason

Do not add an intermediate "discovered but not created" workflow.

The pharmacist/reporting staff owns follow-up on cases doctors did not complete.

---

# 16. Pharmacy Editing

Pharmacy/reporting staff may edit only these reporting fields:

- medication-use reason

- actual dispensed quantity

- lot number(s)

HIS-derived patient/master fields are not directly editable in this tool.

If a HIS-derived patient field is wrong, fix it in the appropriate source workflow, not here.

Each table row has an explicit Save button.

No autosave.

No "save entire table" operation.

---

# 17. Lot Numbers

Doctors never handle lot numbers.

Default case UI supports one lot number.

For the uncommon multi-lot case, provide a small:

`+ Add another lot`

expansion.

Each lot has:

- lot number

- allocated quantity

Sum of lot allocations must equal actual dispensed quantity before export.

Do not create a complex lot editor.

---

# 18. Batch Lot Assignment

Pharmacy/reporting staff may select multiple cases and apply one lot number to them.

Batch lot assignment is allowed only when all selected cases represent the same medication.

If mixed medications are selected:

- reject the batch action

- show a simple message asking the user to separate medications

Individual cases remain editable afterward.

No daily-default lot feature.

---

# 19. Quantity

Initial actual dispensed quantity defaults to the HIS source quantity.

Pharmacy/reporting staff may change it to actual quantity dispensed.

Source quantity remains visible/preserved for comparison.

Important manual changes are recorded in simple audit history.

---

# 20. HIS Re-check Before Export

Do NOT continuously monitor HIS changes.

Doctors are not interrupted by HIS change detection.

Before export, for selected cases:

1. re-read the relevant HIS order

2. compare only fields relevant to reporting

3. if no meaningful change, proceed

4. if changed, block ONLY that affected case from export

Other valid cases must continue exporting.

For a changed case, show only the changed fields.

Provide exactly these choices:

- Use latest HIS data

- Keep current reporting data

- Exclude case

After one choice is made, the case may become exportable again if otherwise valid.

Do not build:

- full snapshot browser

- diff-history subsystem

- source-version graph

- background change monitoring

---

# 21. Exclusion

Cases cannot be deleted.

They may be excluded.

Exclusion reasons:

- Patient did not collect medication

- Prescription cancelled

- Duplicate data

- Other

"Other" may request a short reason only if needed.

Excluded cases:

- are removed from unfinished default work

- remain stored

- can be filtered/viewed

- can be restored/re-included

Restoring an excluded case returns it to the appropriate normal state.

No recycle bin.

No delete/restore system.

---

# 22. States

Keep states minimal.

User-facing states:

- Missing reason

- Missing lot/quantity

- Ready to export

- Uploaded

- Confirmed complete

- Excluded

Do not create additional workflow states unless absolutely required to implement the above.

Use local UI indicators for temporary situations such as HIS-difference resolution rather than growing the persisted state machine.

---

# 23. Export Selection

On the pharmacy workbench:

- Ready-to-export cases are selected by default.

- Pharmacist may unselect individual cases.

- Uploaded cases are not selected by default.

- Previously uploaded cases may be selected manually again, with a simple warning.

Do not build a formal correction-version workflow.

---

# 24. Export Validation

Do NOT add a separate preview wizard.

When the user clicks Generate Excel, automatically validate the selected cases.

At minimum validate:

- medication-use reason exists

- lot number exists

- actual dispensed quantity is valid

- multiple-lot quantities sum correctly

- mandatory HIS/export fields exist

- unresolved HIS differences do not remain

If some selected cases are invalid:

- export the valid cases

- skip invalid cases

- leave invalid cases in the workbench

- show a concise summary:

  - selected count

  - exported count

  - skipped count

  - reasons for skipped cases

Do not block an entire export because one case is incomplete.

---

# 25. Export Batch

Each generated Excel is one simple export batch.

Store only what is needed:

- batch ID

- creation time

- selected operator

- included case IDs

- generated filename

- uploaded boolean

- uploaded time

No:

- version graph

- immutable event model

- correction chain

- complex batch state machine

Draft/generated files that were never actually uploaded do not need permanent historical retention.

---

# 26. Uploaded Excel Retention

When the user marks an export batch as uploaded:

- preserve the exact Excel file that was uploaded

- save it to a simple runtime directory such as:

  C:\\clinic-data\\uploaded\\YYYY\\MM\\

- store the filename/path association in SQLite

Do not:

- hash files

- build object storage

- create a version graph

Never silently overwrite a previously preserved uploaded Excel.

---

# 27. Upload / Platform Confirmation

SMIS operations remain manual.

After the user manually uploads an Excel:

- mark that export batch Uploaded

This marks all included cases Uploaded.

Later, after checking SMIS:

- one or many cases can be selected

- mark selected cases Confirmed complete

Platform confirmation is case-level.

No automatic SMIS query.

No automatic reconciliation.

---

# 28. Editing Confirmed Cases

A Confirmed complete case may still be corrected.

If the user attempts to change:

- medication-use reason

- actual dispensed quantity

- lot number(s)

show a clear warning:

"This case has already been confirmed in SMIS. Changing it may require reporting again."

If the user proceeds:

- allow the change

- record the simple audit entry

- return the case to the appropriate pre-upload/exportable state

Do not create a formal correction workflow/version tree.

---

# 29. Simple Audit History

Track changes ONLY for:

- medication-use reason

- actual dispensed quantity

- lot number(s)

For each change store:

- timestamp

- selected operator

- field

- previous value

- new value

Do not build a global audit subsystem.

On `/pharmacy`, provide a small "View changes" action per case.

It displays only:

- time

- operator

- field

- before

- after

No global search.

No audit export.

No advanced filters.

---

# 30. Operator Identity

There is no login.

Doctor operator identity is the selected doctor ID.

Pharmacy operator identity is a simple selector remembered by the browser.

This is an attribution hint, not authenticated identity.

Do not treat it as security authorization.

---

# 31. No Notes Field

Do not add a generic free-text notes field.

Avoid using notes as a catch-all for workflow complexity.

---

# 32. Historical Data

The Small Tool begins from a new explicit go-live date.

Do NOT migrate previous application databases or workflow history.

Old applications remain historical/read-only references.

The Small Tool must not scan/create cases before its configured go-live date.

Existing unfinished work should be resolved before cutover where practical.

Completed cases are retained in SQLite indefinitely for MVP.

No:

- archive system

- automated deletion

- retention job

---

# 33. Database

Use one SQLite database.

Keep schema small and understandable.

A reasonable minimal model may include:

## cases

- id

- HIS source identity

- required patient/report snapshot

- doctor ID

- medication mapping ID/value

- HIS source quantity

- actual dispensed quantity

- medication-use reason

- state

- exclusion reason

- timestamps

## case\_lots

- case ID

- lot number

- quantity

## change\_history

- case ID

- field

- old value

- new value

- operator

- timestamp

## export\_batches

- batch ID

- filename

- operator

- created time

- uploaded

- uploaded time

## export\_batch\_cases

- batch ID

- case ID

Avoid additional tables unless clearly justified by an MVP requirement.

Do not build abstractions for hypothetical future products.

---

# 34. Error Handling

User-facing errors must be understandable and short.

Show:

- plain-language message

- stable error code

Examples:

HIS read failed.

Error: HIS_READ_001

Official Excel template missing or incompatible.

Error: EXPORT_TEMPLATE_001

Excel generation failed.

Error: EXPORT_002

Database write failed.

Error: DB_001

Do not show raw tracebacks to doctors/pharmacy staff.

Detailed traceback goes to the application log.

An error must never be presented as success.

If a save fails, the UI must not clear the form as though it succeeded.

If export fails, no batch should be treated as uploaded or complete.

---

# 35. Logging

Use a simple rotating application log.

Log only what helps debugging, such as:

- application start/stop

- HIS read failure

- Excel/template failure

- SQLite failure

- unexpected exception

- short operational identifiers such as internal case ID/batch ID

Do NOT log:

- full patient names where avoidable

- national ID numbers

- birth dates

- full DBF records

- entire prescriptions

- credentials

- patient-data dumps

Logs are for debugging, not a second clinical database.

---

# 36. Backup

MVP contains NO backup subsystem.

Do not implement:

- scheduled backup

- restore UI

- backup monitoring

- RPO logic

- application backup button

Keep runtime data locations simple enough that an external/manual backup strategy can be added later.

---

# 37. Existing Half-built Project

The previous implementation is NOT the foundation of this project.

Before implementing, inspect the old work only to salvage verified knowledge.

Classify relevant pieces as:

- KEEP

- REWRITE

- DROP

Rules:

KEEP:

- verified HIS field knowledge

- verified medication mappings

- verified official Excel mapping behavior

- useful pure tests that do not pull old architecture with them

REWRITE:

- HIS reader if old implementation is coupled to old architecture

- Excel exporter if simpler implementation is possible

DROP:

- unnecessary architecture from prior specs

Do NOT keep something simply because it has already been implemented.

This repository should remain clean and small.

---

# 38. Testing Strategy

The owner should NOT be required to manually manufacture realistic DBF test datasets.

## Automated tests

Agents must create minimal synthetic programmatic test data for pure application logic where practical.

Automated tests should cover at least:

- medication mapping

- duplicate-case prevention

- reason-list extraction from official template

- quantity validation

- multi-lot totals

- state derivation

- exclusion/reinclusion

- export validation

- Excel field writing

- export batch creation

- uploaded state behavior

- confirmed-complete behavior

- editing a confirmed case returns it to reporting flow

- date range limit

- scan creates missing cases

## HIS integration

Development integration testing uses the disposable HIS Mirror.

Do NOT require the owner to create hand-made realistic DBF fixtures.

## Manual verification is deliberately limited to:

1. Real HIS smoke test:

   - recent prescription returns correct patient/order

   - MRN search returns correct order

   - date scan approximately matches expected prescriptions

2. Clinic usability smoke test:

   - doctor flow is fast and obvious

   - pharmacy workbench is usable

3. SMIS smoke test:

   - generated official Excel can be accepted by SMIS

Do not create a giant manual M0 validation matrix.

The project philosophy is:

"Automate what an agent can verify. Manually verify only real-system boundaries."

---

# 39. Agreed Test Seams

Prefer a small number of high-level seams.

Primary application seam:

"Given HIS prescription data + operator edits, the web workflow produces and tracks the correct reporting case and official Excel output."

Key boundary seams:

1. HIS reader boundary

   - query in

   - normalized prescription out

2. Official Excel template boundary

   - valid reporting cases in

   - uploadable workbook out

3. Web workflow boundary

   - user action in

   - persisted case/batch state out

Do not create extra abstractions only to increase unit-test count.

Favor high-value behavior tests over implementation-detail tests.

---

# 40. Verification / Definition of Done

MVP is done when all of the following are true:

## Doctor flow

- `/doctor` loads.

- selected doctor ID persists locally.

- recent matching prescription can be loaded.

- MRN search works.

- patient identity is clearly shown.

- official reason dropdown loads from Excel template.

- saving creates/updates the same case without duplication.

- success clears patient-specific screen.

## Pharmacy flow

- `/pharmacy` loads unfinished cases by default.

- today/single-date/date-range scans work.

- scan range over 31 days is rejected.

- scans create missing cases automatically.

- reason, actual quantity, and lots can be edited.

- each row uses explicit Save.

- same-medication batch lot assignment works.

- mixed-medication batch lot assignment is rejected.

- multi-lot quantity validation works.

- cases can be excluded and re-included.

- change history is viewable per case.

## HIS re-check

- selected export cases are re-read from HIS before export.

- changed cases are blocked individually.

- changed values are shown simply.

- user can choose:

  - latest HIS

  - keep reporting data

  - exclude

- unaffected cases continue exporting.

## Excel

- official external template is used.

- reason codes come from official template.

- valid selected cases export.

- invalid selected cases are skipped with clear reasons.

- generated workbook is re-opened/validated.

- real SMIS smoke test succeeds.

## Upload tracking

- generated Excel maps to a simple export batch.

- batch can be marked uploaded.

- uploaded Excel is preserved.

- included cases become Uploaded.

- one or many Uploaded cases can become Confirmed complete.

- editing a confirmed case warns the user and returns it to reporting workflow.

## Safety

- production HIS is never written.

- development uses HIS Mirror.

- DBF/FPT/CDX files are not tracked by Git.

- `.env` is not tracked.

- logs do not dump patient data.

- prior project data is not migrated.

## Operations

- application runs from Python venv on central Windows machine.

- startup script works.

- update script is simple.

- no Tauri/React/Docker/installer is required.

---

# 41. Constraints

Hard constraints:

1. Keep the project small.

2. Prefer one obvious implementation over extensibility.

3. No authentication.

4. LAN only.

5. HIS read-only.

6. Development against HIS Mirror, never writable production DBF.

7. Real DBF mirror files never enter Git.

8. No old database migration.

9. No Tauri in MVP.

10. No React/SPA.

11. No automatic SMIS actions.

12. No backup subsystem.

13. No generic platform abstractions.

14. No hidden silent fallback when data is uncertain.

15. No manual testing burden unless the behavior crosses a real external-system boundary.

---

# 42. Iteration Policy

When an implementation choice is unclear:

1. choose the smallest solution satisfying this SPEC

2. prefer deletion over abstraction

3. prefer explicit code over framework creation

4. prefer one screen over navigation

5. prefer one table over multiple workflow pages

6. prefer a normal function over a generic subsystem

7. avoid speculative extensibility

Do NOT ask the owner low-value implementation questions.

Only stop for clarification if the ambiguity could materially cause:

- wrong patient

- wrong prescription

- wrong medication

- wrong quantity

- wrong lot

- wrong official reason

- wrong Excel

- accidental HIS write

- irreversible loss of meaningful reporting data

Otherwise make the simplest reasonable decision, document it briefly, and continue.

---

# 43. Error/Failure Policy

If a command/task fails:

- diagnose before retrying

- do not repeatedly attempt destructive or broad fixes

- preserve working code

- keep the branch/test suite green where practical

- record blockers in the relevant GitHub Issue

- prefer a narrow workaround over architecture expansion

If the HIS Mirror is unavailable:

- fail clearly

- do not switch to production write-capable access

If production HIS access appears writable:

- STOP that integration path

- do not "test carefully"

- require read-only OS/share permissions before proceeding

If official Excel structure differs:

- fail the export compatibility check

- do not silently guess new mappings

If a test exposes an unanticipated edge case:

- first decide whether it affects normal clinic reporting

- fix it if it materially affects correctness

- do not expand MVP into a generalized framework merely to model the edge case

---

# 44. Outcome

The desired outcome is NOT a sophisticated software system.

The desired outcome is:

A clinician can record the official public-antiviral reason in seconds.

A pharmacist/reporting staff member can see missed cases, enter quantity/lot information, generate the official Excel, upload it manually, and track confirmation with minimal clicks.

The owner can understand and maintain the codebase with AI assistance without needing to operate a medium-sized software platform.

If the implementation becomes difficult to explain in a short README, it is probably too complicated.

---

# 45. Implementation Priority

Build the smallest end-to-end vertical path first:

HIS Mirror

→ doctor loads prescription

→ doctor selects reason

→ SQLite saves case

→ pharmacy sees case

→ pharmacy adds quantity/lot

→ Excel generates from official template

Only after this complete path works should secondary conveniences be added.

Do not start by building infrastructure horizontally.
