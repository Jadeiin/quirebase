import { mkdir, readFile, writeFile } from "node:fs/promises";

const copyModule = async (source, destination) => {
  const contents = await readFile(source, "utf8");
  await writeFile(destination, contents.replace(/\n?\/\/# sourceMappingURL=.*$/u, ""));
};

const copyViewerStyles = async (source, destination) => {
  const contents = await readFile(source, "utf8");
  await writeFile(destination, contents.replace(/url\(["']?images\/[^)]+\)/gu, "none"));
};

await mkdir("src/quirebase/static/vendor", { recursive: true });
await copyModule("node_modules/pdfjs-dist/build/pdf.mjs", "src/quirebase/static/vendor/pdf.mjs");
await copyModule(
  "node_modules/pdfjs-dist/build/pdf.worker.mjs",
  "src/quirebase/static/vendor/pdf.worker.mjs",
);
await copyModule(
  "node_modules/pdfjs-dist/web/pdf_viewer.mjs",
  "src/quirebase/static/vendor/pdf_viewer.mjs",
);
await copyViewerStyles(
  "node_modules/pdfjs-dist/web/pdf_viewer.css",
  "src/quirebase/static/vendor/pdf_viewer.css",
);
