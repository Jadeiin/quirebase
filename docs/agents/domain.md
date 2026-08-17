# Domain documentation

Before changing Quirebase architecture or business behaviour:

1. Read the root `CONTEXT.md`.
2. Read relevant records under `docs/adr/`.
3. For architecture or cross-package changes, read `docs/architecture/modules.md`.
4. Use the terms defined in `CONTEXT.md` in code, tests and documentation.
5. Surface conflicts with accepted ADRs instead of silently overriding them.

Quirebase is currently a single-context repository.

The change is ready when every affected domain term matches `CONTEXT.md`, every changed Module
has an explicit owner and allowed dependency direction, and unresolved conflicts have been
surfaced rather than encoded as accidental implementation choices.
