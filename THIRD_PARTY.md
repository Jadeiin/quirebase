# Third-party components

Quirebase is distributed under AGPL-3.0-only. Binary and source distributions must also retain the notices shipped by their dependencies.

Core PDF components:

- Mozilla PDF.js 6.2.108 — Apache-2.0. The vendored browser files are generated from the pinned `pdfjs-dist` package.
- PyMuPDF — AGPL-3.0-only or commercial license. Quirebase uses it under AGPL-3.0-only.
- bibtexparser 2.x beta — MIT, used for BibTeX/BibLaTeX parsing, native
  serialization, `@string` macros and structured name splitting. The lockfile
  records the resolved beta while Inquiro fixes the middleware stacks explicitly.
- pylatexenc 2.11 — MIT, used directly by Inquiro's rich-text layer for
  Unicode/LaTeX text conversion. Quirebase preserves Unicode code points such as
  CJK characters when no LaTeX mapping exists.
- latex2mathml 3.81.x — MIT, used only by Inquiro's Web projection to render
  bounded inline LaTeX formulae as allowlisted MathML.
- RISpy — MIT, used for RIS parsing and serialization.
- YAKE 0.7.x — used as the default local keyword extractor. Its package metadata says LGPL-3.0,
  while the upstream distribution's actual LICENSE is AGPL-3.0-or-later; Quirebase records and
  distributes it under the latter, more restrictive license.
- KeyBERT 0.9.x — MIT, optional (`keybert` extra) semantic keyphrase extraction.
- Model2Vec — MIT, optional (`keybert` extra) static embedding runtime. Administrator-provided
  model files are separate works: deployments must record each model's source, license and SHA-256
  independently and may configure `QUIREBASE_KEYBERT_MODEL_SHA256` for verification.
- citeproc-py — BSD-2-Clause-Views, the CSL 1.0.1 processor for formatted citations.
- citeproc-py-styles — MIT, optional (`citation` extra) CSL style repository used for built-in styles.
- Alpine.js CSP build 3.15.12 — MIT, bundled from the pinned `@alpinejs/csp` package for local UI interactions without enabling `unsafe-eval`.
- `@zxcvbn-ts/core` 4.2.0, `@zxcvbn-ts/language-common` 4.1.3, and
  `@zxcvbn-ts/language-en` 4.1.1 — MIT, bundled into the local password-strength estimator.
- httpx2 — BSD-3-Clause, HTTP transport client for outbound discovery metadata lookup and online search.
- obstore — Apache-2.0, the native asynchronous Local/S3 object-storage data plane.
- stream-zip — MIT, used to generate ZIP downloads incrementally without assembling an archive on disk.

The lockfiles are the authoritative version inventory. Produce a release SBOM from `uv.lock` and `bun.lock`, and include dependency license files from installed wheels and packages in every release artifact.

`python-poppler`, `pypdfium2`, and `pypdf` are deliberately not dependencies.
