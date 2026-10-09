# Advanced Alchemy persistence boundaries

Status: accepted.

## Context

Quirebase's persistence needs include common model conventions, persistent values, file descriptions
and directory queries. Domain policy, Workspace lineage, transactions, concurrency and durable
object ownership belong to the Modules that own the business capabilities.

## Decision

Quirebase uses SQLAlchemy as its persistence foundation and Advanced Alchemy as a toolkit for
configuration, model/value types, file descriptions and independent query and conversion utilities.
Business operations are Module-owned functions using the native asynchronous runtime defined in
[ADR 0006](0006-async-runtime-and-persistence.md).

### Module responsibilities

Core owns shared persistence configuration and reusable infrastructure tools. Business commands
use SQLAlchemy directly and own authorization facts, lifecycle rules, transaction completion,
Audit Events, Search synchronization and durable work.

Shared mechanisms are justified by actual reuse, independent responsibility and sufficient
complexity. They stay inside their owning Module. Pure domain operations accept domain values;
business Module Interfaces expose the use cases their callers need. Inbound adapters own transport
projections and conversion.

### Workspace mutations

Every mutation of Workspace-owned state establishes valid authority, target lineage and concurrency
protection appropriate to the operation within its business transaction. Commands derive mutation
targets from established ownership facts and coordinate data and side effects under their defined
transaction and recovery guarantees. Database constraints provide the final integrity boundary.

### Persistent values and object ownership

Business Modules own validation and interpretation of persistent domain values. Infrastructure
provides their storage representation.

File descriptions represent persisted objects. Business commands and durable workflows own the
physical object lifecycle, including ownership transfer, retry, idempotent completion and
reference-safe cleanup. Durable boundaries carry application-owned values that express the
workflow's inputs and recovery state.

## Consequences

Business Modules express their use cases directly and share mechanisms where reuse warrants them.
Core supplies consistent persistence infrastructure. Toolkit adoption follows these ownership
boundaries and the domain's product, database and recovery contracts.

Dependency characterization establishes the toolkit behavior the application relies on. Application,
concurrency and object-lifecycle contracts establish Quirebase's guarantees. Dependency upgrades
require reviewing affected behavior and validating those contracts.

Concrete representations, tools, configuration and database operations are documented in the
[implementation record](../architecture/advanced-alchemy-implementation.md).
