import * as pdfjsLib from "/static/vendor/pdf.mjs";
import { EventBus, PDFLinkService, PDFFindController, PDFViewer } from "/static/vendor/pdf_viewer.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdf.worker.mjs";

const root = document.querySelector("#pdf-app");
const itemId = root.dataset.itemId;
const revisionId = root.dataset.revisionId;
const csrf = root.dataset.csrf;
const status = document.querySelector("#pdf-status");
const container = document.querySelector("#viewerContainer");
const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus });
const findController = new PDFFindController({ eventBus, linkService });
const viewer = new PDFViewer({ container, eventBus, linkService, findController, textLayerMode: 1 });
linkService.setViewer(viewer);

let annotations = [];
let selectedAnnotation = null;
let noteMode = false;
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
  const bounds = page.getBoundingClientRect();
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
  if (!segments.length) return alert("Select text first.");
  status.textContent = "Saving…";
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
    status.textContent = "Saved";
  } catch (error) { status.textContent = error.message; }
};

const saveNote = async (event) => {
  if (!noteMode) return;
  const context = pageViewForElement(event.target);
  if (!context) return;
  event.preventDefault();
  noteMode = false;
  const body = prompt("Note text");
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
    status.textContent = "Saved";
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
        node.title = annotation.body || annotation.selected_text || "Highlight";
        node.addEventListener("click", () => { selectedAnnotation = annotation; status.textContent = node.title; });
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
document.querySelector("#add-note").addEventListener("click", () => { noteMode = true; status.textContent = "Click a page to place the note"; });
document.querySelector("#viewer").addEventListener("click", saveNote, true);
projectPicker.addEventListener("change", loadAnnotations);
document.querySelector("#export-annotations").addEventListener("click", async () => {
  try {
    const created = await api(`${annotationUrl.replace("/annotations", "/annotation-exports")}`, {
      method: "POST", body: JSON.stringify({ revision_id: revisionId, project_id: projectPicker.value || null, include_private: true }),
    });
    status.textContent = "Preparing export…";
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      const job = await api(`/annotation-exports/${created.id}`);
      if (job.state === "succeeded") { window.location.assign(`/annotation-exports/${created.id}/content`); status.textContent = "Export ready"; break; }
      if (job.state === "failed") throw new Error(job.error || "Export failed");
    }
  } catch (error) { status.textContent = error.message; }
});
document.querySelector("#delete-annotation").addEventListener("click", async () => {
  if (!selectedAnnotation || !selectedAnnotation.mine) return alert("Select one of your annotations.");
  await api(`${annotationUrl}/${selectedAnnotation.id}`, { method: "DELETE" });
  annotations = annotations.filter((row) => row.id !== selectedAnnotation.id);
  selectedAnnotation = null;
  renderAllOverlays();
});
eventBus.on("pagerendered", renderAllOverlays);
eventBus.on("pagesinit", () => { viewer.currentScaleValue = "page-width"; });

try {
  const loadingTask = pdfjsLib.getDocument({ url: contentUrl, isEvalSupported: false });
  const documentProxy = await loadingTask.promise;
  viewer.setDocument(documentProxy);
  linkService.setDocument(documentProxy);
  await loadAnnotations();
  status.textContent = `${documentProxy.numPages} pages`;
} catch (error) {
  status.textContent = `Unable to open PDF: ${error.message}`;
}
