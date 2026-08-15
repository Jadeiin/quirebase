# ADR 0001: capability evolution and controlled external integrations

Status: accepted.

## Context

During early project initialization, external integrations (such as OIDC/SSO, email notifications, public programmatic APIs, MCP/AI scholarly assistants, and heavy worker pipelines like OCR) were deferred to prioritize core domain modeling, database integrity, and modular monolith transaction boundaries. 

With core capabilities now established (ADR 0002) and bounded external scholarly providers integrated (ADR 0003), Quirebase adopts an architecture-first framework for progressive capability expansion rather than blanket deferrals.

## Integration Principles & Architectural Guardrails

1. **Port & Adapter Seam Discipline**:
   External integrations (Identity providers, notification transports, object storage backends, AI/scholarly assistants) must connect as inbound or outbound Adapters behind strict domain Ports (Interfaces). Core business modules (`library`, `documents`, `access`, `projects`) must remain independent of external transport frameworks and vendor SDKs.

2. **Programmatic & Open Interfaces (REST, OpenAPI, MCP)**:
   Programmatic endpoints (RESTful APIs, OpenAPI schemas, CLI commands, and MCP tooling) are treated as first-class inbound adapters at the HTTP/transport seam. They must invoke existing business module operations directly, sharing the exact same authorization (`access`), validation, concurrency control, and audit event rules as the Web presentation layer.

3. **Enterprise & Federated Authentication (OIDC / OAuth2)**:
   Institutional SSO and external OAuth2/OIDC providers are modeled as authentication providers within the `accounts` capability. External identities map to local `User` entities with threat-modeled session management and audit trails, preserving local access control invariants.

4. **Asynchronous Worker & Background Pipelines**:
   Compute-intensive or high-latency tasks (OCR, embeddings, bulk PDF metadata extraction, webhook/email notifications) must run asynchronously via the durable `pipeline` worker with lease management, retry limits, and sandboxed execution, never blocking synchronous HTTP request lifecycles.

5. **Bounded Outbound Network Invariants**:
   All outbound network interactions must enforce fixed destination allowlists or strict scheme validation, request timeouts, non-redirect policies, bounded payload size limits, and security auditing without leaking user search queries or raw credentials.

## Consequences

- New capabilities (e.g. REST APIs, OIDC, Webhooks, AI assistant tools) can be progressively introduced via dedicated capability modules or adapters without violating modular monolith boundaries.
- The repository enforces these invariants through architectural tests, static compliance gates, and ADRs for major new capability areas.

