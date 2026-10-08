# Legacy salvage audit

The working tree started with only `SPEC.md`. The configured GitHub remote has no branches or tags, so no older implementation or research repository is available in this checkout to inspect.

## Keep

- Verified Eraflu medication mapping and official material value recorded in `SPEC.md`.
- Candidate HIS source identity fields `RELKEY` and `SYS_2015` recorded in `SPEC.md`.
- `TREAT` behavior recorded in `SPEC.md`.
- Verified source quantity and report-date fields recorded in `SPEC.md`.
- The official-template and medication-reason requirements recorded in `SPEC.md`.

## Rewrite

- HIS reader: implement a small read-only normalized prescription boundary for this MVP.
- Excel exporter: implement directly against the supplied official template and validate the generated workbook.

## Drop

- No legacy code was imported.
- Tauri, React/TypeScript SPA code, authentication/RBAC, device identity, generated SDKs, request/revision frameworks, event sourcing, source-version graphs, updater/signing/rollback, backup subsystems, complex quarantine/retry pipelines, database migration, and other architecture excluded by `SPEC.md` remain out of scope.
