import { copyFile, mkdir, rm } from "node:fs/promises";

await rm("src/quirebase/static", { recursive: true, force: true });
await mkdir("src/quirebase/static/vendor", { recursive: true });
await copyFile("src/quirebase/assets/styles.css", "src/quirebase/static/app.css");
await copyFile(
  "node_modules/@embedpdf/pdfium/dist/pdfium.wasm",
  "src/quirebase/static/vendor/pdfium.wasm",
);
