# Issue tracker: GitHub (via forge CLI)

Issues and specs for this repo live as GitHub issues. Use the `forge` CLI for all operations.

## Conventions

- **Create an issue**: `forge issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `forge issue view <number> --comments` (or `forge issue view <number> -o json`).
- **List issues**: `forge issue list --state open -o json` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `forge issue comment <number> --body "..."`
- **Apply / edit labels**: `forge issue edit <number> --label "..."`
- **Close**: `forge issue close <number>`

Infer the repo from `git remote -v` — `forge` does this automatically from `origin`.

## Pull requests

Feature requests are tracked as issues. Read a PR with `forge pr view <number> --comments`
and its changes with `forge pr diff <number>`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `forge pr view 42` and fall back to `forge issue view 42`.
