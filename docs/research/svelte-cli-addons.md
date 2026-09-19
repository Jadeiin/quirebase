# Svelte CLI add-ons for Quirebase

Researched 2026-09-16 against the official Svelte CLI documentation and the Svelte CLI source at
commit [`03fc69b`](https://github.com/sveltejs/cli/tree/03fc69b9a811b8e2213b4e9b0070766952408c99).

## Recommendation

Add **ESLint** and **Prettier** now. Quirebase already has the useful runtime and test add-ons in
substance: Tailwind CSS, Vitest, Playwright, and `adapter-static`. Do not run those add-ons again
just to make the project look CLI-generated; their generated defaults would overlap with working,
project-specific configuration.

After checkpointing the current cutover, the intended command is:

```sh
bunx sv add eslint prettier --cwd frontend --install bun
```

Review the generated diff, then make `bun run --cwd frontend lint` a CI check. `sv add` is
explicitly designed to update an existing project, accepts multiple add-ons and supports both
`--cwd` and Bun; `sv` does not need to become a permanent project dependency
([`sv add`](https://svelte.dev/docs/cli/sv-add),
[`sv` FAQ](https://svelte.dev/docs/cli/faq)).

## Current fit

| Add-on | Current repository state | Decision |
| --- | --- | --- |
| **eslint** | No ESLint dependency, config, script, or frontend lint CI step. `svelte-check` is a type/component diagnostic tool, not a replacement for lint rules. | **Add now.** The official add-on installs `eslint-plugin-svelte`, TypeScript support, a flat config, a `lint` script, and editor recommendation ([docs](https://svelte.dev/docs/cli/eslint), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/eslint.ts)). Keep the generated recommended baseline initially; add project rules only when a demonstrated defect warrants them. |
| **prettier** | No frontend formatter or checked formatting convention. Python's Ruff formatter does not cover TypeScript, Svelte, or CSS. | **Add now.** The official add-on supplies scripts, ignore/config files and `prettier-plugin-svelte`; because Tailwind is installed it also adds the official Tailwind Prettier integration, and it coordinates with ESLint through `eslint-config-prettier` ([docs](https://svelte.dev/docs/cli/prettier), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/prettier.ts)). Run both add-ons together, then format once as a separately reviewable mechanical change. |
| **tailwindcss** | Already configured with Tailwind 4, `@tailwindcss/vite`, the Vite plugin, and `@import "tailwindcss"` in `app.css`. | **Already present; do not rerun.** The CLI add-on would reproduce that setup. Its optional typography/forms plugins should be added only when the UI actually adopts their opinionated styling; Quirebase currently owns semantic tokens and form styles ([docs](https://svelte.dev/docs/cli/tailwind), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/tailwindcss.ts)). |
| **vitest** | Vitest 5, jsdom, scripts, and focused TypeScript tests already exist and run in CI. | **Already present; do not rerun now.** The official add-on can create separate server/unit and browser/component projects using `vitest-browser-svelte` and Playwright ([docs](https://svelte.dev/docs/cli/vitest), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/vitest-addon.ts)). Its current source targets Vitest 4 while this repository is already on Vitest 5, so applying it blindly would regress the declared version. Adopt a version-compatible browser-component project later when shared interactive components need tests below the full E2E seam. |
| **playwright** | Installed, configured for the static production build, populated with application/cutover tests, and run with Chromium in CI. | **Already present; do not rerun.** The generated demo/config would be less specific than the existing FastAPI-boundary test setup ([docs](https://svelte.dev/docs/cli/playwright), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/playwright.ts)). |
| **sveltekit-adapter** | `@sveltejs/adapter-static` is configured with `fallback: "index.html"`, matching FastAPI `app.frontend()` and SPA deep links. | **Already present; keep static.** The add-on merely selects and configures an adapter. Node, Cloudflare, Vercel, and Netlify adapters conflict with the accepted single FastAPI service/no Node server boundary ([docs](https://svelte.dev/docs/cli/sveltekit-adapter), [ADR 0012](../adr/0012-svelte-application-and-http-boundary.md)). |
| **storybook** | No stories or Storybook configuration; most current components are route-sized workspace views rather than isolated design-system components. | **Defer.** Storybook is a component workshop and the add-on delegates to Storybook's SvelteKit initializer ([docs](https://svelte.dev/docs/cli/storybook), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/storybook.ts)). Reconsider once Quirebase has a stable reusable component layer whose visual states are expensive to cover through Playwright alone. |
| **paraglide** | Lingui is installed and frontend localization ownership is an accepted decision. Locale selection currently comes from the authenticated FastAPI session. | **Avoid.** Paraglide would create a second i18n system plus Inlang project data, generated messages, Vite integration, URL rerouting and SvelteKit server hooks ([docs](https://svelte.dev/docs/cli/paraglide), [source](https://github.com/sveltejs/cli/blob/03fc69b9a811b8e2213b4e9b0070766952408c99/packages/sv/src/addons/paraglide.ts)). Improve the existing Lingui catalog/extraction workflow instead. Lingui itself is not an official `sv add` option in the current list ([official add-on list](https://svelte.dev/docs/cli/sv-add)). |
| **better-auth** | Authentication, Login Sessions, API Tokens, cookie security, Origin checks, and audit provenance are FastAPI/Python responsibilities. | **Avoid.** The add-on generates a SvelteKit auth backend with a Drizzle database adapter and password/OAuth pages ([docs](https://svelte.dev/docs/cli/better-auth)); this would duplicate the security boundary rejected by ADR 0012. |
| **drizzle** | SQLAlchemy/Alembic, SQLite/PostgreSQL, transactions, and business persistence belong to the Python modular monolith. | **Avoid.** The add-on intentionally puts database access into SvelteKit server files ([docs](https://svelte.dev/docs/cli/drizzle)), while this static SPA has no production SvelteKit server. |
| **mdsvex** | No frontend-authored Markdown content or content-site route exists. | **Avoid for now.** mdsvex is a Markdown/Svelte preprocessor and the add-on changes `svelte.config.js` ([docs](https://svelte.dev/docs/cli/mdsvex)); it does not help the authenticated workspace. Reconsider only for a concrete, frontend-owned documentation/content feature. |
| **experimental** | Quirebase is already making a large frontend cutover and depends on a predictable static build. | **Avoid.** This add-on enables experimental Svelte/SvelteKit flags and can move Kit and its adapter to `next` prereleases ([docs](https://svelte.dev/docs/cli/experimental)). No current requirement needs those features. |

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

## Proposed order

1. Run the combined ESLint + Prettier add-on against `frontend/` after the current cutover is
   checkpointed, then inspect every generated file.
2. Add `lint` to the root scripts and frontend CI; decide whether format checking belongs in that
   script or as a separate `format:check` command based on the generated scripts.
3. Apply one standalone formatting commit so behavioral review remains readable.
4. Revisit Vitest browser component testing and Storybook only after reusable design components
   emerge. Keep all server-owning and duplicate-stack add-ons out of this static Web adapter.
