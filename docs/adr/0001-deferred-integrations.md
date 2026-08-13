# ADR 0001: controlled network metadata; defer OCR and public extension APIs

Status: accepted for the first complete release.

OCR, OIDC, email, a public REST API, MCP, AI features and a third-party plugin SDK are not required for the current MVP. Adding them now would introduce external process execution, credential storage and long-lived compatibility contracts before the core domain is stable.

Identifier-based metadata lookup and explicit online scholarly search are accepted as bounded exceptions. DOI queries use Crossref with a DataCite fallback; PMID, arXiv, ISBN, and OpenAlex use fixed provider APIs. Search uses a fixed provider allowlist, validated field/operator clauses, bounded pages and response sizes, and no user-controlled destination URLs. Requests have deadlines, no redirects, an identifying user agent, optional provider credentials, explicit user initiation and a preview-before-commit transaction. Lookup and search events are audited without storing search terms. Publisher full-text retrieval and automatic PDF downloading remain out of scope.

The application keeps internal storage and search ports but publishes no plugin ABI. Future OCR must run as an optional sandboxed worker adapter and record page-coordinate provenance. Authentication integrations must be threat-modelled separately. Each deferred capability requires its own ADR and acceptance tests before implementation.
