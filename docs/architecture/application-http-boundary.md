# Application and HTTP boundary contracts

This specification expands the [static application and shared HTTP API](../adr/0012-svelte-application-and-http-boundary.md).
[Module policy](modules.md) defines capability ownership and dependency direction.

## Application and protocol contract

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
layouts, `ItemHeader`, `AdminShell` and literal section pages. Cross-feature product
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

Skeleton's Svelte component stylesheet is loaded alongside the core primitives. Navigation owns
sidebar, mobile and section-link presentation; SvelteKit still owns URL selection and `aria-current`.
Pagination owns page changes through first/previous/next/last controls, a Page Size selector and the
current result range. Library keeps server-side Sort By choices alongside view controls in its results
toolbar; Project Item lists expose them in the pagination bar. Library, Project directory and Project
Item lists keep filters, page, Page Size and sorting
in the URL and reset to page one when size, sorting or filters change. Tabs owns local Account
and Item-action sections, plus URL-selected Tools modes. Combobox owns
searchable Tag, Project and Workspace selection, Listbox owns the visible CSL style choices,
SegmentedControl owns duplicate criteria and the Library’s automatic/table/list view choice,
Collapsible owns the Library filter disclosure, and Progress owns indeterminate loading feedback.
Short fixed choices and native form inputs keep Skeleton's CSS primitives. Native details and
asynchronous Tag assignment actions retain their current product semantics.

Library uses a native table on desktop and a compact list on narrow screens. TanStack Svelte
Table owns column visibility, constrained resizing and row-selection mechanics; Query and the URL
retain server filtering, sorting and pagination. Only the loaded page is selectable. A changed list
query clears selection, and successful refreshes remove selected IDs that are no longer displayed.
Authoritative access/not-found failures discard cached lists for that Project and clear selection;
transient refresh failures may retain the last loaded rows.
Titles remain ordinary Item links. The independent `preview` URL parameter opens a nonmodal Item
overview loaded on demand. Previous/next follows server ordering across pages, preserves filter
drafts, and clears bulk selection only when the loaded page changes. Lazy inline organization edits
only the previewed Item; removing a Project association requires confirmation of Annotation and Reply
deletion. Bulk Tag removal and removal from the current Project capture their submitted targets;
Project removal requires the same confirmation. Selection toolbar actions and Item menus in both
views and preview share one action dialog. Each request captures its target scope and export
preferences; retries preserve the submitted payload. Copy and download retain selection. Clipboard
failures retain generated citation text for retry, manual copy or download without another request.
Dismissed operations settle without taking focus, and failures remain available to review.
Bulk mutation requests use five canonical actions, including `delete_items`, with action-specific
required fields and reject unrelated fields. Destructive-action warnings and confirmation belong
to the dialog; Item and Project DELETE requests carry no confirmation body. Project and Workspace
name matching stays local to their dialogs.
Item sections and PDF links carry a validated,
same-Workspace Library return URL with the filters, sorting, page and Item focus anchor. Closing a
preview restores its trigger or current result. Preview autofocus preserves focus moved to another
control during asynchronous loading. Density, optional
columns, widths and the automatic/table/list view choice are local User-scoped display preferences.
Automatic view follows viewport width; an explicit view choice overrides it. Preview code loads on demand.
Author credits, publication titles and publication years refine the submitted Library query, replace
the same facet and reset paging while preserving other filters, sort, page size and preview target.
Item summaries carry ordered structured author names with exact filter values; no row-level lookup
or parsing of joined names is needed. Only the year portion of a displayed date acts as a filter.
Library sorting supports title, first author, publication, publication date, date added and date
modified in both directions; the toolbar groups a field selector with its direction toggle, synchronized
with sortable table headers through the URL.
Author order uses the first named Author’s surname or literal name, falling back to the first named
Editor; organization credits use their literal names. Missing names and dates always sort last.
Publication dates compare their supplied
calendar parts, with shorter precision first in ascending order; times do not distinguish the same calendar day.

Client interactions distinguish four sources of state:

| State                                         | Owner              | Transition rule                                                                                     |
| --------------------------------------------- | ------------------ | --------------------------------------------------------------------------------------------------- |
| Raw text and unsaved form fields              | Local draft        | Keep whitespace and newer edits until an explicit reset or restored filter replaces them.           |
| Submitted filters, criteria and list position | URL                | Queries consume these values; dependent changes such as a new filter and page one publish together. |
| Submitted operation criteria and input        | Operation snapshot | Capture on explicit submission; later draft or URL edits do not retarget an in-flight operation.    |
| Remote results, errors and fetch status       | TanStack Query     | Do not mirror results or infer active work from the absence of data.                                |

The Web UI Adapter's `src/lib/navigation/url-draft.svelte.ts` owns the repeated search-draft
synchronization used by Tools' Tag filter and Citation Style search. Features retain their URL
parsers and build the complete destination. The shared mechanism publishes trimmed text after
200 ms using replacement navigation, preserves raw whitespace and newer edits when that publication
is acknowledged, and pauses publication while navigation is in progress. Back/Forward cancels
unpublished edits and restores the destination's filter even when its value equals the previous
URL's value. An external filter change replaces the draft; an unrelated URL correction retains it.
Timers belong to the view's lifetime. A cancelled publication retains the draft without an automatic
retry loop; the next edit can publish again.

Automatic page clamps replace history only after a successful, settled read establishes the last
page. User pagination pushes history. Administration exposes separate `setPage` and `correctPage`
actions so query effects cannot accidentally select the user-navigation policy.

Tools stores the active mode, duplicate criteria, Tag filter/page/size and Citation Style search
in its URL. Returning to or refreshing a duplicate view never initiates a scan. Only the explicit
check captures submitted criteria and calls the disabled query's `refetch`; URL criteria changes
leave that in-flight query attached to the submitted criteria. Revisiting stale results does not
refetch. Leaving the view may cancel the request; returning requires another explicit check.
A pending query with idle fetch status is an idle check, not a loading indicator. Tag and Citation
Style reads are enabled only for their active tool. Pending Tools commands prevent duplicate
submission without blocking independent filter or tab navigation. Citation Style installation
captures its input and clears only an unchanged submitted draft on success; newer form edits remain.

The shared administration filter bar and Overview, Users, Audit and
Workflows pagination store their state in the URL; switching sections starts the default view,
while browser history restores its previous filter values. The filter bar keeps unsubmitted drafts
when only the page or Page Size changes, including automatic page corrections. A changed submitted
filter, section switch or Back/Forward restores the destination's filter values. Clear filters
explicitly resets drafts even when the URL already contains the default filters.
Passwords, credentials and mutation drafts remain local.

Remote reads distinguish loading, failure, successful empty results and populated results.
`QueryError` provides localized, task-local failure feedback and a retry action; a failed read
cannot produce a successful empty-result message. Cached content may remain visible when a
refresh fails, accompanied by the failure feedback. Modal commands retain their target and
draft on failure, display errors inside the active modal, and close after success. Pending
commands disable repeated submission and dismissal. File selection includes visible action
text in its accessible name and associates supplementary instructions as a description.

List content must shrink and wrap valid long words; declaring grid columns alone is insufficient.
Secondary text is checked against both page and panel backgrounds, and tab text is checked in
selected and focused states. Browser acceptance includes representative English and Chinese,
light and dark modes, long content, failed reads/commands, and URL refresh/history recovery.
Temporal regressions are covered through the shared draft Interface and browser consumers:
debounce followed by Back/Forward, edits during URL publication or a pending command, command
success/failure, an in-flight scan's criteria changes, leaving an unfinished scan, stale-tab return,
and automatic clamps followed by user pagination and Back.

Administrative event and workflow lists use server-side limit/offset pages. Workflow totals come
from DBOS state aggregates, and overview statistics cover the complete record set independently of
the displayed event page.

`src/lib/design/DateField.svelte` adapts Skeleton DatePicker to ISO strings at year, month or day
precision. Metadata chooses that precision; Library and Discovery choose only years. Calendar
anchors never supply missing date components to persisted metadata or search requests. Zag 1.43
filters typed separators using the locale even with custom format/parse callbacks and repairs an
invalid blur value using its focused date. The ISO input therefore overrides those input handlers,
uses DatePicker's focus API for valid drafts, and uses native form validity for invalid drafts;
calendar navigation and selection remain Skeleton's responsibility. Popups inside a Dialog portal
to that Dialog with fixed positioning, keeping them within its focus and accessibility boundary
without being clipped by the action panel.

Tag listing uses bounded `limit`/`offset` pages with a filtered total, literal case-folded name
search and an optional Workspace-scoped `tag_id` filter for restoring a selection. Tools requests
20 Tags per page; Library and merge selectors request 25 options only when opened, with debounced
server search and explicit loading of additional pages. A selected Tag is resolved independently
so deep links and renamed selections remain usable outside the first option page. Library counts
assignments only for Tags in the requested page, preserving zero counts without aggregating the
whole taxonomy. Tag mutations invalidate Tag lists, option searches and selected-Tag queries.
Library Project selectors likewise request 25 options only when opened, with debounced server search
and explicit pagination inside the picker. Opening Library, expanding its filters or focusing the
Add to Project dialog does not fetch the Project directory. A selected Project is resolved by ID
independently of option pages; Add to Project waits for a successful detail read with current manage
permission before submission.

## Workspace navigation and settings

The Workspace directory at `/workspace` is a global destination. Without a Workspace ID, the
application shell offers global destinations rather than linking Library, Projects and other
Workspace tasks back to the directory. The brand menu owns Workspace switching and the settings
entry. Workspace creation is an explicit dialog action; its owner requirements come from the
creation-availability projection, and assigning another owner does not grant the creator content
access.

`src/lib/features/workspaces` owns Workspace directory and settings presentation, typed queries,
mutations and their cache invalidation. It consumes the Workspace context/API, design patterns,
localization and Workflow Center; authorization stays in Access and the HTTP API. Route pages are
thin adapters. A shared settings layout identifies the current Workspace and links to literal
General, Members, Invitations and Advanced routes. Each task loads its own data and owns its
drafts, pending state and feedback. Members includes either the ordinary directory or governance
projection, selected by the server-authored read decision. Advanced holds maintenance and
lifecycle operations, with permanent deletion last. Direct visits to unavailable sections explain
their unavailability without fetching restricted data.

General settings also contains self-service Leave workspace, projected as `workspace_member.leave`
for active non-owner members of active, unfrozen Workspaces. Owner and read-only states explain
their prerequisite instead of offering an unauthorized command. `WorkspaceView.current_membership_id`
identifies the caller's current generation. The confirmation snapshots it and the displayed name;
`POST /workspaces/{workspace_id}/leave` accepts `{membership_id}` and can end only that same current
membership of the authenticated User. Submission prevents dismissal and duplicate commands;
failures retain the confirmation and refresh authoritative Workspace availability, including recovery
after a lost response. Success clears a matching default preference, returns to `/workspace`,
evicts that Workspace's cached projections and refreshes the directory and pending invitation count.
Recovery after a lost response performs the same cleanup once the API confirms the Workspace
is unavailable, including all directory pages and the brand menu's Workspace options. Pending
Workspace reads are cancelled before eviction so their responses cannot repopulate the cache.
Failed leaves directly read the captured Workspace, independently of query observers and route
lifetime, even if navigation happens during that read. An unavailable response enters the same cleanup
path as a successful leave; other read failures retain uncertainty and never replay the command.
Finishing an operation after navigation to another Workspace does not redirect that new context.

Directory and member search, page and page size live in URL parameters. Search and page-size
changes reset to page one; settled results clamp an out-of-range page. Unsubmitted drafts remain
local and are not overwritten by background refreshes. A Workspace-ID change retains the existing
keyed Provider isolation. Governance mutations invalidate the shared Workspace projections once,
including dependent research views; starting reindex registers its scoped job with the global
Workflow Center.

Read sections distinguish loading, failure, no matches and empty data, with local retries for
failures. Invitation read failures do not remove a newly created one-time link. Only successful
revocation of that exact invitation retires its displayed link. Confirmation dialogs identify the
affected Workspace or member, retain failures for retry and block dismissal while a submission is
pending. Permanent Workspace deletion requires the current Workspace name in the confirmation
dialog; the API still enforces archive and retention conditions. ESLint rejects native browser
dialogs in both TypeScript and Svelte product code.

Workspace UI changes describe the user task, account/Workspace/instance scope, entry and URL,
required server decisions, success/failure/empty states and representative acceptance scenario.
Browser checks cover task routes, refresh/back navigation, cancellation and failure recovery;
representative English desktop and Chinese narrow-screen scenarios check long content,
accessibility and layout width and attach review screenshots. These complement the existing
membership, lifecycle and cross-Workspace recovery checks.

## Deployment and frontend constraints

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
- Reactive Svelte state (runes) lives in `.svelte`, `.svelte.js` or `.svelte.ts` modules only
  (including Vite-compiled `.svelte.test.ts` test modules);
  plain TypeScript modules never use runes, so the static build cannot ship an initializer that
  crashes the application shell at startup.
- Production builds must tree-shake unused components. Frontend upgrades check generated JS/CSS
  sizes and accessibility behavior. `frontend/scripts/check-bundle-budget.ts` checks the shell,
  route bundles and opened tools; budgets may be adjusted for justified dependency or feature
  changes. DatePicker, the schema editor and the PDF reader stay outside the application shell.
  Temml loads through the lazy `rich-text-math` chunk when inline math is rendered.

## Received Workspace Invitations

Workspaces owns recipient reads and admission; Access owns the `workspace_invitation.read`
and `workspace_invitation.accept` system decisions with the `own` relation. The authenticated
`/api/v1/me/workspace-invitations` collection requires no Workspace membership. It returns only
that User's pending invitations, in descending creation/ID order with limit/offset pagination.
The pending count includes invitations temporarily blocked by Workspace freeze or archive.
The separate Workspace settings collection remains the governance view of sent invitations.
Neither read exposes raw tokens or token hashes.

`GET /me/workspace-invitations/{invitation_id}` reports the recipient's pending, accepted,
revoked or expired state. Workspaces projects `can_accept`, `can_open` and an optional
`unavailable_reason` from current lifecycle, membership and Access decisions. An accepted
invitation alone never authorizes opening a Workspace: a current active membership and
`workspace.read` are required. Missing and other recipients' invitations return the same 404.

`POST /me/workspace-invitations/{invitation_id}/accept` shares the single-use admission command
with token-based acceptance. The command reloads and locks the active User, then the Workspace,
then the invitation; it creates a new membership and records Audit in the same transaction.
It neither activates suspended memberships nor restores terminated generations or Project
participation. A repeated acceptance fails; reconciliation reads do not replay the command.
The standard HTTP credential and cookie Origin checks apply to all three endpoints.

Received invitations live in a conditional section above the Workspace directory at `/workspace`,
available without any Workspace membership. When there are no pending invitations, the section
and its Workspace menu shortcut are hidden. A positive count appears beside the section heading,
on the menu trigger and in the shortcut, which links to `/workspace#invitations`.
Counts represent pending invitations, not unread notifications. Query keys include the User ID;
`invitation_page` and `invitation_page_size` live in the URL independently of the directory's
search and pagination. A submitted accept retains its target,
prevents duplicate commands through reconciliation, and reads authoritative invitation state
after either success or failure. A lost response can therefore become an accepted result.
If that read also fails, the next action checks status without resending acceptance. A missing,
revoked or expired invitation is explained; failure never appears as a successful empty inbox.
Read failures show a local Retry even when the pending count is unknown. The last acceptance
keeps its result and explicit Open Workspace action visible until dismissed or navigated away;
the section does not disappear during reconciliation. Uncertain results cannot be dismissed.
Successful reconciliation refreshes pending counts, the Workspace directory/options and
Workspace projections. Acceptance keeps the default Workspace preference unchanged; only the
explicit Open Workspace action changes it. The mobile header is a banner landmark with a
named Account settings link.
