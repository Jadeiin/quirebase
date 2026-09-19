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
state, and URL parameters for shareable state. Skeleton 5 is the sole general-purpose design
system: its semantic theme tokens and Tailwind CSS 4 utilities own visual styling, while Skeleton
Svelte components backed by Zag own accessible interactive primitives. Feature views compose those
primitives with a small set of Quirebase product patterns in `src/lib/design`; they do not define a
parallel application-wide button, field, card, menu, dialog, tooltip, or status system. SvelteKit's
filesystem router owns application URL matching and parameter parsing; a persistent authenticated
route layout owns the Login Session, locale and application shell. Route pages remain thin
adapters over feature views instead of reimplementing domain behavior or maintaining a catch-all
client dispatcher. Item and Admin workspace sections are literal child routes rather than one
parameterized route with a client-side switch, so every section ships its own chunk and owns the
queries and mutations it reads; the shared Item layout sits in a route group that keeps the PDF
reader outside the workspace shell. Feature views live under `src/lib/features/<feature>` as typed TanStack queries,
mutations and presentational components (`Library` and `ProjectWorkspace` are feature
orchestrators, not root-level views); Item and Admin workspaces are composed by their route
layouts, `ItemWorkspaceHeader`, `AdminShell` and literal section pages. Cross-feature product
patterns (`ConfirmDialog`,
`PromptDialog`, `StatusNotice`, `EmptyState`, `Toast`) live in `src/lib/design`. Destructive or
text-confirmed actions use those dialog patterns; `window.confirm` and `window.prompt` are not
used. Frontend localization is owned by Lingui. Committed gettext PO catalogs are the
translation source of truth; a strict Svelte extractor records literal messages and marked dynamic
labels, and Lingui generates runtime catalogs during checks and builds. Python gettext catalogs
and template localization helpers are removed. `src/lib/locale.ts` is the single locale inventory.
Language is a browser display preference like theme or sidebar state: the Frontend Adapter detects
the stored `quirebase:locale` value with Lingui's `@lingui/detect-locale` and falls back to the
browser language, so `/session` carries no locale and the API owns no locale cookie, no locale
request body and no `Accept-Language` negotiation. Switching the language persists the preference
immediately and synchronizes other tabs through the `storage` event. ICU interpolation values and
plural forms flow through `i18n._` rather than message-fragment composition.

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

The version prefix is owned by the API composition root in web/api/routes.py; capability
routers declare relative paths, with administration composed below /api/v1/admin. OpenAPI
operation IDs are generated centrally through FastAPI's generate_unique_id_function as
<capability module>.<endpoint function>. Endpoint decorators do not hand-author operation IDs,
so the same generated identifier is consumed by OpenAPI, frontend tooling and the curated MCP
projection.

Every `/api/v1` failure uses one JSON contract containing a stable machine-readable `code`, an
English `message` for programmatic clients, optional validation `fields`, and optional structured
`meta`. Request validation never echoes submitted input values. The Svelte adapter translates known
error codes for the active locale and uses a feature-specific localized fallback for unknown codes;
it does not display backend messages directly.

The public session and Invitation endpoints use the same Origin rule for unsafe requests. API
responses may aggregate several domain read models when a workspace needs one coherent initial
payload; business behavior remains behind the existing Module interfaces.

Durable workflows are UI first-class citizens through a global Workflow Center owned by the
application shell: feature code registers a started workflow ID with a label instead of awaiting
it inside the initiating component, a shell-level tray polls the typed workflow status query and
keeps the job visible across client-side navigation, and terminal failures surface through the
global toast pattern. Callers that need post-completion refreshes await the center's settled
promise, which resolves from the same polled status; dismissing a job hands remaining waiters
back to direct polling so local busy states always settle. The tray limit only ever prunes
terminal jobs: active jobs are retained regardless of the cap, so a tracked workflow with
outstanding waiters can never be evicted from the polling set. Status polling whose retries are
exhausted fails the job through the same settled path, so a missing workflow or persistent
server error rejects waiters and surfaces a failure toast instead of leaving the initiating
mutation busy indefinitely.

Jinja, templates, HTML form routes, CSRF synchronizer tokens, `web/views`, `web/json` and the
legacy asset tree are removed. Application deep links are handled by the static SPA fallback.
This is an alpha, forward-only cutover and does not retain compatibility routes for deleted page
or form URLs.

The PDF reader uses EmbedPDF's bundled Svelte viewer package (`@embedpdf/svelte-pdf-viewer`) and Svelte
lifecycle, superseding custom headless plugin assembly. PDFium is a declared frontend dependency
imported as a Vite asset URL; Vite emits a content-hashed, same-origin WASM asset. Quirebase does not
copy PDFium to a fixed vendor path or manage the EmbedPDF engine lifecycle imperatively. EmbedPDF
remains isolated under `src/lib/pdf`; its domain-specific viewer controls and UI schemas are customized
to disable unsupported commands (such as callout annotations) and keep search and page navigation
integrated with the Svelte workspace, but do not become a second general-purpose design system.

## Consequences

- A single Quirebase service and artifact still contains the complete application.
- `/api/v1` response and authorization behavior is the shared browser, agent and script
  contract; transport-specific credential selection remains explicit.
- The application shell's CSP allows the same-origin application, `wasm-unsafe-eval` and
  EmbedPDF's Blob worker while forbidding remote scripts and frames. `/docs`, `/redoc` and the
  OAuth2 redirect page receive a separate documentation policy that hashes their inline
  initialization scripts and exempts the external jsDelivr assets, FastAPI favicon and ReDoc
  Google Fonts those generated pages load. API, OpenAPI and MCP responses receive the general
  security headers without either policy.
- Web is the source product. PWA, Tauri and Capacitor may package or enhance the same static
  application later without changing the FastAPI boundary.
- Deployments must build the frontend before constructing the Python wheel or container.
- Quirebase owns one named Skeleton theme, including the complete semantic color ramps,
  typography and radii. Product code consumes those tokens instead of raw palette values for
  general interface states.
- Reactive Svelte state (runes) lives in `.svelte`, `.svelte.js` or `.svelte.ts` modules only;
  plain TypeScript modules never use runes, so the static build cannot ship an initializer that
  crashes the application shell at startup.
- Skeleton Svelte brings Zag's state machines and a broader dependency graph. Production builds
  must continue to tree-shake unused components, and frontend upgrades must check generated JS and
  CSS sizes as well as accessibility behavior. The application-shell bundle budget in
  `frontend/scripts/check-bundle-budget.ts` is raised deliberately when a maintained dependency
  replaces hand-rolled code: once for the Toast, Popover and Tabs state machines, once for
  `openapi-fetch`, which replaced the hand-written API client plumbing while keeping the
  `apiRequest` contract, and once for ICU-capable localization. The same script enforces per-route
  budgets for the Library, Import, Item and Admin graphs so section ownership changes are measured
  rather than assumed. Temml is imported only by the lazily loaded `rich-text-math` chunk, so the
  many routes that never render inline math do not eagerly ship it.
- This alpha cutover is forward-only: the former Bits UI dependency and global `.button`, `.field`,
  `.panel` and related compatibility classes are removed in the same change.

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
