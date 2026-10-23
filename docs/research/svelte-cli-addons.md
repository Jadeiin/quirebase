# Svelte CLI add-ons for Quirebase

Researched 2026-09-16 against the official Svelte CLI documentation and the Svelte CLI source at
commit [`03fc69b`](https://github.com/sveltejs/cli/tree/03fc69b9a811b8e2213b4e9b0070766952408c99).

## Adoption outcome

ESLint and Prettier are configured in `frontend/` and run through `bun run --cwd frontend lint`.
Tailwind, Vitest, Playwright and the static adapter are also present. The table records how the
researched add-ons fit the current application; implementation and checks are documented in
[Testing](../TESTING.md).

## Current fit

| Add-on | Current repository state | Decision |
| --- | --- | --- |
| **eslint** | Flat configuration, TypeScript/Svelte rules and a frontend lint CI step are installed. | The [official add-on](https://svelte.dev/docs/cli/eslint) supplies the baseline; project rules enforce current UI and authorization conventions. |
| **prettier** | Formatting scripts, Svelte and Tailwind integration are installed. | The [official add-on](https://svelte.dev/docs/cli/prettier) coordinates formatting with ESLint. |
| **tailwindcss** | Already configured with Tailwind 4, `@tailwindcss/vite`, the Vite plugin, and `@import "tailwindcss"` in `app.css`. | **Already present; do not rerun.** The CLI add-on would reproduce that setup. Its optional typography/forms plugins should be added only when the UI actually adopts their opinionated styling; Quirebase currently owns semantic tokens and form styles ([docs](https://svelte.dev/docs/cli/tailwind), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/tailwindcss.ts)). |
| **vitest** | Vitest 5, jsdom, scripts, and focused TypeScript tests already exist and run in CI. | **Already present; do not rerun now.** The official add-on can create separate server/unit and browser/component projects using `vitest-browser-svelte` and Playwright ([docs](https://svelte.dev/docs/cli/vitest), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/vitest-addon.ts)). Its current source targets Vitest 4 while this repository is already on Vitest 5, so applying it blindly would regress the declared version. Adopt a version-compatible browser-component project later when shared interactive components need tests below the full E2E seam. |
| **playwright** | Installed, configured for the static production build, populated with application tests, and run with Chromium in CI. | **Already present; do not rerun.** The generated demo/config would be less specific than the existing FastAPI-boundary test setup ([docs](https://svelte.dev/docs/cli/playwright), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/playwright.ts)). |
| **sveltekit-adapter** | `@sveltejs/adapter-static` is configured with `fallback: "index.html"`, matching FastAPI `app.frontend()` and SPA deep links. | **Already present; keep static.** The add-on merely selects and configures an adapter. Node, Cloudflare, Vercel, and Netlify adapters conflict with the accepted single FastAPI service/no Node server boundary ([docs](https://svelte.dev/docs/cli/sveltekit-adapter), [ADR 0012](../adr/0012-svelte-application-and-http-boundary.md)). |
| **storybook** | No stories or Storybook configuration; the current component layer includes shared design patterns and feature views. | **Defer.** Storybook is a component workshop and the add-on delegates to Storybook's SvelteKit initializer ([docs](https://svelte.dev/docs/cli/storybook), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/storybook.ts)). Reconsider once Quirebase has a stable reusable component layer whose visual states are expensive to cover through Playwright alone. |
| **paraglide** | Lingui is installed and frontend localization ownership is an accepted decision. PO catalogs own messages; locale is a browser preference. | **Avoid.** Paraglide would create a second i18n system plus Inlang project data, generated messages, Vite integration, URL rerouting and SvelteKit server hooks ([docs](https://svelte.dev/docs/cli/paraglide), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/paraglide.ts)). Improve the existing Lingui catalog/extraction workflow instead. Lingui itself is not an official `sv add` option in the current list ([official add-on list](https://svelte.dev/docs/cli/sv-add)). |
| **better-auth** | Authentication, Login Sessions, API Tokens, cookie security, Origin checks, and audit provenance are FastAPI/Python responsibilities. | **Avoid.** The add-on generates a SvelteKit auth backend with a Drizzle database adapter and password/OAuth pages ([docs](https://svelte.dev/docs/cli/better-auth)); this would duplicate the security boundary rejected by ADR 0012. |
| **drizzle** | SQLAlchemy/Alembic, SQLite/PostgreSQL, transactions, and business persistence belong to the Python modular monolith. | **Avoid.** The add-on intentionally puts database access into SvelteKit server files ([docs](https://svelte.dev/docs/cli/drizzle)), while this static SPA has no production SvelteKit server. |
| **mdsvex** | No frontend-authored Markdown content or content-site route exists. | **Avoid for now.** mdsvex is a Markdown/Svelte preprocessor and the add-on changes `svelte.config.js` ([docs](https://svelte.dev/docs/cli/mdsvex)); it does not help the authenticated workspace. Reconsider only for a concrete, frontend-owned documentation/content feature. |
| **experimental** | Quirebase uses a static production build. | **Avoid.** This add-on enables experimental Svelte/SvelteKit flags and can move Kit and its adapter to `next` prereleases ([docs](https://svelte.dev/docs/cli/experimental)). No current requirement needs those features. |

## AI tools, MCP, and DevTools

The current CLI has no separate **MCP** or **DevTools** add-on in its official list
([`sv add` list](https://svelte.dev/docs/cli/sv-add)). MCP is one option inside **ai-tools**: that
add-on can install the official Svelte plugin or selected MCP, skill, and sub-agent files for
supported clients ([ai-tools docs](https://svelte.dev/docs/cli/ai-tools),
[source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/ai-tools.ts)).

Treat `ai-tools` as an optional contributor-environment enhancement, not an application dependency
or required CI input. Quirebase already has a repository-specific `AGENTS.md`; generated generic
instructions must not replace its domain, migration, and architecture rules. A contributor who
wants the Svelte MCP should configure it for their supported client deliberately. There is no CLI
DevTools action to take at present.
