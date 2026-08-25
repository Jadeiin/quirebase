# Implementation policy

Use these rules when implementing or refactoring Quirebase:

- **Simplest complete change**: choose the smallest implementation that satisfies the current
  issue or specification, accepted ADRs and operational requirements. Add abstractions,
  configuration and indirection only for a demonstrated requirement.
- **Working increments**: keep the system working end to end at each mergeable increment. Add new
  capability on top of verified behaviour instead of landing disconnected scaffolding.
- **Explicit compatibility**: remove obsolete internal paths in the same change instead of adding
  unrequested aliases, fallbacks or shims. Preserve a boundary only when an issue, specification or
  accepted ADR makes it a compatibility commitment; follow the repository's migration policy for
  persistent data and schemas.
- **Reuse before expansion**: inspect the documentation and types of existing dependencies before
  writing common functionality or adding a package. Prefer a well-maintained library when it
  reduces total complexity or improves reliability, and evaluate its security, maintenance,
  licence and Module-boundary impact before adoption.
- **Durable architecture**: align long-lived seams with the domain glossary, accepted ADRs and
  Module ownership policy. Surface a needed architectural decision instead of encoding a stopgap
  that is already intended for replacement.
- **Prior art**: for unfamiliar product behaviour or interface design, inspect established
  products or libraries before inventing a convention, then adopt only the parts that fit
  Quirebase's domain and constraints.

The change is ready when the requested behaviour works end to end, every new abstraction and
dependency has a current caller or requirement, obsolete internal paths are removed, and any
compatibility or architectural choice is traceable to the governing issue, specification or ADR.
