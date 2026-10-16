# Issue 19 onboarding isolation validation

**Result: PASS.** One full onboarding run on a fresh external copy completed with exit code 0. The run created an isolated scheduled task, verified Python and the installed environment as the new account, then removed only the task, unloaded profile, and local account created for this run. The formal `\ClinicAntiviralTool` task and its port 8001 listener were unchanged.

## Isolation and copy

- Implementer branch: `codex/issue-19-isolation-validation`, based on integration commit `e1e744fea7de22d6549576b65f022ba67c46f162`.
- External test root: `C:\clinic-onboarding-checks\issue19-20261015-665D45E1`.
- Fresh project copy: `C:\clinic-onboarding-checks\issue19-20261015-665D45E1\runner\project`.
- The pre-onboarding copy manifest saw 64 tracked files and copied 63, excluding `.env.example`. The single onboarding run used that 63-file copy. `.env.example` contains generic documented defaults, not site-specific paths, credentials, or patient data, and is not read by application or onboarding code; after the run, it was restored byte-for-byte into the retained project copy. The original manifest preserves the pre-run state, and `reports/post-run-template-restoration.json` records that all 64 tracked files from the integration baseline are present with matching hashes in the retained copy. The copy did not include `.git`, `.env`, `.venv`, DBF/FPT/CDX/SQLite data, or real Excel files. SHA-256 comparisons for `README.md`, `scripts/ClinicAntiviral.Onboarding.psm1`, and `tests/test_onboarding_powershell.py` matched the source at the integration commit.
- Unique preflight values were account `svc19665D45E1`, task `Clinic19-665D45E1`, and port `24205`. The initial preflight recorded the new external root as absent; it was then created for this run. Before onboarding, the work script confirmed the account, profile path, task, project `.env`, and `.venv` were absent, and port 24205 was unoccupied and bindable. App data, uploads, pip cache, venv, logs, and reports were kept under the new external root.
- The only HIS path used was synthetic `\\192.0.2.10\HISROOT`. No HIS credential or real patient data was used.

## Regression and actual run

After editing the external work script with the unique #19 account, task, and port values, the synthetic regression harness passed all four scenarios: `cleanup-failure`, `native-exit-7`, `powershell-exception`, and `success-both-streams`. Each scenario preserved the expected report; the three failure scenarios correctly returned runner failure, while the success scenario passed. Results are retained under `runner\regression-results\20261015T022140Z-63fb64a7` through `20261015T022142Z-899ccd11`.

The actual onboarding wrapper was then run exactly once, from the copied project, with no `-SkipDependencyInstall` or `-ConfigureFirewall` option. It completed from 2026-10-15 02:22:48 UTC to 02:24:05 UTC with PowerShell exit code 0. The full pip output records successful dependency installation. The wrapper's `native_dependency_exit_code` field remains `unknown` because it does not infer a pip exit status from `LASTEXITCODE`; the independent account-side `pip check` below returned 0. The full wrapper stdout and stderr, structured and Markdown reports, and account-context probe streams remain in:

`C:\clinic-onboarding-checks\issue19-20261015-665D45E1\reports\actual-onboarding`

The generated `.env` points HIS reads to the synthetic UNC and routes app data and uploads under the isolated root; it uses port 24205 and the copied `official-template\smis_report.xlsx` path. The firewall was not changed. No test listener was opened.

The account-context checks used `Start-Process -Credential`; the password was not placed in process arguments or reports. As that account, shared Python reported version 3.12.10 with the expected shared `sys.prefix` and `sys.base_prefix`; `venv`, `ensurepip`, `sqlite3`, and `pip` imports passed. The new venv also reported Python 3.12.10, with its prefix in the copied project and base prefix at the shared interpreter. Imports for `fastapi`, `uvicorn`, `jinja2`, `multipart`, `dotenv`, `openpyxl`, `dbfread`, `httpx`, and `pytest` passed, and `pip check` returned 0 with “No broken requirements found.”

Before cleanup, the new task was `Ready`, with an enabled boot trigger and `startWhenAvailable` enabled. Its principal SID matched the new account; its action was the copied venv's `python.exe -m app.startup --expected-account-sid <SID>` and its working directory was the copied project. The task settings, action, and principal were recorded before removal. It was not started. The app health endpoint was not queried because HIS credential/access setup was intentionally outside this synthetic build validation; startup correctly remains gated on verifying the required HIS tables.

## Cleanup and production comparison

Cleanup matched the test task by its account SID, venv executable, and copied-project working directory before removing it. The profile was confirmed to have the same account SID, exact test profile path, and `Loaded = false` before removal. The newly created local account was then removed. Post-cleanup checks found no test account, task, profile, or listener on port 24205. The copied project, venv, app data, uploaded-data directory, pip cache, and reports were retained for inspection.

The before and after service snapshots compare equal for the formal task fields and listeners. `\ClinicAntiviralTool` remained Running as `svc_clinic_tool`, with the same Python action, working directory, task settings, and listener `0.0.0.0:8001` owned by PID 9716. The formal task XML and structured before snapshot are also retained under `reports`.

The raw work report's top-level `account.sid` is empty because that field records the post-cleanup `Get-LocalUser` result. The pre-cleanup SID remains in `state_before_cleanup.account_sid`, `account_context_verification.account_sid`, the task action, and the profile evidence; the report was left intact.

## Evidence index

- `reports/copy-manifest.json` — tracked-file copy, exclusions, and source/copy hash comparisons.
- `reports/post-run-template-restoration.json` — post-run restoration and hash comparison for the generic `.env.example` template; the original manifest remains unchanged.
- `reports/formal-task-before.xml` and `reports/formal-service-before.json` — formal task settings and listener baseline.
- `reports/actual-onboarding/report.md`, `report.json`, `work-report.json`, `stdout.txt`, and `stderr.txt` — single actual run and full captured output.
- `reports/actual-onboarding/account-python/` — shared interpreter, venv, and pip-check streams.
- `runner/regression-results/` — four synthetic runner scenarios.

The exercise validates isolated host onboarding and environment construction. It does not validate HIS credentials, access to real HIS tables, or application startup against a live HIS share.
