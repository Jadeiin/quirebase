---
status: accepted
---

# Advanced Alchemy persistence boundaries

Quirebase needs consistent persistence configuration, model conventions, persistent values and file
descriptions while business Modules own authorization, concurrency and durable recovery. We use
SQLAlchemy as the persistence foundation and Advanced Alchemy as a toolkit, with native asynchronous
business operations retaining transaction and object-lifecycle ownership. This reuses persistence
mechanisms while keeping their adoption governed by Quirebase's domain, database and recovery
contracts.

Persistence configuration, representations and transaction behavior are defined in the
[implementation record](../architecture/advanced-alchemy-implementation.md), with ownership and
Interface rules in [Module policy](../architecture/modules.md) and the runtime decision in
[ADR 0006](0006-async-runtime-and-persistence.md).

## Consequences

- Core supplies shared persistence infrastructure; business modules own their reused mechanisms,
  and inbound adapters own transport projections and conversion.
- Business Modules retain validation, Workspace lineage, transaction completion, Audit Events,
  Search synchronization and durable work. File descriptors describe objects; commands and workflows
  own transfer, retries, idempotent completion and reference-safe cleanup.
- Toolkit behavior is established by dependency characterization. Application, concurrency and
  object-lifecycle contracts establish Quirebase's guarantees and must be checked when affected
  dependency behavior changes.
