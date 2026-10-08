# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues in `lemonicefate/clinic-antiviral-tool`. Use the `gh` CLI for all issue operations.

## Conventions

- Create an issue with `gh issue create --title "..." --body "..."`.
- Read an issue with `gh issue view <number> --json number,title,body,labels,comments`.
- List issues with `gh issue list --state open --json number,title,body,labels,comments` and appropriate filters.
- Apply or remove labels with `gh issue edit <number> --add-label "..."` or `--remove-label "..."`.
- Close an issue with `gh issue close <number> --comment "..."`.
- Add issue comments with `gh issue comment <number> --body "..."`.

## Pull requests as a triage surface

No. Pull requests are not treated as feature requests for this repository.

## When a skill says "publish to the issue tracker"

Create or update a GitHub issue in this repository. Keep `SPEC.md` in the repository as the canonical local implementation document even when the same specification is published to GitHub.
