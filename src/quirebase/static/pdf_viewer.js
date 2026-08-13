import * as pdfjsLib from "/static/vendor/pdf.mjs";
import { EventBus, PDFLinkService, PDFFindController, PDFViewer } from "/static/vendor/pdf_viewer.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.mjs";

const root = document.querySelector("#pdf-app");
const messages = JSON.parse(root.dataset.i18n);
const message = (key, values = {}) => Object.entries(values).reduce(
  (text, [name, value]) => text.replaceAll(`{${name}}`, value),
  messages[key],
);
const itemId = root.dataset.itemId;
const revisionId = root.dataset.revisionId;
const csrf = root.dataset.csrf;
const status = document.querySelector("#pdf-status");
const container = document.querySelector("#viewerContainer");
const pageNumber = document.querySelector("#pdf-page-number");
const pageTotal = document.querySelector("#pdf-page-total");
const scale = document.querySelector("#pdf-scale");
const search = document.querySelector("#pdf-search");
const detail = document.querySelector("#annotation-detail");
const detailKind = document.querySelector("#annotation-detail-kind");
const detailPage = document.querySelector("#annotation-detail-page");
const detailScope = document.querySelector("#annotation-detail-scope");
const detailText = document.querySelector("#annotation-detail-text");
const detailBody = document.querySelector("#annotation-detail-body");
const detailSave = document.querySelector("#annotation-detail-save");
const detailDelete = document.querySelector("#annotation-detail-delete");
const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus });
const findController = new PDFFindController({ eventBus, linkService });
const viewer = new PDFViewer({ container, eventBus, linkService, findController, textLayerMode: 1 });
linkService.setViewer(viewer);

let annotations = [];
let selectedAnnotation = null;
let noteMode = false;
let lastFindQuery = "";
const projectPicker = document.querySelector("#annotation-project");
const visibility = () => projectPicker.value ? { scope: "project", project_id: projectPicker.value } : { scope: "private", project_id: null };

const api = async (url, options = {}) => {
  options.headers = { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...(options.headers || {}) };
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.text()) || `HTTP ${response.status}`);
  return response.status === 204 ? null : response.json();
};

const annotationUrl = `/documents/${itemId}/annotations`;
const contentUrl = `/documents/${itemId}/revisions/${revisionId}/content`;

const showAnnotation = (annotation) => {
  selectedAnnotation = annotation;
  document.querySelectorAll("[data-annotation-id]").forEach((node) => {
    node.classList.toggle("is-selected", node.dataset.annotationId === annotation.id);
  });
  const firstSegment = annotation.segments[0];
  detailKind.textContent = annotation.kind === "highlight" ? message("highlight") : message("noteText");
  detailPage.textContent = message("page", { page: (firstSegment?.page_index ?? 0) + 1 });
  detailScope.textContent = message(annotation.scope === "project" ? "project" : "private");
  detailText.textContent = annotation.selected_text || "";
  detailText.hidden = !annotation.selected_text;
  detailBody.value = annotation.body || "";
  detailBody.disabled = !annotation.mine;
  detailSave.hidden = !annotation.mine;
  detailDelete.hidden = !annotation.mine;
  detail.hidden = false;
};

const closeAnnotation = () => {
  detail.hidden = true;
  document.querySelectorAll("[data-annotation-id]").forEach((node) => node.classList.remove("is-selected"));
  selectedAnnotation = null;
};

const find = (findPrevious = false) => {
  const query = search.value.trim();
  if (!query) return;
  eventBus.dispatch("find", {
    source: root,
    type: query === lastFindQuery ? "again" : "",
    query,
    phraseSearch: true,
    caseSensitive: false,
    entireWord: false,
    highlightAll: true,
    findPrevious,
    matchDiacritics: false,
  });
  lastFindQuery = query;
};

const loadAnnotations = async () => {
  const project = projectPicker.value ? `&project_id=${encodeURIComponent(projectPicker.value)}` : "";
  const data = await api(`${annotationUrl}?revision_id=${revisionId}${project}`);
  annotations = data.annotations;
  renderAllOverlays();
};

const pageViewForElement = (element) => {
  const page = element?.closest(".page");
  if (!page) return null;
  const index = Number(page.dataset.pageNumber) - 1;
  return { page, index, view: viewer.getPageView(index) };
};

const pointToPdf = (page, view, clientX, clientY) => {
  const bounds = page.querySelector(".canvasWrapper")?.getBoundingClientRect() || page.getBoundingClientRect();
  return view.viewport.convertToPdfPoint(clientX - bounds.left, clientY - bounds.top);
};

const selectionSegments = () => {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return [];
  const segments = [];
  for (const rect of selection.getRangeAt(0).getClientRects()) {
    if (rect.width < 1 || rect.height < 1) continue;
    const context = pageViewForElement(document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2));
    if (!context) continue;
    const ul = pointToPdf(context.page, context.view, rect.left, rect.top);
    const ur = pointToPdf(context.page, context.view, rect.right, rect.top);
    const ll = pointToPdf(context.page, context.view, rect.left, rect.bottom);
    const lr = pointToPdf(context.page, context.view, rect.right, rect.bottom);
    segments.push({ page_index: context.index, quad_points: [...ul, ...ur, ...ll, ...lr] });
  }
  return segments;
};

const saveHighlight = async (color) => {
  const selection = window.getSelection();
  const segments = selectionSegments();
  if (!segments.length) return alert(message("selectTextFirst"));
  status.textContent = message("saving");
  try {
    const saved = await api(annotationUrl, {
      method: "POST",
      body: JSON.stringify({
        revision_id: revisionId, kind: "highlight", ...visibility(), color,
        selected_text: selection.toString(), segments,
      }),
    });
    annotations.push(saved);
    selection.removeAllRanges();
    renderAllOverlays();
    status.textContent = message("saved");
  } catch (error) { status.textContent = error.message; }
};

const saveNote = async (event) => {
  if (!noteMode) return;
  const context = pageViewForElement(event.target);
  if (!context) return;
  event.preventDefault();
  noteMode = false;
  const body = prompt(message("noteText"));
  if (body === null || !body.trim()) return;
  const [anchor_x, anchor_y] = pointToPdf(context.page, context.view, event.clientX, event.clientY);
  try {
    const saved = await api(annotationUrl, {
      method: "POST",
      body: JSON.stringify({
        revision_id: revisionId, kind: "note", ...visibility(), color: "yellow", body,
        segments: [{ page_index: context.index, anchor_x, anchor_y }],
      }),
    });
    annotations.push(saved);
    renderAllOverlays();
    status.textContent = message("saved");
  } catch (error) { status.textContent = error.message; }
};

const overlayForPage = (index) => {
  const pageView = viewer.getPageView(index);
  if (!pageView?.div) return null;
  let overlay = pageView.div.querySelector(":scope > .quirebase-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "quirebase-overlay";
    pageView.div.append(overlay);
  }
  overlay.replaceChildren();
  return { overlay, viewport: pageView.viewport };
};

const renderAllOverlays = () => {
  if (!viewer.pdfDocument) return;
  for (let pageIndex = 0; pageIndex < viewer.pagesCount; pageIndex++) {
    const target = overlayForPage(pageIndex);
    if (!target) continue;
    for (const annotation of annotations) {
      for (const segment of annotation.segments.filter((part) => part.page_index === pageIndex)) {
        const node = document.createElement("span");
        node.dataset.annotationId = annotation.id;
        node.title = annotation.body || annotation.selected_text || message("highlight");
        node.addEventListener("click", (event) => { event.stopPropagation(); showAnnotation(annotation); });
        if (annotation.kind === "highlight") {
          const points = [];
          for (let i = 0; i < 8; i += 2) points.push(target.viewport.convertToViewportPoint(segment.quad_points[i], segment.quad_points[i + 1]));
          const xs = points.map((p) => p[0]); const ys = points.map((p) => p[1]);
          Object.assign(node.style, {
            left: `${Math.min(...xs)}px`, top: `${Math.min(...ys)}px`,
            width: `${Math.max(...xs) - Math.min(...xs)}px`, height: `${Math.max(...ys) - Math.min(...ys)}px`,
            background: annotation.color,
          });
          node.className = "quirebase-highlight";
        } else {
          const [x, y] = target.viewport.convertToViewportPoint(segment.anchor_x, segment.anchor_y);
          Object.assign(node.style, { left: `${x - 9}px`, top: `${y - 9}px` });
          node.className = "quirebase-note";
        }
        target.overlay.append(node);
      }
    }
  }
};

document.querySelectorAll("[data-color]").forEach((button) => button.addEventListener("click", () => saveHighlight(button.dataset.color)));
document.querySelector("#pdf-previous-page").addEventListener("click", () => { viewer.currentPageNumber -= 1; });
document.querySelector("#pdf-next-page").addEventListener("click", () => { viewer.currentPageNumber += 1; });
document.querySelector("#pdf-zoom-out").addEventListener("click", () => viewer.decreaseScale());
document.querySelector("#pdf-zoom-in").addEventListener("click", () => viewer.increaseScale());
pageNumber.addEventListener("change", () => {
  viewer.currentPageNumber = Math.max(1, Math.min(viewer.pagesCount, Number(pageNumber.value) || 1));
});
scale.addEventListener("change", () => { viewer.currentScaleValue = scale.value; });
document.querySelector("#pdf-find-previous").addEventListener("click", () => find(true));
document.querySelector("#pdf-find-next").addEventListener("click", () => find());
search.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  event.preventDefault();
  find(event.shiftKey);
});
document.querySelector("#add-note").addEventListener("click", () => { noteMode = true; status.textContent = message("clickPage"); });
document.querySelector("#viewer").addEventListener("click", saveNote, true);
projectPicker.addEventListener("change", loadAnnotations);
document.querySelector("#export-annotations").addEventListener("click", async () => {
  try {
    const created = await api(`${annotationUrl.replace("/annotations", "/annotation-exports")}`, {
      method: "POST", body: JSON.stringify({ revision_id: revisionId, project_id: projectPicker.value || null, include_private: true }),
    });
    status.textContent = message("preparingExport");
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      const job = await api(`/annotation-exports/${created.id}`);
      if (job.state === "succeeded") { window.location.assign(`/annotation-exports/${created.id}/content`); status.textContent = message("exportReady"); break; }
      if (job.state === "failed") throw new Error(job.error || message("exportFailed"));
    }
  } catch (error) { status.textContent = error.message; }
});
document.querySelector("#delete-annotation").addEventListener("click", async () => {
  if (!selectedAnnotation || !selectedAnnotation.mine) return alert(message("selectOwnAnnotation"));
  await api(`${annotationUrl}/${selectedAnnotation.id}`, { method: "DELETE" });
  annotations = annotations.filter((row) => row.id !== selectedAnnotation.id);
  selectedAnnotation = null;
  detail.hidden = true;
  renderAllOverlays();
});
document.querySelector("#annotation-detail-close").addEventListener("click", closeAnnotation);
detailSave.addEventListener("click", async () => {
  if (!selectedAnnotation?.mine) return;
  const saved = await api(`${annotationUrl}/${selectedAnnotation.id}`, {
    method: "PATCH",
    body: JSON.stringify({ version: selectedAnnotation.version, body: detailBody.value }),
  });
  annotations = annotations.map((row) => row.id === saved.id ? saved : row);
  showAnnotation(saved);
  renderAllOverlays();
  status.textContent = message("saved");
});
detailDelete.addEventListener("click", async () => {
  if (!selectedAnnotation?.mine) return;
  await api(`${annotationUrl}/${selectedAnnotation.id}`, { method: "DELETE" });
  annotations = annotations.filter((row) => row.id !== selectedAnnotation.id);
  closeAnnotation();
  renderAllOverlays();
});
eventBus.on("pagerendered", renderAllOverlays);
eventBus.on("pagechanging", ({ pageNumber: current }) => { pageNumber.value = current; });
eventBus.on("scalechanging", ({ presetValue }) => {
  if (presetValue && [...scale.options].some((option) => option.value === presetValue)) scale.value = presetValue;
});
eventBus.on("pagesinit", () => {
  viewer.currentScaleValue = "page-width";
  pageTotal.textContent = viewer.pagesCount;
  pageNumber.max = viewer.pagesCount;
});

try {
  const loadingTask = pdfjsLib.getDocument({ url: contentUrl, isEvalSupported: false });
  const documentProxy = await loadingTask.promise;
  viewer.setDocument(documentProxy);
  linkService.setDocument(documentProxy);
  await loadAnnotations();
  status.textContent = message("pages", { count: documentProxy.numPages });
} catch (error) {
  status.textContent = message("unableToOpen", { message: error.message });
}
