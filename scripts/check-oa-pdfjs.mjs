import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(await readFile(path.join(root, "tests", "oa_corpus.json"), "utf8"));
const directory = path.resolve(process.argv[2] || path.join(root, ".cache", "oa-pdfs"));

for (const paper of manifest.papers) {
  const bytes = new Uint8Array(await readFile(path.join(directory, `${paper.id}.pdf`)));
  const digest = createHash("sha256").update(bytes).digest("hex");
  if (digest !== paper.sha256) throw new Error(`${paper.id}: SHA-256 mismatch`);
  const task = getDocument({ data: bytes, isEvalSupported: false, useSystemFonts: true });
  const document = await task.promise;
  if (document.numPages !== paper.pages) throw new Error(`${paper.id}: page count mismatch`);
  let characters = 0;
  let operators = 0;
  for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
    const page = await document.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1 });
    if (!(viewport.width > 0 && viewport.height > 0)) throw new Error(`${paper.id}: bad viewport`);
    const content = await page.getTextContent();
    characters += content.items.reduce((count, item) => count + (item.str?.length || 0), 0);
    const operatorList = await page.getOperatorList();
    operators += operatorList.fnArray.length;
    page.cleanup();
  }
  if (characters < paper.minimum_text_characters * 0.8) {
    throw new Error(`${paper.id}: PDF.js extracted too little text (${characters})`);
  }
  if (operators < document.numPages) throw new Error(`${paper.id}: empty drawing operation list`);
  await task.destroy();
  process.stdout.write(`${paper.id}: ${paper.pages} pages, ${characters} chars, ${operators} operators\n`);
}
