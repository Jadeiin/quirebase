import EmbedPDF, {
  LockModeType,
  PdfAnnotationSubtype,
} from "@embedpdf/snippet";
import { csrfFetch } from "./csrf.js";
import { createAnnotationAdapter } from "./pdf_annotation_adapter.js";
import { disabledCategories, uiSchema } from "./pdf_viewer_schema.js";

const root = document.querySelector("#pdf-app");
const target = document.querySelector("#embedpdf-viewer");
const status = document.querySelector("#pdf-status");
const projectPicker = document.querySelector("#annotation-project");
const toolbarControls = document.querySelector("#pdf-toolbar-controls");
const downloadOptions = document.querySelector("#pdf-download-options");
const downloadOptionsButton = document.querySelector("#pdf-download-options-button");
const downloadCurrentButton = document.querySelector("#pdf-download-current");
const exportAnnotations = document.querySelector("#pdf-export-annotations");
const downloadProject = document.querySelector("#pdf-download-project");
const messages = JSON.parse(root.dataset.i18n);
const pageGeometry = JSON.parse(root.dataset.pageGeometry || "[]");
const itemId = root.dataset.itemId;
const revisionId = root.dataset.revisionId;
const editableDocument = root.dataset.editable === "true";
const embedPdfLocale = root.dataset.locale?.startsWith("zh") ? "zh-CN" : "en";
const annotationUrl = `/documents/${itemId}/annotations`;
const contentUrl = `/documents/${itemId}/revisions/${revisionId}/content`;
const exportUrl = `/documents/${itemId}/revisions/${revisionId}/export`;
const wasmUrl = new URL("/static/vendor/pdfium.wasm", window.location.origin).href;
const PDF_LOAD_TIMEOUT_MS = 30_000;
const metadata = new Map();
const replyMetadata = new Map();
const annotationTombstones = new Map();
const replyTombstones = new Map();
const databaseIds = new Set();
const nativeIds = new Set();
const pendingWrites = new Map();
const {
  canonicalFromVendor,
  vendorFromCanonical,
  vendorReplyFromCanonical,
} = createAnnotationAdapter(pageGeometry);
let annotationApi;
let uiApi;
let registry;
let initialAnnotationLoad;
let disposed = false;

const visibility = () => projectPicker.value
  ? { scope: "project", project_id: projectPicker.value }
  : { scope: "private", project_id: null };

const message = (key, values = {}) => Object.entries(values).reduce(
  (text, [name, value]) => text.replaceAll(`{${name}}`, value),
  messages[key],
);

const waitForShadowElement = (shadow, selector) => new Promise((resolve, reject) => {
  const existing = shadow.querySelector(selector);
  if (existing) {
    resolve(existing);
    return;
  }
  const observer = new MutationObserver(() => {
    const element = shadow.querySelector(selector);
    if (!element) return;
    window.clearTimeout(timer);
    observer.disconnect();
    resolve(element);
  });
  const timer = window.setTimeout(() => {
    observer.disconnect();
    reject(new Error("EmbedPDF toolbar is unavailable"));
  }, 5_000);
  observer.observe(shadow, { childList: true, subtree: true });
});

const mountQuirebaseToolbar = async (container) => {
  const shadow = container.shadowRoot;
  const toolbar = await waitForShadowElement(
    shadow,
    '[data-epdf-i="quirebase-toolbar"]',
  );
  const style = document.createElement("style");
  style.dataset.quirebase = "toolbar";
  style.textContent = `
    .embedpdf-snippet-root { position: relative; }
    #pdf-toolbar-controls { display: flex; align-items: center; gap: .5rem; min-width: 0;
      margin-left: auto; padding-left: .75rem; border-left: 1px solid var(--ep-border-default); }
    #pdf-toolbar-controls label { display: flex; align-items: center; gap: .4rem;
      color: var(--ep-foreground-secondary); font-size: .875rem; white-space: nowrap; }
    #pdf-toolbar-controls select, #pdf-toolbar-controls button,
    #pdf-download-options select, #pdf-download-options button { min-height: 32px; border-radius: .375rem;
      border: 1px solid var(--ep-border-default); background: var(--ep-background-surface);
      color: var(--ep-foreground-primary); padding: .3rem .55rem; }
    #pdf-toolbar-controls select { max-width: 10rem; }
    #pdf-toolbar-controls button:hover, #pdf-download-options button:hover {
      background: var(--ep-interactive-hover); }
    #pdf-status { max-width: 18rem; overflow: hidden; color: var(--ep-foreground-secondary);
      font-size: .8rem; text-overflow: ellipsis; white-space: nowrap; }
    #pdf-download-options { position: absolute; z-index: 120; top: 49px; right: .75rem;
      display: grid; width: min(24rem, calc(100% - 1.5rem)); padding: .8rem; gap: .75rem;
      border: 1px solid var(--ep-border-default); border-radius: 0 0 .65rem .65rem;
      background: var(--ep-background-surface); color: var(--ep-foreground-primary);
      box-shadow: 0 12px 28px rgb(0 0 0 / 20%); }
    #pdf-download-options[hidden] { display: none; }
    #pdf-download-options label { display: grid; gap: .35rem; font-size: .875rem; }
    #pdf-download-options .export-check { display: flex; align-items: center; gap: .5rem; }
    #pdf-download-options .option-panel-heading { display: grid; }
    #pdf-download-options small, #pdf-download-options p { margin: 0;
      color: var(--ep-foreground-secondary); font-size: .8rem; }
    @container (max-width: 900px) {
      #pdf-toolbar-controls label > :first-child, #pdf-status { display: none; }
      #pdf-toolbar-controls select { max-width: 7rem; }
    }
  `;
  shadow.append(style);
  toolbarControls.hidden = false;
  toolbar.append(toolbarControls);
  shadow.append(downloadOptions);
  downloadOptionsButton.addEventListener("click", () => {
    downloadOptions.hidden = !downloadOptions.hidden;
    downloadOptionsButton.setAttribute("aria-expanded", String(!downloadOptions.hidden));
  });
  shadow.addEventListener("click", (event) => {
    const path = event.composedPath();
    if (!path.includes(downloadOptions) && !path.includes(downloadOptionsButton)) {
      downloadOptions.hidden = true;
      downloadOptionsButton.setAttribute("aria-expanded", "false");
    }
  });
};

const waitForDocument = (documentManagerApi) => new Promise((resolve, reject) => {
  let settled = false;
  let unsubscribeOpened = () => {};
  let unsubscribeError = () => {};
  let timer;
  const finish = (callback, value) => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    unsubscribeOpened();
    unsubscribeError();
    callback(value);
  };
  const openedSubscription = documentManagerApi.onDocumentOpened((documentState) => {
    if (documentState.id === revisionId) finish(resolve, documentState);
  });
  unsubscribeOpened = openedSubscription;
  if (settled) openedSubscription();
  if (!settled) {
    const errorSubscription = documentManagerApi.onDocumentError((event) => {
      if (event.documentId === revisionId) finish(reject, new Error(event.message));
    });
    unsubscribeError = errorSubscription;
    if (settled) errorSubscription();
  }
  if (!settled) {
    timer = window.setTimeout(
      () => finish(reject, new Error(messages.loadTimedOut)),
      PDF_LOAD_TIMEOUT_MS,
    );
  }
  const state = documentManagerApi.getDocumentState(revisionId);
  if (state?.status === "loaded") finish(resolve, state);
  if (state?.status === "error") finish(reject, new Error(state.error || messages.loadFailed));
});

const showLoadError = (error) => {
  const text = message("unableToOpen", { message: error.message });
  status.textContent = text;
  target.dataset.loadError = text;
};

const api = async (url, options = {}) => {
  const response = await csrfFetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    const error = new Error((await response.text()) || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.status === 204 ? null : response.json();
};

const enqueue = (id, operation) => {
  const previous = pendingWrites.get(id) || Promise.resolve();
  const next = previous.catch(() => {}).then(operation);
  pendingWrites.set(id, next);
  next.finally(() => {
    if (pendingWrites.get(id) === next) pendingWrites.delete(id);
  });
  return next;
};

const drainWrites = async () => Promise.allSettled([...pendingWrites.values()]);

const annotationIsLoaded = (id) => annotationApi
  .forDocument(revisionId)
  .getAnnotations()
  .some((tracked) => tracked.object.id === id);

const loadAnnotations = async () => {
  const project = projectPicker.value ? `&project_id=${encodeURIComponent(projectPicker.value)}` : "";
  const response = await api(`${annotationUrl}?revision_id=${revisionId}${project}`);
  for (const id of databaseIds) {
    const old = metadata.get(id);
    const reply = replyMetadata.get(id);
    const parent = reply ? metadata.get(reply.annotation_id) : null;
    const pageIndex = old?.page_index ?? parent?.page_index;
    if (pageIndex !== undefined) annotationApi.purgeAnnotation(pageIndex, id, revisionId);
  }
  databaseIds.clear();
  replyMetadata.clear();
  metadata.clear();
  annotationTombstones.clear();
  replyTombstones.clear();
  for (const annotation of response.annotations) {
    databaseIds.add(annotation.id);
    metadata.set(annotation.id, annotation);
    for (const reply of annotation.replies) {
      databaseIds.add(reply.id);
      replyMetadata.set(reply.id, reply);
    }
  }
  annotationApi.importAnnotations(response.annotations.flatMap((annotation) => [
    { annotation: vendorFromCanonical(annotation) },
    ...annotation.replies.map((reply) => ({
      annotation: vendorReplyFromCanonical(annotation, reply),
    })),
  ]));
};

const recoverAnnotation = async (id, pageIndex) => {
  try {
    const project = projectPicker.value ? `&project_id=${encodeURIComponent(projectPicker.value)}` : "";
    const response = await api(`${annotationUrl}?revision_id=${revisionId}${project}`);
    const snapshot = response.annotations.find((annotation) => annotation.id === id);
    annotationApi.purgeAnnotation(pageIndex, id, revisionId);
    databaseIds.delete(id);
    metadata.delete(id);
    for (const [replyId, reply] of replyMetadata) {
      if (reply.annotation_id !== id) continue;
      databaseIds.delete(replyId);
      replyMetadata.delete(replyId);
    }
    if (snapshot) {
      databaseIds.add(id);
      metadata.set(id, snapshot);
      for (const reply of snapshot.replies) {
        databaseIds.add(reply.id);
        replyMetadata.set(reply.id, reply);
      }
      annotationApi.importAnnotations([
        { annotation: vendorFromCanonical(snapshot) },
        ...snapshot.replies.map((reply) => ({
          annotation: vendorReplyFromCanonical(snapshot, reply),
        })),
      ]);
    }
  } catch {
    annotationApi.purgeAnnotation(pageIndex, id, revisionId);
    databaseIds.delete(id);
    metadata.delete(id);
  }
  status.textContent = messages.syncFailed;
};

const recoverReply = async (id, parentId, pageIndex) => {
  try {
    const project = projectPicker.value ? `&project_id=${encodeURIComponent(projectPicker.value)}` : "";
    const response = await api(`${annotationUrl}?revision_id=${revisionId}${project}`);
    const parent = response.annotations.find((annotation) => annotation.id === parentId);
    const snapshot = parent?.replies.find((reply) => reply.id === id);
    annotationApi.purgeAnnotation(pageIndex, id, revisionId);
    databaseIds.delete(id);
    replyMetadata.delete(id);
    if (parent && snapshot) {
      databaseIds.add(id);
      replyMetadata.set(id, snapshot);
      annotationApi.importAnnotations([{
        annotation: vendorReplyFromCanonical(parent, snapshot),
      }]);
    }
  } catch {
    annotationApi.purgeAnnotation(pageIndex, id, revisionId);
    databaseIds.delete(id);
    replyMetadata.delete(id);
  }
  status.textContent = messages.syncFailed;
};

const lockNativeAnnotations = (documentId) => {
  for (const tracked of annotationApi.forDocument(documentId).getAnnotations()) {
    const object = tracked.object;
    if (databaseIds.has(object.id)) continue;
    nativeIds.add(object.id);
    const flags = [...new Set([...(object.flags || []), "readOnly"] )];
    annotationApi.syncAnnotationObject(object.id, { flags }, documentId);
  }
};

const initializeAnnotations = () => {
  if (!initialAnnotationLoad) {
    initialAnnotationLoad = loadAnnotations()
      .then(() => { status.textContent = message("pages", { count: pageGeometry.length }); })
      .catch((error) => { status.textContent = message("unableToOpen", { message: error.message }); });
  }
  return initialAnnotationLoad;
};

const handleAnnotationEvent = (event) => {
  if (event.type === "loaded") {
    lockNativeAnnotations(event.documentId);
    initializeAnnotations();
    return;
  }
  if (event.documentId !== revisionId || nativeIds.has(event.annotation.id)) return;
  const parentId = event.annotation.inReplyToId;
  if (parentId) {
    const id = event.annotation.id;
    enqueue(id, async () => {
      status.textContent = messages.saving;
      try {
        if (event.type === "create") {
          const pendingParentWrite = pendingWrites.get(parentId);
          if (pendingParentWrite) await pendingParentWrite;
          if (databaseIds.has(id)) {
            status.textContent = messages.saved;
            return;
          }
          const tombstone = replyTombstones.get(id);
          const saved = tombstone
            ? await api(
              `${annotationUrl}/${parentId}/replies/${id}/restore?version=${tombstone.version}`,
              { method: "POST" },
            )
            : await api(`${annotationUrl}/${parentId}/replies`, {
              method: "POST",
              body: JSON.stringify({ id, body: event.annotation.contents || "" }),
            });
          replyTombstones.delete(id);
          databaseIds.add(id);
          replyMetadata.set(id, saved);
        } else if (event.type === "update") {
          const existing = replyMetadata.get(id);
          if (!existing) return;
          const updatedObject = { ...event.annotation, ...event.patch };
          const saved = await api(`${annotationUrl}/${parentId}/replies/${id}`, {
            method: "PATCH",
            body: JSON.stringify({
              version: existing.version,
              body: updatedObject.contents || "",
            }),
          });
          replyMetadata.set(id, saved);
          const parent = metadata.get(parentId);
          if (parent) {
            annotationApi.syncAnnotationObject(
              id,
              vendorReplyFromCanonical(parent, saved),
              revisionId,
            );
          }
        } else if (event.type === "delete") {
          const existing = replyMetadata.get(id);
          if (!existing) return;
          if (!annotationIsLoaded(parentId)) return;
          await api(
            `${annotationUrl}/${parentId}/replies/${id}?version=${existing.version}`,
            { method: "DELETE" },
          );
          replyTombstones.set(id, { ...existing, version: existing.version + 1 });
          databaseIds.delete(id);
          replyMetadata.delete(id);
        }
        status.textContent = messages.saved;
      } catch (error) {
        if (event.type === "create") {
          annotationApi.purgeAnnotation(event.pageIndex, id, revisionId);
          status.textContent = messages.syncFailed;
        } else {
          await recoverReply(id, parentId, event.pageIndex);
        }
      }
    });
    return;
  }
  if (event.type === "create" && event.annotation.type === PdfAnnotationSubtype.TEXT) {
    uiApi.forDocument(revisionId).setActiveSidebar("right", "main", "comment-panel");
  }
  const id = event.annotation.id;
  enqueue(id, async () => {
    status.textContent = messages.saving;
    try {
      if (event.type === "create") {
        if (databaseIds.has(id)) {
          status.textContent = messages.saved;
          return;
        }
        const tombstone = annotationTombstones.get(id);
        const saved = tombstone
          ? await api(`${annotationUrl}/${id}/restore?version=${tombstone.version}`, {
            method: "POST",
          })
          : await api(annotationUrl, {
            method: "POST",
            body: JSON.stringify({
              id,
              revision_id: revisionId,
              ...visibility(),
              ...canonicalFromVendor(event.annotation, event.pageIndex),
            }),
          });
        annotationTombstones.delete(id);
        databaseIds.add(id);
        metadata.set(id, saved);
        for (const reply of saved.replies) {
          databaseIds.add(reply.id);
          replyMetadata.set(reply.id, reply);
        }
      } else if (event.type === "update") {
        const existing = metadata.get(id);
        if (!existing) return;
        const updatedObject = { ...event.annotation, ...event.patch };
        const canonical = canonicalFromVendor(updatedObject, event.pageIndex, existing);
        const saved = await api(`${annotationUrl}/${id}`, {
          method: "PATCH",
          body: JSON.stringify({
            version: existing.version,
            scope: existing.scope,
            project_id: existing.project_id,
            ...canonical,
          }),
        });
        metadata.set(id, saved);
        annotationApi.syncAnnotationObject(id, vendorFromCanonical(saved), revisionId);
      } else if (event.type === "delete") {
        const existing = metadata.get(id);
        if (!existing) return;
        await api(`${annotationUrl}/${id}?version=${existing.version}`, { method: "DELETE" });
        annotationTombstones.set(id, { ...existing, version: existing.version + 1 });
        databaseIds.delete(id);
        metadata.delete(id);
        for (const reply of existing.replies) {
          databaseIds.delete(reply.id);
          replyMetadata.delete(reply.id);
        }
      }
      status.textContent = messages.saved;
    } catch (error) {
      if (event.type === "create") {
        annotationApi.purgeAnnotation(event.pageIndex, id, revisionId);
        status.textContent = messages.syncFailed;
      } else {
        await recoverAnnotation(id, event.pageIndex);
      }
    }
  });
};

const viewer = EmbedPDF.init({
  type: "container",
  target,
  wasmUrl,
  fontFallback: null,
  fonts: { ui: null, signature: null },
  tabBar: "never",
  disabledCategories,
  documentManager: {
    initialDocuments: [{
      url: contentUrl,
      documentId: revisionId,
      name: document.title,
      requestOptions: { credentials: "same-origin" },
    }],
  },
  i18n: { defaultLocale: embedPdfLocale },
  ui: { schema: uiSchema },
  stamp: { manifests: [], defaultLibrary: false },
  annotations: {
    autoCommit: false,
    annotationAuthor: root.dataset.author,
    selectAfterCreate: true,
    editAfterCreate: true,
  },
  permissions: {
    overrides: { print: false, copy: true, modifyAnnotations: editableDocument },
  },
});

try {
  registry = await viewer.registry;
  const documentManagerApi = registry.getPlugin("document-manager").provides();
  const documentReady = waitForDocument(documentManagerApi);
  annotationApi = registry.getPlugin("annotation").provides();
  uiApi = registry.getPlugin("ui").provides();
  annotationApi.onAnnotationEvent(handleAnnotationEvent);
  await registry.pluginsReady();
  await mountQuirebaseToolbar(viewer);
  await documentReady;
  target.removeAttribute("data-load-error");
  lockNativeAnnotations(revisionId);
  await initializeAnnotations();
  if (!editableDocument) annotationApi.setLocked({ type: LockModeType.All }, revisionId);
} catch (error) {
  showLoadError(error);
}

projectPicker.addEventListener("change", async () => {
  await drainWrites();
  try {
    await loadAnnotations();
  } catch (error) {
    status.textContent = message("unableToOpen", { message: error.message });
  }
});

const browserTimezone = () => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
};

downloadCurrentButton.addEventListener("click", () => {
  const includeAnnotations = exportAnnotations.checked ? 1 : 0;
  const selectedProject = downloadProject.value;
  const params = new URLSearchParams({
    include_annotations: String(includeAnnotations),
    timezone: browserTimezone(),
  });
  if (selectedProject && includeAnnotations) params.set("project_id", selectedProject);
  status.textContent = messages.downloading;
  window.location.assign(`${exportUrl}?${params.toString()}`);
});

window.addEventListener("beforeunload", (event) => {
  if (!pendingWrites.size) return;
  event.preventDefault();
  event.returnValue = "";
});

window.addEventListener("pagehide", () => {
  if (disposed) return;
  disposed = true;
  if (!pendingWrites.size) registry?.destroy();
});
