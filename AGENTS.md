# Quirebase repository guidance

## Alpha compatibility policy

Quirebase is alpha software. Optimize changes for the current design. Add compatibility layers for
an earlier release's APIs, stored data, or persisted durable workflow inputs and checkpoints only
when the task or an explicit release plan requires them. Preserve correctness within the current
version, including concurrent requests, retries, and durable recovery.

## Agent skills

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
