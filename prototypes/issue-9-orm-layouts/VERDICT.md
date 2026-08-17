# Verdict

Keep the ORM mapping centralized. Do not split `models.py` into capability packages.

Both prototypes loaded complete representative metadata, configured cross-capability mappers,
created a scratch SQLite schema and avoided importing Web. Capability-local mappings therefore
are technically possible, but they do not deepen a business Module:

- Alembic needs an aggregator that imports every mapping owner (7 prototype mapping modules
  versus 2 for the centralized layout).
- `Item`/`FileRevision`, `PdfAnnotation`/`Project`, and the many `User` foreign keys remain
  persistence relationships spanning business ownership. Moving their classes changes file
  placement but does not remove that coupling.
- Business operations already own permissions, transactions, auditing and synchronization.
  Exposing mapping packages as their interfaces would reduce depth and invite ORM relationships
  to become cross-Module contracts.

Production should retain one side-effect-free persistence mapping and add an enforced
class-to-owner registry in the architecture suite. Alembic should import that mapping directly,
without Web or business package facades.

Facade inventory found one definite policy violation: `quirebase.search` re-exports the concrete
`SQLiteSearchIndex` and `PostgreSQLSearchIndex` adapters. Other facade removals should be limited
to symbols with no external caller and no caller-facing use-case/result/error role. Internal
Python paths need no compatibility shims.
