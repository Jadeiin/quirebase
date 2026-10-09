---
status: accepted
---

# ADR 0006: native async runtime and persistence

## Context

Provider access, database operations, file delivery and background Jobs coordinate concurrent I/O.
Their resource lifetimes, cancellation and transaction responsibilities need one consistent runtime
model across Quirebase and Inquiro.

## Decision

Quirebase/Inquiro uses native asynchronous Interfaces throughout its I/O paths. Provider access,
persistence, Library Search, Web/API, MCP and Pipeline workers participate in that runtime model.
Resources have explicit owners and lifetimes, including completion, cancellation and failure.

Core owns database connectivity and session provisioning. Each request or Job owns its database
session and transaction context; concurrent tasks use separate sessions. Business commands own
persistence and transaction completion within their Modules.

External Provider I/O runs outside business database transactions. A subsequent mutation establishes
current authority and concurrency conditions before committing its state and side effects.

Pure domain operations execute synchronously. Blocking local work runs through an explicit execution
boundary appropriate to its resource requirements. Inbound adapters coordinate calls to the owned
business Interfaces.

[ADR 0014](0014-advanced-alchemy-persistence.md) defines the persistence toolkit's role within these
runtime and ownership boundaries.

## Consequences

I/O composition, cancellation and resource cleanup follow one asynchronous model. Business Modules
control transactional outcomes, while Core supplies common runtime infrastructure. Provider,
application and database contracts verify resource lifetime, concurrent execution, failure handling
and durable recovery.

Runtime bindings and execution mechanisms are documented in the
[implementation record](../architecture/advanced-alchemy-implementation.md).
