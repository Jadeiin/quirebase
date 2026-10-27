# Paraglide JS under a gettext/PO source-of-truth constraint

Date: 2026-09-16

## Adoption outcome

Quirebase uses Lingui with committed PO catalogs, `lingui-for-svelte` macros/extraction and generated
TypeScript runtime messages. Ordinary TypeScript uses official Core macros and the Babel extractor.
Locale is a browser preference managed with `@lingui/detect-locale`.
[Testing](../TESTING.md#frontend-localization) documents the active workflow.

The Svelte integration was migrated on 2026-10-27; the dated comparison below describes the earlier
project-local adapter. See the [migration evaluation](2026-10-26-lingui-for-svelte-upstream.md).

The PO requirement decided against Paraglide: the researched official Svelte add-on and storage
plugin use Inlang Message Format JSON. Supporting PO would require a maintained storage plugin or
bidirectional converter. The investigation below compares those costs against Lingui's native PO
support using the dated upstream sources.

## 1. What is canonical in Paraglide

There are two layers to distinguish:

- The Paraglide compiler opens an **Inlang Project** and compiles its normalized messages into
  JavaScript functions.
- A storage plugin imports from and exports to the repository's editable translation files.

Paraglide is therefore format-pluggable in principle. Its official file-format documentation says
that any format can be used **if an Inlang plugin exists**. However, its documented default and the
official Svelte CLI add-on use the Inlang Message Format plugin and
`messages/{locale}.json`
([Paraglide file formats](https://paraglidejs.com/file-formats),
[Svelte CLI add-on](https://svelte.dev/docs/cli/paraglide),
[add-on source](https://github.com/sveltejs/cli/blob/main/packages/sv/src/addons/paraglide.ts)).

The generated Svelte setup is explicit:

```json
{
  "modules": [
    "https://cdn.jsdelivr.net/npm/@inlang/plugin-message-format@4/dist/index.js",
    "https://cdn.jsdelivr.net/npm/@inlang/plugin-m-function-matcher@2/dist/index.js"
  ],
  "plugin.inlang.messageFormat": {
    "pathPattern": "./messages/{locale}.json"
  }
}
```

The add-on also creates JSON files with the Inlang Message Format schema. The default authoring
model is stable message keys mapped to strings or structured variants; Paraglide's own guidance
recommends flat, stable, human-readable random keys and compiles them to calls such as
`m.calm_green_otter()`
([basics](https://paraglidejs.com/basics),
[message keys](https://paraglidejs.com/message-keys)).

Consequently, neither PO nor POT is Paraglide's default canonical repository format. Saying that
"Inlang is format agnostic" does not make PO support automatic—the storage plugin is the component
that must preserve all relevant semantics in both directions.

## 2. Gettext/PO support

### Paraglide/Inlang

As of the date above, the official Inlang plugin catalog lists storage integrations including
Inlang Message Format JSON, i18next JSON, ICU MessageFormat JSON, next-intl, Android resources, and
Apple string catalogs, but it does not list a gettext or PO plugin
([official plugin catalog](https://inlang.com/c/plugins)). Paraglide's own file-format guide lists
the recommended JSON plugin, i18next, and simple JSON and directs other formats to that same
catalog; it does not document `.po` or `.pot`
([translation file formats](https://paraglidejs.com/file-formats)). The official npm registry also
describes `@inlang/plugin-message-format` as a JSON-per-language storage plugin
([package metadata](https://registry.npmjs.org/@inlang%2Fplugin-message-format/latest)).

Therefore Paraglide currently provides no official, documented, stable PO/POT round trip. It can
only meet the constraint through one of these project-owned extensions:

- **Custom Inlang storage plugin:** implement PO read and write against Inlang's message/variant
  model, including contexts, comments/references, fuzzy and obsolete state, plural headers,
  placeholders, and plural/select mapping. Inlang documents how to write plugins, but Quirebase
  would own the compatibility and data-loss tests
  ([plugin authoring](https://inlang.com/docs/write-plugin)).
- **Conversion before compilation:** treat PO as canonical and generate ignored Inlang JSON for
  Paraglide. This can be safe only as a one-way, deterministic build artifact. It still needs a
  separate source extractor/POT updater and a rigorously specified mapping. Allowing both JSON and
  PO to be edited would create two sources of truth.
- **External bidirectional converter:** this has the highest merge and semantic-loss risk. A
  generic PO-to-JSON conversion is not the same thing as a Paraglide/Inlang round trip, especially
  for contexts, metadata, and plural/select variants.

Paraglide's CLI compiles an Inlang project; it does not document an equivalent of
`extract-template` that creates a gettext POT from application source. Sherlock can extract
messages interactively and its matcher recognizes generated `m.*` calls, but that is a developer
IDE workflow, not a reproducible PO/POT catalog pipeline
([message-key guidance](https://paraglidejs.com/message-keys),
[Svelte add-on output](https://svelte.dev/docs/cli/paraglide#What-you-get)).

### Lingui

Lingui treats the offline catalog format as separate from the optimized production representation.
Its official documentation calls PO the **recommended and default** catalog format and provides a
formatter that reads and writes PO while preserving translator comments, origins, contexts, flags,
and metadata
([catalog formats](https://lingui.dev/ref/catalog-formats#po)).

Its CLI provides the complete source-to-catalog lifecycle:

- `lingui extract` scans source, merges newly found messages into each locale's existing catalog,
  preserves translations, can mark/remove obsolete entries, and reports missing messages;
- `lingui extract-template` generates a `.pot` template;
- `lingui compile` reads the translated catalogs, validates them, and emits optimized JS/TS runtime
  catalogs; `--strict` can fail on missing translations
  ([CLI reference](https://lingui.dev/ref/cli)).

There are two PO encodings to choose deliberately:

- `@lingui/format-po` uses normal PO records but stores plural expressions as ICU MessageFormat.
  This is the documented default and retains Lingui's full ICU feature set.
- `@lingui/format-po-gettext` reads and writes native gettext plurals with `msgid_plural` and
  `msgstr[n]`. It is appropriate when the translation backend requires native gettext plural
  records, but Lingui documents real limitations: nested/multiple plurals, `select`,
  `selectOrdinal`, negative/fractional plural cases, and some source languages cannot map losslessly
  to gettext's model
  ([PO with gettext plurals](https://lingui.dev/ref/catalog-formats#po-gettext)).

The product requirement should clarify whether "gettext/PO" means the standard PO container or
strict gettext-native plural semantics. Lingui supports both, but native gettext plurals constrain
the message model regardless of frontend runtime.

### Dependency health

Package health is not a reason to reject Paraglide. The evaluated package is the genuine
`@inlang/paraglide-js` package linked to `opral/paraglide-js`, not a similarly named community
package. Version 2.25.2 is MIT-licensed, was published on 2026-09-11, has npm provenance
attestation, declares no install lifecycle script, and recorded about 1.90 million npm downloads
in the month ending 2026-09-11
([npm manifest](https://registry.npmjs.org/@inlang%2Fparaglide-js/latest),
[npm downloads](https://api.npmjs.org/downloads/point/last-month/%40inlang%2Fparaglide-js)).
The official repository is active and unarchived, and the package has accumulated 163 releases
since 2023. OSV returned no advisory for the package at the time of review
([repository metadata](https://api.github.com/repos/opral/paraglide-js),
[OSV query API](https://api.osv.dev/v1/query)).

There are two caveats to retain in the dependency record: npm lists one human maintainer and one
publishing bot, so effective publishing ownership is concentrated, and OpenSSF Scorecard does not
currently have a result for the repository. The npm provenance attestation is a useful mitigating
signal, but it is not a substitute for a Scorecard review. Neither caveat changes the format and
ownership decision above.

## 3. SvelteKit static SPA integration

Paraglide 2.25.2 officially supports Vite and SvelteKit. Its Vite plugin watches the Inlang project
and emits generated source under an output directory such as `src/lib/paraglide`:

```text
paraglide/
  messages/<message-id>/{index,en,zh-CN}.js
  messages.js
  runtime.js
  server.js
```

The output is generated and ignored. Each message is a typed function. Because messages are plain
ES modules, Vite can tree-shake unused message functions and code-split them with the consuming
route. This is Paraglide's clearest technical advantage
([architecture](https://paraglidejs.com/architecture),
[compiling messages](https://paraglidejs.com/compiling-messages)). The researched npm package supports
Vite 5 or later and TypeScript 5.6 or later
([npm manifest](https://registry.npmjs.org/@inlang%2Fparaglide-js/latest)).

The official Svelte add-on also installs:

- a client `reroute` hook for locale-prefixed URLs;
- a **SvelteKit server** `handle` hook that runs Paraglide middleware and substitutes `<html lang>`
  and `dir` placeholders;
- localized hidden links in the root layout;
- default URL-based locale strategy and Inlang JSON catalogs
  ([Svelte CLI documentation](https://svelte.dev/docs/cli/paraglide),
  [official SvelteKit example](https://paraglidejs.com/sveltekit)).

That generated integration cannot be accepted unchanged for Quirebase:

- Quirebase builds a client-only `adapter-static` fallback with `ssr = false`; FastAPI, not a
  SvelteKit server, serves the document in production. A generated `hooks.server.ts` cannot
  transform the static fallback per request.
- Locale is a reactive browser preference. The static application updates translated content
  and document language without a full navigation.
- The official setup defaults to localized URLs. Adding locale prefixes would change every
  application URL and route contract without a product requirement.
- Paraglide recommends that normal locale changes perform a full document navigation. Its
  `setLocale(locale, { reload: false })` is explicitly described as a narrow client-only escape
  hatch that does **not** rerender the framework or update `<html lang>`, direction, title, or
  metadata; an application choosing it must own all those reactive updates
  ([locale strategy](https://paraglidejs.com/strategy),
  [locale switching](https://paraglidejs.com/basics#getting-and-setting-the-locale)).

A Paraglide integration would need to preserve that reactive behavior and the PO source of truth.
The [application contract](../architecture/application-http-boundary.md) defines those requirements.

## 4. Workflow comparison

| Concern                     | Lingui PO                                                                 | Paraglide default                                                   | Paraglide with PO constraint                                       |
| --------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Committed translation truth | `.po`; optional generated `.pot`                                                 | `messages/{locale}.json`                                            | `.po`, plus project-owned adapter/converter                        |
| Official PO read/write      | Yes: `@lingui/format-po`; native plural alternative available                    | No                                                                  | Must implement or depend on an unendorsed conversion layer         |
| Source extraction           | `lingui extract`; `.pot` via `extract-template`                                  | Messages authored in storage files; Sherlock-assisted extraction    | Separate custom extractor/POT generator required                   |
| Production compilation      | `lingui compile` or Vite plugin emits compact catalog modules                    | Vite plugin emits typed per-message functions                       | PO conversion/plugin, then Paraglide compile                       |
| Svelte syntax               | Project-local Svelte extractor; official extractor covers JS/TS | `m.*` calls work directly in Svelte after generation                | Same, plus PO bridge                                               |
| Locale reactivity           | Existing Quirebase writable store activates Lingui and rerenders                 | Full navigation by default; no-reload requires app-owned reactivity | Custom reactive locale bridge needed                            |
| Tree shaking                | Catalog usually loaded per locale; experimental dependency-tree extractor exists | Per-message ES modules are tree-shakable                            | Same runtime benefit after extra pipeline                          |
| CI drift checks             | Extract/compile/strict are official CLI operations                               | Compiler validates Inlang project                                   | Must also prove PO↔Inlang conversion is deterministic and lossless |

Lingui's built-in extractor supports JavaScript/TypeScript, while Svelte syntax needs a custom
extractor ([message extraction](https://lingui.dev/guides/message-extraction#supported-source-types)).
Quirebase implements that seam in
[`i18n-extractor.ts` at the evaluated revision](https://github.com/Jadeiin/quirebase/blob/2c6dd3aec88959bc2047eb42dc32b32f52d1d62c/frontend/src/lib/i18n-extractor.ts), recognizing literal `$t` calls and
marked `msg` descriptors. Fixture tests verify extraction and rejected dynamic markers. It feeds
Lingui's official PO merge/POT/compile pipeline without owning a general gettext storage plugin.

## 5. Migration cost and risks

### Immediate application rewrite

Changing to Paraglide would replace runtime calls and extraction, add Inlang project data,
provide a PO storage/conversion path and preserve reactive locale switching in the static app.
The current Lingui implementation already provides those application workflows.

### Long-term risks

- **Two sources of truth:** editable JSON generated for Paraglide will eventually diverge from PO
  unless it is always overwritten and CI rejects changes.
- **Silent semantic loss:** gettext plurals, ICU/Inlang variants, contexts, flags, comments, and
  source references do not form a one-to-one model.
- **Generated API churn:** message-key changes are source-code API renames in Paraglide, whereas
  Quirebase currently uses English text as IDs.
- **Locale ownership split:** a Paraglide cookie/URL preference would need to agree with the
  application's reactive browser locale.
- **Tooling ownership:** the project, rather than Paraglide or Inlang, becomes responsible for the
  most important requirement—the PO round trip.

### What Paraglide would improve

The assessment should not hide its benefits. Paraglide generates typed calls, validates parameter
shapes, eliminates unused messages through normal bundler tree shaking, avoids runtime message
parsing, and integrates cleanly with Vite HMR. If Quirebase later permits Inlang Message Format JSON
to become the translation source of truth, Paraglide becomes a strong candidate. Under the current
PO-only rule, those runtime/DX gains do not outweigh the catalog-pipeline risk.

## Reconsideration criteria

Revisit Paraglide only if one of these conditions changes:

- Inlang publishes and supports an official PO storage plugin with tested bidirectional fidelity
  and a POT/extraction workflow; or
- Quirebase deliberately changes its canonical translation format from PO to Inlang Message
  Format JSON.

## Primary-source snapshot

- Researched Paraglide JS package: 2.25.2, MIT, Vite `>=5`, TypeScript `>=5.6`
  ([npm](https://registry.npmjs.org/@inlang%2Fparaglide-js/latest)).
- Researched Lingui runtime/CLI: 6.7.0, MIT
  ([core](https://registry.npmjs.org/@lingui%2Fcore/latest),
  [CLI](https://registry.npmjs.org/@lingui%2Fcli/latest)).
- Svelte CLI's current add-on source selects Inlang JSON storage and generates Vite, reroute,
  server-hook, document-language, and locale-link integration
  ([source](https://github.com/sveltejs/cli/blob/main/packages/sv/src/addons/paraglide.ts)).
