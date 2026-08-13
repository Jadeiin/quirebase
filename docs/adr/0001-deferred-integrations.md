# ADR 0001: controlled network metadata; defer OCR and public extension APIs

Status: accepted for the first complete release.

OCR, OIDC, email, a public REST API, MCP, AI features and a third-party plugin SDK are not required for the current MVP. Adding them now would introduce external process execution, credential storage and long-lived compatibility contracts before the core domain is stable.

Identifier-based metadata lookup is now accepted as a bounded exception. DOI queries use Crossref with a DataCite fallback, PMID queries use NCBI ESummary, and arXiv IDs use the arXiv Atom API. The user supplies an identifier, never a URL; provider origins and HTTPS paths are fixed in code. Requests have deadlines, response-size limits, no redirects, an identifying user agent, optional provider credentials, explicit user initiation and a preview-before-commit transaction. Lookup events are audited. Arbitrary metadata search, publisher full-text retrieval and automatic PDF downloading remain out of scope.

The application keeps internal storage and search ports but publishes no plugin ABI. Future OCR must run as an optional sandboxed worker adapter and record page-coordinate provenance. Authentication integrations must be threat-modelled separately. Each deferred capability requires its own ADR and acceptance tests before implementation.
