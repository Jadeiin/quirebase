# Third-party components

Quirebase is distributed under AGPL-3.0-only. Binary and source distributions must also retain the notices shipped by their dependencies.

Core PDF components:

- `@embedpdf/svelte-pdf-viewer` 2.15.1 — MIT, the pinned Svelte viewer used for browser PDF rendering, search, zoom and annotation interaction.
- `@embedpdf/snippet` 2.15.1 — MIT, the viewer's runtime dependency that provides EmbedPDF initialization and API exports.
- PDFium WebAssembly from `@embedpdf/pdfium` 2.15.1 — EmbedPDF's wrapper is MIT; the bundled PDFium binary carries the PDFium BSD-style license and the additional third-party notices distributed in that package.
- PyMuPDF — AGPL-3.0-only or commercial license. Quirebase uses it under AGPL-3.0-only.
- Commonmeta — MIT, used for local scholarly metadata and bibliography format conversion.
- bibtexparser — BSD-3-Clause or LGPL-3.0, used for BibTeX/BibLaTeX parsing, native serialization,
  `@string` macros and structured name splitting alongside Commonmeta conversion.
- pylatexenc — MIT, used directly by Inquiro's rich-text layer for
  Unicode/LaTeX text conversion. Quirebase preserves Unicode code points such as
  CJK characters when no LaTeX mapping exists.
- Temml 0.14.0 — MIT, bundled by the frontend to render bounded inline LaTeX
  formulae as MathML before Quirebase rebuilds them through a strict allowlist.
- YAKE 0.7.x — used as the default local keyword extractor. Its package metadata says LGPL-3.0,
  while the upstream distribution's actual LICENSE is AGPL-3.0-or-later; Quirebase records and
  distributes it under the latter, more restrictive license.
- KeyBERT 0.9.x — MIT, optional (`keybert` extra) semantic keyphrase extraction.
- Model2Vec — MIT, optional (`keybert` extra) static embedding runtime. Administrator-provided
  model files have their own licenses; retain their source and license information separately.
- citeproc-py — BSD-2-Clause-Views, the CSL 1.0.1 processor for formatted citations.
- citeproc-py-styles — MIT, optional (`citation` extra) CSL style repository used for built-in styles.
- httpx2 — BSD-3-Clause, HTTP transport client for outbound discovery metadata lookup and online search.
- FastMCP 4.x — Apache-2.0, used to derive the curated MCP tool adapter from Quirebase's OpenAPI
  contract. Its official MCP SDK dependency is MIT.
- PyCasbin — Apache-2.0, used as the in-process authorization policy evaluator. Its `simpleeval`
  dependency is MIT.
- obstore — Apache-2.0, the native asynchronous Local/S3 object-storage data plane.
- stream-zip — MIT, used to generate ZIP downloads incrementally without assembling an archive on disk.

The lockfiles are the authoritative version inventory. Produce a release SBOM from `uv.lock` and
`frontend/bun.lock`, and include dependency license files from installed wheels and packages in
every release artifact.

Known dependency constraints: Commonmeta currently requires WeasyPrint 69.x, blocking its 70.x
security fixes. Inquiro uses Commonmeta's local metadata conversion with `no_network=True` and does
not invoke PDF rendering. The development-only glob dependency `braces` 3.0.3 also has an unresolved
advisory. Recheck these upstream constraints and advisories before publishing.
