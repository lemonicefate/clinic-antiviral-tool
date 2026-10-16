# Issue #18 external onboarding runner results

Date: 2026-10-15. Scope: synthetic regression only; no real onboarding was run.

The external runner and its artifacts are in:

```text
C:\clinic-onboarding-checks\issue18-20261015-B83F21\
```

The worktree is `C:\Users\UE-3\Documents\dev\clinic-antiviral-tool-issue18` on branch `codex/issue-18-external-runner`, based on integration commit `4dcffd3dbf524da0cee51e32f37bb93fcdc65048`. The runner uses the verified shared Python executable `C:\Program Files\ClinicAntiviralPython312\tools\python.exe` by default. The product dependency-install block was extracted verbatim for synthetic tests; its pip command and nonzero exit check were not changed.

Run the regression suite from the external runner directory with:

```powershell
python test_executor_regression.py --project-root C:\Users\UE-3\Documents\dev\clinic-antiviral-tool-issue18
```

It executes the real call shape—Python controller, Windows PowerShell 5.1 work script, and a temporary synthetic `pip.py`—without installing packages, using a network, or creating accounts or scheduled tasks. Temporary pip modules, requirements files, and work scripts are removed by the tests. Each retained scenario directory contains a `scenario-result.json`; runner output includes complete redacted `report.json`, `report.md`, separate `stdout.txt` and `stderr.txt`, and the PowerShell `work-report.json`.

| Scenario | Synthetic native exit | PowerShell exit | Regression verdict | Runner verdict | Evidence |
| --- | ---: | ---: | --- | --- | --- |
| Old merge repro, then fixed success | 0 | 0 | PASS | PASS | Old merged-stream probe exited 41 after turning native stderr into `NativeCommandError`; fixed call saved both streams and exited 0. |
| Native install failure | 7 | 1 | PASS | FAIL | Stderr and `Python dependency installation failed.` were retained. |
| PowerShell exception | 0 | 1 | PASS | FAIL | Exception details were retained; synthetic bearer token, credential URL, and password were absent from reports and streams. |
| Cleanup failure after synthetic work completion | 0 | 1 | PASS | FAIL | `CLEANUP_INCOMPLETE` was retained and the outer result remained failed. |

The successful scenario also confirms the old false failure: the old PowerShell pipeline produced exit 41 and no success output even though synthetic pip exited 0. The fixed runner reports the PowerShell work-script exit separately from the synthetic pip exit and leaves an unavailable native exit marked unknown.

Final scenario records:

```text
regression-results\20261015T020701Z-1a271afd\success-both-streams\scenario-result.json
regression-results\20261015T020701Z-b5f0c4a7\native-exit-7\scenario-result.json
regression-results\20261015T020701Z-3cd2f3d5\powershell-exception\scenario-result.json
regression-results\20261015T020700Z-e4d31f96\cleanup-failure\scenario-result.json
```

The work script directly invokes onboarding without merging its streams. It records formal task settings and listener status, PID, and process image for before/after comparison. Its `finally` block has a documented insertion point, immediately before `Remove-IsolatedResources`, for issue #19 to verify shared and venv Python as the newly created account before cleanup. No account-context verification or operating-system changes were run for this issue.

The six files in `C:\clinic-onboarding-checks\issue17-20261015-C64E10\` retained identical SHA-256 hashes before and after this work.
