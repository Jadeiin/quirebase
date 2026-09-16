# ADR 0012: Svelte application and unified HTTP API boundary

Status: accepted.

## Context

Quirebase's authenticated workspace has outgrown server-rendered pages. Its Library, Item,
Project, PDF, Import and administration experiences need shared client state, responsive
application layouts and accessible interactive primitives. FastAPI already owns the business
use cases, persistence, sessions, programmatic API, file streaming and durable workflows, so a
second server runtime would duplicate the application boundary.

The existing `/api/v1` surface was originally authenticated only by API Tokens. A separate
browser-only JSON hierarchy would duplicate routes and response contracts. The prior Jinja
layer also coupled Login Sessions to synchronizer-token generation and HTML form conventions.

## Decision

Quirebase uses a Svelte 5 and TypeScript application built by SvelteKit with the static adapter.
FastAPI's `app.frontend()` serves `frontend/build` and its immutable assets as low-priority
routes. The build remains outside the Python source tree and Hatch includes it as wheel data for
releases; there is no frontend installation/copy script. There is no Node server, SvelteKit server
endpoint, server action or second domain implementation in production.

The Svelte application uses TanStack Svelte Query for remote state, Svelte runes for local UI
state, URL parameters for shareable state, Tailwind CSS 4 with semantic CSS tokens for styling,
and headless accessible component primitives. SvelteKit's filesystem router owns application URL
matching and parameter parsing; a persistent authenticated route layout owns the Login Session,
locale and application shell. Route pages remain thin adapters over feature views instead of
reimplementing domain behavior or maintaining a catch-all client dispatcher. Frontend
localization is owned by Lingui. Committed gettext PO catalogs are the translation source of
truth; a strict Svelte extractor records literal messages and marked dynamic labels, and Lingui
generates runtime catalogs during checks and builds. Python gettext catalogs and template
localization helpers are removed.

Both browsers and programmatic clients use `/api/v1`:

- An explicit `Authorization` header selects Bearer API Token authentication. Invalid,
  unsupported or expired credentials fail with `401`; authentication never falls back to a
  Login Session cookie.
- Without `Authorization`, protected routes authenticate the Login Session cookie.
- Cookie-authenticated `POST`, `PUT`, `PATCH` and `DELETE` requests require an `Origin` whose
  normalized scheme, host and effective port exactly match `QUIREBASE_EXTERNAL_ORIGIN` when it is
  configured, or the direct request origin otherwise. TLS reverse-proxy deployments configure the
  external origin explicitly rather than trusting forwarding headers from arbitrary peers. Missing,
  opaque or malformed origins fail with `403`.
- Bearer requests do not require an Origin and retain programmatic Audit Event provenance.
- Browser code never stores an API Token. Login Session cookies remain HTTP-only.

The public session and Invitation endpoints use the same Origin rule for unsafe requests. API
responses may aggregate several domain read models when a workspace needs one coherent initial
payload; business behavior remains behind the existing Module interfaces.

Jinja, templates, HTML form routes, CSRF synchronizer tokens, `web/views`, `web/json` and the
legacy asset tree are removed. Application deep links are handled by the static SPA fallback.
This is an alpha, forward-only cutover and does not retain compatibility routes for deleted page
or form URLs.

The PDF reader uses EmbedPDF's native Svelte headless packages and Svelte lifecycle. PDFium is a
declared frontend dependency imported as a Vite asset URL; Vite emits a content-hashed,
same-origin WASM asset. Quirebase does not copy PDFium to a fixed vendor path or manage the
EmbedPDF engine lifecycle imperatively.

## Consequences

- A single Quirebase service and artifact still contains the complete application.
- `/api/v1` response and authorization behavior is the shared browser, agent and script
  contract; transport-specific credential selection remains explicit.
- CSP allows the same-origin application, `wasm-unsafe-eval` and EmbedPDF's Blob worker while
  forbidding remote scripts and frames.
- Web is the source product. PWA, Tauri and Capacitor may package or enhance the same static
  application later without changing the FastAPI boundary.
- Deployments must build the frontend before constructing the Python wheel or container.

## Rejected alternatives

- Retaining Jinja as an application shell was rejected because static Svelte output already
  supplies the shell and session bootstrap is an API concern.
- A separate browser API namespace was rejected because the same use cases and most wire
  contracts serve both credential types.
- SvelteKit SSR and server actions were rejected because they introduce a second server/runtime
  without benefiting the authenticated workspace.
- Browser-stored API Tokens were rejected because they weaken the existing Login Session
  boundary.
- A fixed copied `vendor/pdfium.wasm` was rejected because it bypasses Vite's dependency graph,
  hashing and asset URL handling.
