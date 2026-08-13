import { cp, mkdir } from "node:fs/promises";

await mkdir("src/quirebase/static/vendor", { recursive: true });
await cp("node_modules/pdfjs-dist/build/pdf.mjs", "src/quirebase/static/vendor/pdf.mjs");
await cp("node_modules/pdfjs-dist/build/pdf.worker.mjs", "src/quirebase/static/vendor/pdf.worker.mjs");
await cp("node_modules/pdfjs-dist/web/pdf_viewer.mjs", "src/quirebase/static/vendor/pdf_viewer.mjs");
await cp("node_modules/pdfjs-dist/web/pdf_viewer.css", "src/quirebase/static/vendor/pdf_viewer.css");
