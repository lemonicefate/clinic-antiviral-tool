---
status: accepted
---

# Guided workgroup onboarding for the HIS boundary

The v0.1.0 application host uses a separate local task account and stores the existing HIS read-only credential in that account's Windows Credential Manager. HIS host onboarding is verify-only: it checks the existing workgroup account, full-root share, ACLs, and required DBF tables, while all HIS account, share, and ACL changes remain manual. This avoids an automated change that could interrupt clinical HIS access, while keeping the application client unauthenticated as required by the product specification.

## Consequences

- The production HIS path is an explicit UNC path; mapped drives are not part of the task configuration.
- The credential bootstrap must run under the same local account that runs the scheduled task.
- The application host can be automated, but a HIS administrator must resolve failed verification items.
- Passwords do not rotate automatically and are never written to `.env`, scripts, logs, or Git.
- Task Scheduler starts the normal `uvicorn` process at Windows startup. A Windows Service wrapper is not required for v0.1.0.
