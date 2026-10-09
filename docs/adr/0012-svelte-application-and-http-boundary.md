---
status: accepted
---

# Static Svelte application and unified HTTP API

Quirebase's authenticated research UI needs shared client state and interactive layouts while FastAPI
already owns the business operations and runtime. We serve a static Svelte 5/TypeScript application
built by SvelteKit from FastAPI, with browsers, scripts and MCP sharing `/api/v1` through explicit
Login Session or Bearer authentication. This supplies a richer client without introducing a second
server or duplicating application behavior and response contracts.

Frontend composition, localization, credential selection, Origin checks, error contracts, PDF
integration and delivery constraints are defined in the
[application and HTTP boundary contracts](../architecture/application-http-boundary.md).

## Considered options

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
- Direct Bits UI primitives plus an ad-hoc global stylesheet were rejected because component
  behavior, theme semantics and product patterns would continue to evolve as separate systems.
- shadcn-svelte was rejected because copied source components transfer long-term design-system and
  upgrade ownership into this repository, which is not useful differentiation for Quirebase.
- CSS-only component kits were rejected because dialogs, menus, tooltips and other composite
  controls still need a separate accessible behavior layer.
- Manual headless EmbedPDF component composition was rejected in favor of `@embedpdf/svelte-pdf-viewer`
  because the bundled viewer provides standard responsive viewing layouts, thumbnails, zoom and
  navigation while still exposing the plugin registry for Quirebase's annotation bridging, write
  queues and command filtering.

## Consequences

- One service and release artifact contain the complete application; frontend builds must precede
  Python wheel or container construction.
- An explicit Authorization header selects Bearer authentication without cookie fallback. Unsafe
  cookie-authenticated requests require the configured same-origin check; browsers keep HTTP-only
  Login Session cookies rather than storing API Tokens.
- Skeleton owns general UI primitives and semantic themes, Lingui owns gettext-based frontend
  localization, and the bundled EmbedPDF viewer owns standard PDF viewing. Their dependency and
  upgrade costs require bundle-size and accessibility checks.
- The application, generated API documentation and non-page responses have distinct security-header
  requirements, including the application's same-origin WASM and worker allowances.
- The alpha cutover removes Jinja pages, form routes and synchronizer tokens. Future PWA or desktop
  packaging can reuse the static application and FastAPI boundary.
