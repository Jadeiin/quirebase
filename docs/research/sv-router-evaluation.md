# Svelte SPA router evaluation

Date: 2026-09-16

## Recommendation

Do **not** add `sv-router`, Routify, or `svelte-spa-router` to Quirebase. Continue the cutover to
SvelteKit's filesystem router.

All three packages are legitimate routers for a plain Svelte/Vite SPA. Quirebase, however, already
depends on SvelteKit 2.70.3 and `adapter-static`, and has selected SvelteKit routing in
[ADR 0012](../adr/0012-svelte-application-and-http-boundary.md). Adding one of them would leave
SvelteKit responsible for the build and fallback shell while a second runtime owns URL matching,
navigation, layouts, preloading, and errors. That is duplicate infrastructure rather than a missing
capability.

The current branch already expresses the useful boundary directly:

- `src/routes/(app)/+layout.svelte` is the persistent authenticated application shell;
- `(public)` and `(app)` are URL-transparent route groups;
- item and admin routes use typed dynamic parameters and `src/params` matchers;
- `src/routes/+error.svelte` is the application error/404 boundary;
- `adapter-static({ fallback: 'index.html' })` produces the SPA shell FastAPI serves as its
  frontend fallback;
- `src/routes/+layout.ts` sets `ssr = false`, so SvelteKit does not introduce a production Node
  backend.

## What SvelteKit already supplies

SvelteKit calls its router a filesystem router. It generates route-local types, gives pages typed
`params`, preserves shared nested layouts during navigation, walks upward through `+error.svelte`
boundaries, and uses route groups without adding URL segments
([routing](https://svelte.dev/docs/kit/advanced-routing),
[route files, layouts, errors, and generated types](https://svelte.dev/docs/kit/routing)). Dynamic
segments can be constrained by typed matchers in `src/params`; failed matches continue to another
route or 404 ([parameter matching](https://svelte.dev/docs/kit/advanced-routing#Matching)). These
are exactly the mechanisms Quirebase needs for `itemSection` and `adminSection`.

For client navigation, SvelteKit owns normal anchors, `goto`, `beforeNavigate`, `onNavigate`,
`afterNavigate`, `preloadCode`, and `preloadData`
([navigation API](https://svelte.dev/docs/kit/$app-navigation)). Link options support code/data
preloading, replace-state, scroll, focus, and full reload behavior
([link options](https://svelte.dev/docs/kit/link-options)). `page.url` provides reactive URL and
query state ([application state](https://svelte.dev/docs/kit/$app-state)). Vite/SvelteKit splits
route code and imports the code for a destination during navigation; no per-page lazy wrapper is
required.

The static deployment is a supported SvelteKit configuration, not a reason to replace its router.
Official SPA guidance specifies `ssr = false` plus `adapter-static` with a fallback document, and
describes that fallback as loading the app and navigating to the requested route
([SPA mode](https://svelte.dev/docs/kit/single-page-apps),
[`adapter-static`](https://svelte.dev/docs/kit/adapter-static)). FastAPI's fallback fulfils the host
rewrite part of that contract. SvelteKit 2.70 also exposes pathname and hash router modes in its
official configuration type; Quirebase should retain pathname/history routing because FastAPI
already supplies deep-link fallback
([router configuration](https://svelte.dev/docs/kit/configuration#router)).

## Capability comparison

| Concern | SvelteKit 2.70 | `sv-router` 0.19 | Routify 3.6 | `svelte-spa-router` 5.1 |
| --- | --- | --- | --- | --- |
| Intended host | SvelteKit app, including client-only static SPA | Plain Svelte 5 SPA | Svelte/Vite router/framework layer | Small Svelte 5 hash SPA |
| Filesystem routes | Built in, `+page` convention | Optional Vite plugin/CLI; generates `.router` | Core feature, generated route tree | No; JS object/`Map` |
| Nested persistent layouts / groups | Built in; `(group)` does not alter URL | `layout.svelte`; `_group` does not alter URL | Modules/layout composition and multiple routers | Nested routers, but no filesystem layout hierarchy |
| Dynamic params | Generated route-local `PageProps`; matchers constrain values | Generated path/param types, but params accept arbitrary segment strings; no matcher equivalent documented | Runtime params; published declarations expose `any` | Runtime `params`; no path-derived static types |
| Query params | Reactive `page.url`; update through navigation/history APIs | Writable reactive `searchParams`, plus typed `search` accepted by generated navigation | Parsed/stringified by configurable `queryHandler` and merged into route params | Hash query is exposed as an unparsed string |
| Guards / navigation lifecycle | `beforeNavigate`, `onNavigate`, `afterNavigate`; layout/page data lifecycle | `beforeLoad`, `afterLoad`, `onPreload`, `onError`; navigation blockers | `beforeUrlChange`, `afterUrlChange`, preloads | `wrap` preconditions and route events |
| Errors / 404 | Hierarchical `+error.svelte` boundaries and default 404 | Explicit catch-all; `onError` callback, not an error component boundary | Application-defined fallback/error handling | Ordered `*` catch-all; application-defined error component |
| Code splitting / preload | Route chunks automatic; link and programmatic preload | `.lazy.svelte`/`allLazy`; hover, viewport, prediction, programmatic preload | Dynamic imports, configurable bundling and prefetch/preload | Manual `wrap({ asyncComponent: () => import(...) })`; no documented preload layer |
| URL mode | Pathname/history, or hash mode | History or hash base | Browser history and configurable URL reflectors | Hash only |
| Quirebase fit | **Direct match** | Duplicates Kit; useful only if Kit is removed | Duplicates Kit and has a Vite peer mismatch | Regresses clean URLs, layouts, types, and error handling |

The `sv-router` comparison is based on its official documentation for
[why it exists](https://sv-router.dev/guide/why),
[file routing setup](https://sv-router.dev/guide/file-based/manual-setup),
[layouts](https://sv-router.dev/guide/file-based/layouts),
[dynamic routes](https://sv-router.dev/guide/file-based/dynamic-routes),
[hooks](https://sv-router.dev/guide/file-based/hooks),
[search params](https://sv-router.dev/guide/file-based/search-params),
[code splitting](https://sv-router.dev/guide/file-based/code-splitting), and
[preloading](https://sv-router.dev/guide/file-based/preloading). Its own rationale explicitly says
SvelteKit remains the correct choice when SvelteKit is wanted, while `sv-router` fills the gap for
Svelte SPAs that do not want the meta-framework. Quirebase does not need SvelteKit server routes or
SSR, but it already benefits from its client router, compiler integration, generated types, error
boundaries, and static adapter.

Routify advertises file-based routing, dynamic imports, customizable bundling, prefetching,
preloads/guards, multiple routers, history restoration, SSR and static export on its
[official site](https://routify.dev/). Those are broad capabilities, but Quirebase does not need
multiple simultaneous routers or a second routing framework. More concretely, its current npm
manifest allows Vite only through major 7, while this branch uses Vite 8.3.0; adopting it would
start with an unsupported peer range
([npm manifest](https://registry.npmjs.org/@roxi%2Froutify/latest)).

`svelte-spa-router` is deliberately hash-based. Its official README documents route objects,
ordered matching, `wrap`-based lazy imports and guards, nested routers, and an unparsed query string
inside the hash
([official repository](https://github.com/ItalyPaleAle/svelte-spa-router)). It is maintained for
Svelte 5, but replacing clean URLs such as `/item/:id/metadata` with hash URLs and reconstructing
layouts/types/error boundaries manually would be a regression for Quirebase.

## Maintenance, compatibility, and adoption snapshot

These figures are snapshots, not quality scores. Download totals include indirect and legacy use.

| Package | Current release and compatibility | Maintenance surface | Adoption snapshot | License |
| --- | --- | --- | --- | --- |
| `sv-router` | 0.19.0, published 2026-09-11; peer `svelte: ^5` | One npm maintainer; repository pushed 2026-09-15 | 18,215 npm downloads in the preceding month; 215 GitHub stars | MIT |
| `@roxi/routify` | 3.6.4, published 2025-09-16; Svelte 3/4/5, Vite 3–7 peer range | One npm maintainer; repository pushed 2026-01-07 | 151,012 monthly downloads; 1,986 stars | MIT |
| `svelte-spa-router` | 5.1.1, published 2026-06-25; peer `svelte: ^5` | Two npm maintainers; repository pushed 2026-08-23 | 237,025 monthly downloads; 1,608 stars | MIT |

Sources: official npm manifests and registry histories for
[`sv-router`](https://registry.npmjs.org/sv-router/latest),
[`@roxi/routify`](https://registry.npmjs.org/@roxi%2Froutify/latest), and
[`svelte-spa-router`](https://registry.npmjs.org/svelte-spa-router/latest); official npm download
API snapshots for
[`sv-router`](https://api.npmjs.org/downloads/point/last-month/sv-router),
[`@roxi/routify`](https://api.npmjs.org/downloads/point/last-month/@roxi/routify), and
[`svelte-spa-router`](https://api.npmjs.org/downloads/point/last-month/svelte-spa-router); official
GitHub repository metadata for
[`sv-router`](https://api.github.com/repos/colinlienard/sv-router),
[Routify](https://api.github.com/repos/roxiness/routify), and
[`svelte-spa-router`](https://api.github.com/repos/ItalyPaleAle/svelte-spa-router).

## Decision rule

Reconsider a standalone router only if Quirebase deliberately removes SvelteKit and becomes a
plain Vite/Svelte app. In that different architecture, `sv-router` would be the strongest of these
three for generated type-safe Svelte 5 routes. As long as SvelteKit remains the selected build and
static adapter, its filesystem router is the smallest and best-integrated choice.
