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

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `forge pr` equivalents:

- **Read a PR**: `forge pr view <number> --comments` and `forge pr diff <number>` for the diff.
- **List external PRs for triage**: `forge pr list --state open -o json` then keep only `authorAssociation` of `CONTRIBUTOR`, `FIRST_TIME_CONTRIBUTOR`, or `NONE` (drop `OWNER`/`MEMBER`/`COLLABORATOR`).
- **Comment / label / close**: `forge pr comment <number> --body "..."`, `forge pr edit <number>`, `forge pr close <number>`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either — resolve with `forge pr view 42` and fall back to `forge issue view 42`.

## When a skill says "publish to the issue tracker"

Create an issue with `forge issue create`.

## When a skill says "fetch the relevant ticket"

Run `forge issue view <number> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `forge issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map. Add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: Add an edge via `forge api` (or use `Blocked by: #<n>, #<n>` in the body). A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`forge issue list --state open -o json`), drop any with an open blocker or an assignee; first in map order wins.
- **Claim**: `forge issue edit <n> --assignee @me` — the session's first write.
- **Resolve**: `forge issue comment <n> --body "<answer>"`, then `forge issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
