# 4. Research Intelligence, Model Context Protocol (MCP), and Agent Architecture

Date: 2026-08-15

## Status

Proposed

Tracking: [#1 Plan staged Research Intelligence and MCP capabilities](https://github.com/Jadeiin/quirebase/issues/1)

## Context

Scholarly workflows increasingly leverage Large Language Models (LLMs) and autonomous agents for literature review, semantic synthesis, equation/table extraction, and automated annotation. However, integrating AI must not violate the core architectural invariants established in ADR-0001 (Deferred Integrations & Ports/Adapters) and ADR-0002 (Modular Monolith Organization by Business Capabilities).

Specifically:
1. Core business modules (`library`, `documents`, `access`, `projects`) must remain pure, decoupled from vendor LLM SDKs and prompt engineering logic.
2. External AI tools (such as Claude Desktop, Cursor, IDE plugins, CLI agents) require a standardized protocol to inspect libraries, query full-text, and create annotations.
3. PDF text extraction for research papers requires structural fidelity—preserving LaTeX mathematical formulas, markdown tables, section hierarchies, and figure captions.

## Candidate Direction

If the proposal is validated, Quirebase would establish two decoupled layers for AI and
language model integration. The concrete libraries, protocols, transports, and module
interfaces remain subject to staged research and implementation decisions tracked in #1.

### 1. Domain Capability: `quirebase.intelligence`
A dedicated capability module providing:
- **Structural Extraction (`extraction.py`)**: Uses `pymupdf4llm` (with fallback to structured PyMuPDF extraction) to transform a **File Revision** into structured Markdown with LaTeX math formulas (`$...$`) and Markdown tables.
- **Semantic Chunking (`chunking.py`)**: Header-aware document chunking for Retrieval-Augmented Generation (RAG).
- **Research Agent (`agent.py`)**: Type-safe research assistant agent built on **Pydantic AI**, providing structured outputs (`ItemSummary`, `LiteratureReview`, `SynthesisOutput`) and tool calling across Quirebase capabilities.

### 2. Protocol Adapter: `quirebase.mcp` (Model Context Protocol)

An inbound protocol adapter built on the official Python `mcp` 2.x SDK. Remote access uses
Streamable HTTP; standard input/output is reserved for a client launching a trusted local process.
The superseded HTTP+SSE transport is not a new implementation target.

The server exposes a fixed allowlist covering the ordinary User's core research workflows:

| Capability | Tools | Deliberate limits |
| --- | --- | --- |
| Library | `library.search`, `library.get_item`, `library.create_item`, `library.update_item` | Search is limited to 25 Items per page; writes reuse Item ownership and optimistic version checks |
| Projects | `projects.list`, `projects.get`, `projects.create`, `projects.add_item`, `projects.remove_item`, `projects.set_member`, `projects.remove_member` | Project Role checks remain authoritative, including owner-only membership changes |
| Documents | `documents.list` | Returns revision and attachment metadata, never object keys, bytes or extracted text |
| Annotations | `annotations.list`, `annotations.create`, `annotations.update`, `annotations.delete` | Reuses revision, Item and Project visibility plus annotation ownership/version rules |
| Organization | `tags.list`, `tags.add_to_item`, `tags.remove_from_item`, `tags.set_for_item`, `discussions.list`, `discussions.add`, `discussions.delete` | Reuses editable-Item and message ownership rules |
| Discovery and citation | `discovery.search`, `citations.format_item` | Discovery is marked open-world and never receives the inbound API Token |

The allowlist deliberately omits administrative and operational capabilities. It also omits file
upload/download and extracted full text: the current full text is an unstructured plain-text field
and needs a bounded structured-document interface before it becomes an MCP capability. Resources
and prompts are not required for this tool-oriented slice. API Tokens do not carry separate
read/write or per-tool scopes; adding a tool changes the server allowlist for every valid token and
therefore requires its own authorization and behaviour review.

Every handler derives the User from the verified API Token and invokes the existing business
Interface, which continues to apply System Role, Project Role, Item ownership, transaction and
Audit Event rules. Tool input never selects the authorization subject.

Programmatic Adapters bind protocol, operation and API Token/client identity through the Audit
Module interface. A successful data-changing operation records one business Audit Event enriched
with that invocation source; it does not also record a protocol event. Security-sensitive reads
such as Discovery retain their dedicated business Audit Event, while ordinary successful reads do
not create persistent per-call records. MCP validation failures, authorization failures and other
protocol outcomes likewise do not create Audit Events; operational diagnostics for those paths
belong in redacted logs and metrics rather than the immutable business audit history. Tool
arguments, bearer credentials and result content are never added to Audit Events.

For Streamable HTTP, the Accounts Module issues revocable, expiring API Tokens and stores only their
hashes. MCP accepts them only as `Authorization: Bearer` credentials; browser Login Sessions and
CSRF tokens are not MCP credentials, query-string tokens are rejected, and an inbound token is
never passed to an upstream Provider. The raw token is shown only once at creation. This deliberately
does not implement MCP OAuth authorization discovery: deployment and client configuration are
simpler, at the cost of interactive OAuth acquisition, delegated clients and step-up scopes.

```mermaid
graph LR
  subgraph ExternalEcosystem[External Agents]
    Claude[Claude Desktop / Cursor]
  end

  subgraph Adapters[Protocol & Web Adapters]
    MCP[quirebase.mcp Inbound Adapter]
    CLI[quirebase mcp CLI]
    Web[Web Chat Interface]
  end

  subgraph IntelligenceCapability[quirebase.intelligence Module]
    Agent[Pydantic AI Research Agent]
    Extractor[PyMuPDF4LLM Structured Extractor]
    Chunker[Semantic Chunker]
  end

  subgraph CoreCapabilities[Core Business Modules]
    Library[quirebase.library]
    Documents[quirebase.documents]
    LibrarySearch["Library Search (quirebase.search)"]
    Access[quirebase.access]
  end

  Claude -->|MCP Protocol / JSON-RPC| MCP
  CLI -->|stdio| MCP
  Web --> Agent

  MCP --> CoreCapabilities
  Agent --> CoreCapabilities
  Agent --> Chunker
  Extractor --> Documents
```

## Expected Consequences If Accepted

- Core library and storage operations remain 100% independent of AI dependencies.
- External agent ecosystems can read and write to Quirebase without custom integration code.
- Research papers preserve mathematical equations and structured tables when processed by LLMs.
- Agents can run with either local models (e.g. Ollama) or cloud providers via configurable runtime settings.
- Protocol and transport behaviour follows the official `mcp` SDK rather than a Quirebase JSON-RPC implementation.
- API Tokens expire, can be revoked, and immediately lose access when their User is deactivated.
- Tool availability is server-wide; User- and object-level authorization remains authoritative.

The protocol, transport and authorization findings are recorded in
[`docs/research/2026-08-30-mcp-server-integration.md`](../research/2026-08-30-mcp-server-integration.md).
