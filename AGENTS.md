# Quirebase repository guidance

## Agent skills

### Implementation policy

Before implementing or refactoring, use the repository's rules for simplicity, incremental
delivery, compatibility and dependency choices.
See `docs/agents/implementation.md`.

### Issue tracker

Issues are tracked in GitHub Issues (via `forge` CLI).
See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, and `wontfix` states.
See `docs/agents/triage-labels.md`.

### Domain and module architecture

Before changing business behaviour, capability ownership, cross-package dependencies or test
seams, use the root domain glossary, repository decisions and module policy.
See `docs/agents/domain.md`.
