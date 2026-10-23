---
status: accepted
---

# ADR 0002: organize the modular monolith by business capability

Quirebase remains a single deployable Python application, organized around business capabilities.
Web and MCP are inbound adapters: they parse transport input, invoke business operations and
format results. Business operations own permissions, database transactions, Audit Events,
durable enqueue and Search synchronization.

The [Module policy](../architecture/modules.md) defines current owners, interfaces and allowed
imports. The shared [ORM mapping](../architecture/orm-ownership.md) keeps relationship and
mapper-order knowledge local to persistence while capability modules own business behavior.

## Considered options

- Horizontal `models/schemas/services/providers` layering was rejected because
  common feature changes would still require traversal across many shallow
  Modules.
- Separately deploying frontend and backend servers was rejected because it adds
  an operational boundary without resolving transaction and permission coupling.
- Long-term legacy import shims were rejected because the project has no
  published plugin ABI and the shims would become shallow Modules.

## Consequences

- Architecture and behavior tests verify the shared authorization, transaction and
  side-effect responsibilities.
- Business Modules must not depend on FastAPI.

## Implementation notes

- Business failures are raised as typed exceptions
  (`quirebase.core.errors`) and converted to HTTP responses by the Web layer
  and to workflow outcomes by the durable runtime, never rendered inside Modules.
- Capability modules define DBOS workflows; CLI bootstrap registers them for the worker.
- Core supplies the Local/S3 object interface described in
  [ADR 0007](0007-obstore-object-data-plane.md).
