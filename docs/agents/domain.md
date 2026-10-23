# Domain documentation

Before changing Quirebase architecture or business behaviour:

1. Read the root `GLOSSARY.md`.
2. Read relevant records under `docs/adr/`.
3. For architecture or cross-package changes, read `docs/architecture/modules.md`.
4. Use the terms defined in `GLOSSARY.md` in code, tests and documentation.
5. Surface conflicts with accepted ADRs instead of silently overriding them.

Quirebase has one bounded context. Keep definitions in `GLOSSARY.md`, architectural choices in
ADRs, and detailed behavior contracts in `docs/architecture/`.

## ADR format

Record an ADR for a decision that is hard to reverse, surprising without context and the result of
a real trade-off. Start with a short decision title and one to three sentences stating the context,
chosen approach and reason. Put status in YAML frontmatter when needed; add considered options or
consequences only when they explain meaningful trade-offs or non-obvious effects. Keep detailed API,
UI, database and recovery contracts under `docs/architecture/`, linked from the ADR, and update
references when moving those contracts.
