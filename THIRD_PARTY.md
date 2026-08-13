# Third-party components

Quirebase is distributed under AGPL-3.0-only. Binary and source distributions must also retain the notices shipped by their dependencies.

Core PDF components:

- Mozilla PDF.js 6.2.108 — Apache-2.0. The vendored browser files are generated from the pinned `pdfjs-dist` package.
- PyMuPDF — AGPL-3.0-only or commercial license. Quirebase uses it under AGPL-3.0-only.
- bibtexparser — LGPL-3.0-or-later, used for BibTeX parsing and serialization.
- RISpy — MIT, used for RIS parsing and serialization.
- Alpine.js CSP build 3.15.12 — MIT, bundled from the pinned `@alpinejs/csp` package for local UI interactions without enabling `unsafe-eval`.

The lockfiles are the authoritative version inventory. Produce a release SBOM from `uv.lock` and `bun.lock`, and include dependency license files from installed wheels and packages in every release artifact.

`python-poppler`, `pypdfium2`, and `pypdf` are deliberately not dependencies.
