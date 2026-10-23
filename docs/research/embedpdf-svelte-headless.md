# EmbedPDF Svelte headless integration notes

Research snapshot: 2026-09-16, targeting EmbedPDF 2.15.0. EmbedPDF moved its v2 implementation and examples to the `v2` maintenance branch in
July 2026; the pinned source links below use that branch's commit
[`2c0f23d`](https://github.com/embedpdf/embed-pdf-viewer/tree/2c0f23d90c0bbfd126363db5e913b407a8ae7266).

## Integration outcome

Quirebase uses `@embedpdf/svelte-pdf-viewer`, with the current choice and its alternatives recorded
in [ADR 0012](../adr/0012-svelte-application-and-http-boundary.md). The headless APIs below explain
the underlying plugin, asset and lifecycle behavior; they are upstream examples rather than the
application's component composition. The official headless guide uses `usePdfiumEngine()`,
`<EmbedPDF>`, plugin registrations and Svelte snippets.
([guide](https://www.embedpdf.com/docs/svelte/headless/getting-started),
[pinned guide source](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/website/src/content/docs/svelte/headless/getting-started.mdx),
[first-party viewer](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/examples/svelte-tailwind/src/routes/viewer/%2Bpage.svelte))

## Packages

The official minimal scrollable viewer installs:

```text
@embedpdf/core
@embedpdf/engines
@embedpdf/plugin-document-manager
@embedpdf/plugin-viewport
@embedpdf/plugin-scroll
@embedpdf/plugin-render
```

An upstream headless annotation workspace additionally uses:

```text
@embedpdf/plugin-interaction-manager
@embedpdf/plugin-selection
@embedpdf/plugin-history
@embedpdf/plugin-annotation
```

EmbedPDF says the interaction, selection, and history registrations must precede annotation
registration. History is optional in the abstract, but is appropriate here because Quirebase
already supports annotation history and restoration.
([minimal install](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/website/src/content/docs/svelte/headless/getting-started.mdx#L11-L17),
[annotation install and order](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/website/src/content/docs/svelte/headless/plugins/plugin-annotation.mdx#L11-L47))

The models package supplies PDF types/enums; the PDFium package supplies the WASM export for Vite.
Navigation and reader UI can then add only the packages it actually renders, such as zoom, pan,
rotate, spread, tiling, search, thumbnail, export, print, and fullscreen. The full example shows
the exact one-package-per-capability composition; `@embedpdf/snippet` is not part of its headless
viewer path.
([full registration](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/examples/svelte-tailwind/src/routes/viewer/%2Bpage.svelte#L1-L92),
[annotation package manifest](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/plugin-annotation/package.json))

The researched 2.15.0 packages require matching plugin versions. The published packages expose their
Svelte adapters through `/svelte`, require Svelte 5, and declare exact-version peer relationships
between plugins in the 2.15 release.
([core manifest](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/core/package.json),
[engine manifest](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/engines/package.json))

## Upstream Svelte 5 headless example

The relevant native APIs are:

- `usePdfiumEngine` from `@embedpdf/engines/svelte`.
- `EmbedPDF` from `@embedpdf/core/svelte`, plus `createPluginRegistration` from
  `@embedpdf/core`.
- `DocumentContent`, `Viewport`, `Scroller`, and `RenderLayer` from their respective `/svelte`
  exports.
- For annotations, `GlobalPointerProvider` around the viewport, and `PagePointerProvider` around
  each page's `RenderLayer`, `SelectionLayer`, and `AnnotationLayer`.
- Svelte 5 `$props`, `$state`, `$derived`/`$derived.by`, and `{#snippet ...}` are the patterns used
  by the first-party implementation. Capability stores that depend on a changing document ID take
  a getter, for example `useAnnotation(() => documentId)`.

The minimal structure is therefore:

```svelte
<EmbedPDF engine={pdfEngine.engine} {plugins}>
  {#snippet children({ activeDocumentId })}
    <DocumentContent documentId={activeDocumentId}>
      {#snippet children({ isLoaded })}
        {#if isLoaded}
          <GlobalPointerProvider documentId={activeDocumentId}>
            <Viewport documentId={activeDocumentId}>
              <Scroller documentId={activeDocumentId}>
                {#snippet renderPage(page)}
                  <PagePointerProvider
                    documentId={activeDocumentId}
                    pageIndex={page.pageIndex}
                  >
                    <RenderLayer documentId={activeDocumentId} pageIndex={page.pageIndex} />
                    <SelectionLayer documentId={activeDocumentId} pageIndex={page.pageIndex} />
                    <AnnotationLayer documentId={activeDocumentId} pageIndex={page.pageIndex} />
                  </PagePointerProvider>
                {/snippet}
              </Scroller>
            </Viewport>
          </GlobalPointerProvider>
        {/if}
      {/snippet}
    </DocumentContent>
  {/snippet}
</EmbedPDF>
```

The initial document belongs in `DocumentManagerPluginPackage` configuration. Its supported URL
options include a stable `documentId`, display `name`, loading `mode`, and `requestOptions`; the
request options explicitly support `credentials: "same-origin"`, which is required for
Quirebase's session-authenticated PDF content and range requests.
([document options](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/plugin-document-manager/src/lib/types.ts#L30-L46),
[credential contract](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/models/src/pdf.ts#L3171-L3185),
[annotation page composition](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/examples/svelte-tailwind/src/examples/headless/annotation-example-content.svelte#L93-L136))

Use a constant plugin array when the document configuration cannot change during the component's
life. If route props can change without remounting the component, use `$derived.by(() => [...])`
so that a URL/revision change produces a new registration set; the first-party full viewer uses
that construct for its configuration.
([derived registrations](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/examples/svelte-tailwind/src/routes/viewer/%2Bpage.svelte#L58-L92))

## PDFium and WASM

`usePdfiumEngine()` accepts `wasmUrl`, `worker`, `logger`, and `fontFallback`. Its defaults are a
jsDelivr URL for the matching `@embedpdf/pdfium` WASM and `worker: true`; the first-party Svelte
example simply uses this managed default. Consequently, that example performs no manual WASM copy.
For an installation that permits the CDN, `usePdfiumEngine()` is sufficient.
([engine guide](https://www.embedpdf.com/docs/svelte/headless/engine),
[hook implementation](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/engines/src/svelte/hooks/use-pdfium-engine.svelte.ts#L1-L65))

Quirebase bundles PDFium for same-origin loading. The PDFium package explicitly exports
`@embedpdf/pdfium/pdfium.wasm`, while Vite supports explicit URL imports using `?url` and emits
referenced assets into the production asset graph with hashed names. These two first-party
contracts compose without a post-build copy step:

```ts
import pdfiumWasmUrl from '@embedpdf/pdfium/pdfium.wasm?url';
import { usePdfiumEngine } from '@embedpdf/engines/svelte';

const pdfEngine = usePdfiumEngine({
  wasmUrl: pdfiumWasmUrl,
  fontFallback: null,
});
```

The `?url` asset composition follows two upstream contracts: EmbedPDF's own package manifest establishes the public WASM subpath, and Vite establishes
the asset-URL behavior. It lets SvelteKit copy the already-built, hashed asset along with the rest
of `frontend/build`.
([PDFium public export](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/pdfium/package.json#L11-L30),
[Vite static asset handling](https://vite.dev/guide/assets.html#explicit-url-imports))

Pass `fontFallback: null` if Quirebase must make no external font requests. EmbedPDF otherwise
defaults missing-font fallback to jsDelivr URLs for its language font packages. Keep worker mode
enabled for the reader; the engine constructs a module worker from a Blob URL, so CSP must allow
`worker-src 'self' blob:`. PDFium WebAssembly compilation still requires the existing
`script-src 'wasm-unsafe-eval'` policy.
([font fallback URLs](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/engines/src/lib/pdfium/cdn-fonts.ts#L22-L39),
[worker construction](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/engines/src/lib/pdfium/web/worker-engine.ts#L53-L89))

## Lifecycle and teardown

The native Svelte components own engine and registry teardown:

- `usePdfiumEngine()` uses a Svelte `$effect`; its cleanup closes all documents, then destroys the
  engine and worker resources.
- `<EmbedPDF>` creates and initializes the `PluginRegistry` in its own `$effect`; cleanup
  unsubscribes from the registry store, destroys the registry/plugins, and resets context.
- Quirebase-specific event subscriptions used by the annotation persistence adapter remain
  Quirebase's responsibility. Return unsubscribe functions from a component `$effect`, or follow
  the first-party annotation example's `onMount`/`onDestroy` pairing.

([engine cleanup](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/engines/src/svelte/hooks/use-pdfium-engine.svelte.ts#L24-L62),
[provider cleanup](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/packages/core/src/svelte/components/EmbedPDF.svelte#L47-L153),
[subscription cleanup example](https://github.com/embedpdf/embed-pdf-viewer/blob/2c0f23d90c0bbfd126363db5e913b407a8ae7266/examples/svelte-tailwind/src/examples/headless/annotation-example-content.svelte#L1-L58))
