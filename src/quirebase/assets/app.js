import Alpine from "@alpinejs/csp";

const matchesTag = (name, query) => !query || Boolean(name && name.toLowerCase().includes(query));

const exportPreferenceDefaults = {
  citation: {
    format: "csl",
    style: "apa",
    includeAbstract: true,
    preserveCase: false,
    includeIdentifiers: false,
    includeCustomFields: false,
    encoding: "unicode",
    journalMode: "full",
    doiPolicy: "include",
    urlPolicy: "include",
    excludedFields: "",
    sortBy: "input",
    citationKeyFormula: "auth.capitalize + year + shorttitle(1).capitalize",
    citationKeyForceAscii: true,
  },
  document: {
    includeAnnotations: false,
    includeSupplements: false,
  },
};

const validExportFormats = new Set(["csl", "bibtex", "biblatex", "ris", "endnote"]);
const citationBooleanPreferences = [
  "includeAbstract",
  "preserveCase",
  "includeIdentifiers",
  "includeCustomFields",
  "citationKeyForceAscii",
];
const documentBooleanPreferences = ["includeAnnotations", "includeSupplements"];

function readExportPreferences(key) {
  const preferences = {
    citation: { ...exportPreferenceDefaults.citation },
    document: { ...exportPreferenceDefaults.document },
  };
  if (!key) return preferences;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) || "null");
    if (!parsed || parsed.schemaVersion !== 1) return preferences;
    if (validExportFormats.has(parsed.citation?.format)) {
      preferences.citation.format = parsed.citation.format;
    }
    if (typeof parsed.citation?.style === "string" && parsed.citation.style.length <= 200) {
      preferences.citation.style = parsed.citation.style;
    }
    citationBooleanPreferences.forEach((field) => {
      if (typeof parsed.citation?.[field] === "boolean") {
        preferences.citation[field] = parsed.citation[field];
      }
    });
    const citationEnumPreferences = {
      encoding: new Set(["unicode", "latex"]),
      journalMode: new Set(["full", "abbreviated", "prefer_abbreviated"]),
      doiPolicy: new Set(["include", "omit"]),
      urlPolicy: new Set(["include", "omit", "omit_when_doi"]),
      sortBy: new Set(["input", "citation_key", "author", "year", "title"]),
    };
    Object.entries(citationEnumPreferences).forEach(([field, allowed]) => {
      if (allowed.has(parsed.citation?.[field])) {
        preferences.citation[field] = parsed.citation[field];
      }
    });
    if (
      !citationEnumPreferences.journalMode.has(parsed.citation?.journalMode)
      && parsed.citation?.abbreviateJournal === true
    ) {
      preferences.citation.journalMode = "prefer_abbreviated";
    }
    ["excludedFields", "citationKeyFormula"].forEach((field) => {
      if (typeof parsed.citation?.[field] === "string" && parsed.citation[field].length <= 1000) {
        preferences.citation[field] = parsed.citation[field];
      }
    });
    documentBooleanPreferences.forEach((field) => {
      if (typeof parsed.document?.[field] === "boolean") {
        preferences.document[field] = parsed.document[field];
      }
    });
  } catch {
    return preferences;
  }
  return preferences;
}

function storeExportPreferences(key, section, values) {
  if (!key) return;
  const preferences = readExportPreferences(key);
  preferences[section] = { ...preferences[section], ...values };
  try {
    window.localStorage.setItem(key, JSON.stringify({ schemaVersion: 1, ...preferences }));
  } catch {
    // Export must continue when browser policy or storage quota blocks persistence.
  }
}

function resetExportPreferences(key, sections) {
  if (!key) return;
  const sectionsToReset = Array.isArray(sections) ? sections : [sections];
  const preferences = readExportPreferences(key);
  sectionsToReset.forEach((section) => {
    preferences[section] = { ...exportPreferenceDefaults[section] };
  });
  try {
    window.localStorage.setItem(key, JSON.stringify({ schemaVersion: 1, ...preferences }));
  } catch {
    // best-effort
  }
}

async function fetchCitationStyles(query, limit, includeKey) {
  const params = new URLSearchParams({ query, limit: String(limit) });
  if (includeKey) params.set("include", includeKey);
  const response = await fetch(`/api/citation-styles?${params.toString()}`);
  if (!response.ok) throw new Error("failed to load citation styles");
  const data = await response.json();
  return data.styles || [];
}

function browserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
 }

function resolveCitationStyle(styles, requestedKey) {
  if (!Array.isArray(styles) || styles.length === 0) return requestedKey;
  return styles.some((style) => style.key === requestedKey)
    ? requestedKey
    : styles[0].key;
}

function readSidebarCollapsed() {
  try {
    const collapsed = JSON.parse(window.localStorage.getItem("quirebase:sidebar-collapsed") || "false");
    return typeof collapsed === "boolean" ? collapsed : false;
  } catch {
    return false;
  }
}

Alpine.data("appShell", () => ({
  sidebarOpen: false,
  sidebarCollapsed: readSidebarCollapsed(),
  init() {
    if (this.sidebarCollapsed) {
      document.documentElement.classList.add("sidebar-collapsed");
    } else {
      document.documentElement.classList.remove("sidebar-collapsed");
    }
  },
  toggleSidebar() {
    this.sidebarOpen = !this.sidebarOpen;
  },
  closeSidebar() {
    this.sidebarOpen = false;
  },
  toggleCollapse() {
    document.documentElement.classList.add("sidebar-animatable");
    this.sidebarCollapsed = !this.sidebarCollapsed;
    try {
      window.localStorage.setItem(
        "quirebase:sidebar-collapsed",
        JSON.stringify(this.sidebarCollapsed),
      );
    } catch {
      // ignore storage failure
    }
    if (this.sidebarCollapsed) {
      document.documentElement.classList.add("sidebar-collapsed");
    } else {
      document.documentElement.classList.remove("sidebar-collapsed");
    }
  },
  openDetails() {
    const details = document.querySelector(this.$event.currentTarget.hash);
    if (details) details.open = true;
  },
}));

Alpine.data("passwordStrength", () => ({
  password: "",
  score: -1,
  async init() {
    try {
      const [
        { ZxcvbnFactory },
        zxcvbnCommonPackage,
        zxcvbnEnglishPackage,
      ] = await Promise.all([
        import("@zxcvbn-ts/core"),
        import("@zxcvbn-ts/language-common"),
        import("@zxcvbn-ts/language-en"),
      ]);
      const passwordStrengthAnalyzer = new ZxcvbnFactory({
        dictionary: {
          ...zxcvbnCommonPackage.dictionary,
          ...zxcvbnEnglishPackage.dictionary,
        },
        graphs: zxcvbnCommonPackage.adjacencyGraphs,
      });
      this.$watch("password", (value) => {
        this.score = value ? passwordStrengthAnalyzer.check(value).score : -1;
      });
      if (this.password) {
        this.score = passwordStrengthAnalyzer.check(this.password).score;
      }
    } catch {
      this.score = -1;
    }
  },
}));

Alpine.data("userSettings", () => ({
  format: "csl",
  style: "apa",
  query: "",
  styles: [],
  includeAbstract: true,
  preserveCase: false,
  includeIdentifiers: false,
  includeCustomFields: false,
  encoding: "unicode",
  journalMode: "full",
  doiPolicy: "include",
  urlPolicy: "include",
  excludedFields: "",
  sortBy: "input",
  citationKeyFormula: exportPreferenceDefaults.citation.citationKeyFormula,
  lastValidCitationKeyFormula: exportPreferenceDefaults.citation.citationKeyFormula,
  citationKeyForceAscii: true,
  citationKeyPreview: "",
  citationKeyPreviewError: false,
  citationKeyPreviewRequest: 0,
  includeAnnotations: false,
  includeSupplements: false,
  savedToast: false,
  storageKey: "",
  sidebarCollapsed: readSidebarCollapsed(),
  init() {
    this.storageKey = this.$root.dataset.exportPreferencesKey || "";
    const prefs = readExportPreferences(this.storageKey);
    this.format = prefs.citation.format;
    this.style = prefs.citation.style;
    this.includeAbstract = prefs.citation.includeAbstract;
    this.preserveCase = prefs.citation.preserveCase;
    this.includeIdentifiers = prefs.citation.includeIdentifiers;
    this.includeCustomFields = prefs.citation.includeCustomFields;
    this.encoding = prefs.citation.encoding;
    this.journalMode = prefs.citation.journalMode;
    this.doiPolicy = prefs.citation.doiPolicy;
    this.urlPolicy = prefs.citation.urlPolicy;
    this.excludedFields = prefs.citation.excludedFields;
    this.sortBy = prefs.citation.sortBy;
    this.citationKeyFormula = prefs.citation.citationKeyFormula;
    this.lastValidCitationKeyFormula = prefs.citation.citationKeyFormula;
    this.citationKeyForceAscii = prefs.citation.citationKeyForceAscii;
    this.includeAnnotations = prefs.document.includeAnnotations;
    this.includeSupplements = prefs.document.includeSupplements;
    this.loadStyles();
    [
      "format",
      "style",
      "encoding",
      "journalMode",
      "doiPolicy",
      "urlPolicy",
      "excludedFields",
      "sortBy",
      ...citationBooleanPreferences,
    ].forEach((field) => {
      this.$watch(field, () => this.save());
    });
    documentBooleanPreferences.forEach((field) => {
      this.$watch(field, () => this.save());
    });
    this.$watch("citationKeyFormula", () => this.previewCitationKey(true));
    this.$watch("citationKeyForceAscii", () => this.previewCitationKey());
    this.previewCitationKey();
  },
  toggleCollapse() {
    this.sidebarCollapsed = !this.sidebarCollapsed;
    try {
      window.localStorage.setItem(
        "quirebase:sidebar-collapsed",
        JSON.stringify(this.sidebarCollapsed),
      );
    } catch {
      // ignore
    }
    const shellEl = document.querySelector(".app-layout");
    if (shellEl && window.Alpine && window.Alpine.$data(shellEl)) {
      window.Alpine.$data(shellEl).sidebarCollapsed = this.sidebarCollapsed;
    }
  },
  save() {
    storeExportPreferences(this.storageKey, "citation", {
      format: this.format,
      style: this.style,
      includeAbstract: this.includeAbstract,
      preserveCase: this.preserveCase,
      includeIdentifiers: this.includeIdentifiers,
      includeCustomFields: this.includeCustomFields,
      encoding: this.encoding,
      journalMode: this.journalMode,
      doiPolicy: this.doiPolicy,
      urlPolicy: this.urlPolicy,
      excludedFields: this.excludedFields,
      sortBy: this.sortBy,
      citationKeyFormula: this.lastValidCitationKeyFormula,
      citationKeyForceAscii: this.citationKeyForceAscii,
    });
    storeExportPreferences(this.storageKey, "document", {
      includeAnnotations: this.includeAnnotations,
      includeSupplements: this.includeSupplements,
    });
    this.savedToast = true;
    setTimeout(() => {
      this.savedToast = false;
    }, 2000);
  },
  resetDefaults() {
    resetExportPreferences(this.storageKey, ["citation", "document"]);
    this.format = exportPreferenceDefaults.citation.format;
    this.style = exportPreferenceDefaults.citation.style;
    this.includeAbstract = exportPreferenceDefaults.citation.includeAbstract;
    this.preserveCase = exportPreferenceDefaults.citation.preserveCase;
    this.includeIdentifiers = exportPreferenceDefaults.citation.includeIdentifiers;
    this.includeCustomFields = exportPreferenceDefaults.citation.includeCustomFields;
    this.encoding = exportPreferenceDefaults.citation.encoding;
    this.journalMode = exportPreferenceDefaults.citation.journalMode;
    this.doiPolicy = exportPreferenceDefaults.citation.doiPolicy;
    this.urlPolicy = exportPreferenceDefaults.citation.urlPolicy;
    this.excludedFields = exportPreferenceDefaults.citation.excludedFields;
    this.sortBy = exportPreferenceDefaults.citation.sortBy;
    this.citationKeyFormula = exportPreferenceDefaults.citation.citationKeyFormula;
    this.lastValidCitationKeyFormula = exportPreferenceDefaults.citation.citationKeyFormula;
    this.citationKeyForceAscii = exportPreferenceDefaults.citation.citationKeyForceAscii;
    this.includeAnnotations = exportPreferenceDefaults.document.includeAnnotations;
    this.includeSupplements = exportPreferenceDefaults.document.includeSupplements;
    this.savedToast = true;
    setTimeout(() => {
      this.savedToast = false;
    }, 2000);
  },
  async loadStyles() {
    try {
      const response = await fetch("/api/citation-styles");
      if (response.ok) {
        const data = await response.json();
        this.styles = data.styles || [];
      }
    } catch {
      this.styles = [];
    }
  },
  async searchStyles() {
    if (!this.query.trim()) {
      return this.loadStyles();
    }
    try {
      const response = await fetch(`/api/citation-styles?query=${encodeURIComponent(this.query.trim())}`);
      if (response.ok) {
        const data = await response.json();
        this.styles = data.styles || [];
      }
    } catch {
      this.styles = [];
    }
  },
  async previewCitationKey(saveWhenValid = false) {
    const request = ++this.citationKeyPreviewRequest;
    const formula = this.citationKeyFormula;
    this.citationKeyPreviewError = false;
    const params = new URLSearchParams({
      formula,
      force_ascii: String(this.citationKeyForceAscii),
    });
    try {
      const response = await fetch(`/api/citation-key-preview?${params.toString()}`);
      if (!response.ok) throw new Error("invalid formula");
      const data = await response.json();
      if (request !== this.citationKeyPreviewRequest) return;
      this.citationKeyPreview = data.key || "";
      this.lastValidCitationKeyFormula = formula;
      if (saveWhenValid) this.save();
    } catch {
      if (request !== this.citationKeyPreviewRequest) return;
      this.citationKeyPreview = "";
      this.citationKeyPreviewError = true;
    }
  },
}));

Alpine.data("libraryWorkspace", () => ({
  action: "",
  style: "apa",
  includeAbstract: true,
  preserveCase: false,
  includeIdentifiers: false,
  includeCustomFields: false,
  encoding: "unicode",
  journalMode: "full",
  doiPolicy: "include",
  urlPolicy: "include",
  excludedFields: "",
  sortBy: "input",
  citationKeyFormula: exportPreferenceDefaults.citation.citationKeyFormula,
  citationKeyForceAscii: exportPreferenceDefaults.citation.citationKeyForceAscii,
  includeAnnotations: false,
  includeSupplements: false,
  storageKey: "",
  filtersOpen: true,
  selected: [],
  init() {
    this.storageKey = this.$root.dataset.exportPreferencesKey || "";
    const preferences = readExportPreferences(this.storageKey).citation;
    this.style = preferences.style;
    this.includeAbstract = preferences.includeAbstract;
    this.preserveCase = preferences.preserveCase;
    this.includeIdentifiers = preferences.includeIdentifiers;
    this.includeCustomFields = preferences.includeCustomFields;
    this.encoding = preferences.encoding;
    this.journalMode = preferences.journalMode;
    this.doiPolicy = preferences.doiPolicy;
    this.urlPolicy = preferences.urlPolicy;
    this.excludedFields = preferences.excludedFields;
    this.sortBy = preferences.sortBy;
    this.citationKeyFormula = preferences.citationKeyFormula;
    this.citationKeyForceAscii = preferences.citationKeyForceAscii;
    const documentPreferences = readExportPreferences(this.storageKey).document;
    this.includeAnnotations = documentPreferences.includeAnnotations;
    this.includeSupplements = documentPreferences.includeSupplements;
  },
  browserTimezone,
  get allSelected() {
    const checkboxes = this.$root.querySelectorAll('input[name="item_ids"]');
    return checkboxes.length > 0 && this.selected.length === checkboxes.length;
  },
  get selectionLabel() {
    return this.$root.dataset.selectionLabel.replace("{count}", this.selected.length);
  },
  toggleFilters() {
    this.filtersOpen = !this.filtersOpen;
  },
  toggleAll() {
    this.selected = this.$event.target.checked
      ? [...this.$root.querySelectorAll('input[name="item_ids"]')].map((node) => node.value)
      : [];
  },
}));

Alpine.data("importWorkspace", () => ({
  active: "doi",
  pdfFileNames: [],
  selectMethod() {
    this.active = this.$event.currentTarget.dataset.method;
  },
  addPdfFiles() {
    const input = this.$event.currentTarget;
    const selectedByFingerprint = new Map();
    const previouslySelected = input._quirebaseSelectedFiles || [];
    [...previouslySelected, ...Array.from(input.files || [])].forEach((file) => {
      const fingerprint = `${file.name}:${file.size}:${file.lastModified}`;
      selectedByFingerprint.set(fingerprint, file);
    });
    const selectedFiles = [...selectedByFingerprint.values()];
    if (typeof DataTransfer === "function") {
      const transfer = new DataTransfer();
      selectedFiles.forEach((file) => transfer.items.add(file));
      input.files = transfer.files;
    }
    input._quirebaseSelectedFiles = selectedFiles;
    this.pdfFileNames = selectedFiles.map((file) => file.name);
  },
}));

function remotePdfFilename(url) {
  const name = decodeURIComponent(new URL(url).pathname.split("/").pop() || "");
  return name.toLowerCase().endsWith(".pdf") ? name : "downloaded.pdf";
}

Alpine.data("remotePdfUpload", () => ({
  url: "",
  inferred: false,
  downloading: false,
  error: "",
  init() {
    const externalUrls = JSON.parse(this.$root.dataset.externalUrls || "[]");
    this.url = externalUrls.find((url) => url.toLowerCase().includes(".pdf")) || "";
    this.inferred = Boolean(this.url);
  },
  async downloadAndUpload() {
    this.downloading = true;
    this.error = "";
    try {
      const download = await fetch(this.url);
      if (!download.ok) throw new Error("PDF download failed");
      const blob = await download.blob();
      const form = new FormData();
      form.append("pdf", new File([blob], remotePdfFilename(this.url), { type: blob.type }));
      const upload = await fetch(this.$root.action, { method: "POST", body: form });
      if (!upload.ok) throw new Error("PDF upload failed");
      window.location.reload();
    } catch {
      this.error = this.$root.dataset.errorMessage;
    } finally {
      this.downloading = false;
    }
  },
}));

Alpine.data("toolsWorkspace", () => ({
  active: "duplicates",
  init() {
    const hash = window.location.hash ? window.location.hash.replace("#", "") : "";
    const initial = this.$root.dataset.initialActive;
    if (["duplicates", "tags", "citation-styles"].includes(hash)) {
      this.active = hash;
    } else if (initial && ["duplicates", "tags", "citation-styles"].includes(initial)) {
      this.active = initial;
    }
  },
  selectTool(tool) {
    this.active = tool;
    if (window.history && window.history.replaceState) {
      window.history.replaceState(null, "", `#${tool}`);
    }
  },
}));

Alpine.data("tagManager", () => ({
  tagFilter: "",
  page: 1,
  pageSize: 20,
  tags: [],
  visibleIds: new Set(),
  init() {
    const script = document.getElementById("tools-tags-data");
    if (script && script.textContent) {
      try {
        this.tags = JSON.parse(script.textContent);
      } catch (e) {
        this.tags = [];
      }
    }
    this.refresh();
    this.$watch("tagFilter", () => {
      this.page = 1;
      this.refresh();
    });
    this.$watch("page", () => this.refresh());
  },
  refresh() {
    const start = (this.page - 1) * this.pageSize;
    this.visibleIds = new Set(this.filtered.slice(start, start + this.pageSize).map((t) => t.id));
  },
  get filtered() {
    const query = this.tagFilter.trim().toLowerCase();
    return this.tags.filter((tag) => matchesTag(tag.name, query));
  },
  get totalPages() {
    return Math.max(1, Math.ceil(this.filtered.length / this.pageSize));
  },
  isTagVisible(tagId) {
    return this.visibleIds.has(tagId);
  },
  prevPage() {
    if (this.page > 1) this.page--;
  },
  nextPage() {
    if (this.page < this.totalPages) this.page++;
  },
}));

Alpine.data("onlineSearch", () => ({
  visibleClauses: 1,
  init() {
    this.visibleClauses = Math.max(1, Math.min(5, Number(this.$root.dataset.initialClauses) || 1));
  },
  addClause() {
    this.visibleClauses = Math.min(5, this.visibleClauses + 1);
  },
  removeClause() {
    if (this.visibleClauses === 1) return;
    const row = this.$root.querySelectorAll(".query-clause")[this.visibleClauses - 1];
    row?.querySelectorAll("input").forEach((input) => { input.value = ""; });
    this.visibleClauses -= 1;
  },
}));

Alpine.data("pdfToolbar", () => ({
  annotationOpen: false,
  downloadOpen: false,
  toggleAnnotations() {
    this.annotationOpen = !this.annotationOpen;
  },
}));

Alpine.data("itemDownload", () => ({
  includeAnnotations: false,
  includeSupplements: false,
  selectedRevisions: [],
  storageKey: "",
  init() {
    this.storageKey = this.$root.dataset.exportPreferencesKey || "";
    const preferences = readExportPreferences(this.storageKey).document;
    this.includeAnnotations = preferences.includeAnnotations;
    this.includeSupplements = preferences.includeSupplements;
  },
  browserTimezone,
  download() {
    const params = new URLSearchParams({
      include_annotations: String(this.includeAnnotations),
      include_supplements: String(this.includeSupplements),
      timezone: browserTimezone(),
    });
    if (this.selectedRevisions.length > 0) {
      params.set("revisions", this.selectedRevisions.join(","));
    }
    window.location.href = `/items/${this.$root.dataset.itemId}/download?${params.toString()}`;
  },
}));

Alpine.data("itemExport", () => ({
  format: "csl",
  style: "apa",
  query: "",
  styles: [],
  includeAbstract: true,
  preserveCase: false,
  includeIdentifiers: false,
  includeCustomFields: false,
  encoding: "unicode",
  journalMode: "full",
  doiPolicy: "include",
  urlPolicy: "include",
  excludedFields: "",
  sortBy: "input",
  citationKeyFormula: exportPreferenceDefaults.citation.citationKeyFormula,
  citationKeyForceAscii: exportPreferenceDefaults.citation.citationKeyForceAscii,
  copied: false,
  copyError: false,
  stylesLoaded: false,
  stylesLoading: false,
  styleRequestId: 0,
  storageKey: "",
  init() {
    this.storageKey = this.$root.dataset.exportPreferencesKey || "";
    const preferences = readExportPreferences(this.storageKey).citation;
    this.format = preferences.format;
    this.style = preferences.style;
    this.includeAbstract = preferences.includeAbstract;
    this.preserveCase = preferences.preserveCase;
    this.includeIdentifiers = preferences.includeIdentifiers;
    this.includeCustomFields = preferences.includeCustomFields;
    this.encoding = preferences.encoding;
    this.journalMode = preferences.journalMode;
    this.doiPolicy = preferences.doiPolicy;
    this.urlPolicy = preferences.urlPolicy;
    this.excludedFields = preferences.excludedFields;
    this.sortBy = preferences.sortBy;
    this.citationKeyFormula = preferences.citationKeyFormula;
    this.citationKeyForceAscii = preferences.citationKeyForceAscii;
    const first = this.$root.querySelector("select[name=style]")?.value;
    this.style = preferences.style || first || "apa";
    this.$watch("format", () => this.loadStyles());
  },
  async loadStyles() {
    if (!this.$root.open || this.format !== "csl") return;
    if (this.stylesLoaded || this.stylesLoading) return;
    await this.searchStyles();
  },
  async searchStyles() {
    const requestId = ++this.styleRequestId;
    this.stylesLoading = true;
    try {
      const styles = await fetchCitationStyles(this.query, 50, this.style);
      if (requestId !== this.styleRequestId) return;
      this.style = resolveCitationStyle(styles, this.style);
      this.styles = styles;
      this.stylesLoaded = true;
    } catch {
      if (requestId !== this.styleRequestId) return;
      this.styles = [];
      this.stylesLoaded = false;
    } finally {
      if (requestId === this.styleRequestId) this.stylesLoading = false;
    }
  },
  params() {
    const params = new URLSearchParams({
      file_format: this.format,
      style: this.style,
      include_abstract: String(this.includeAbstract),
      preserve_case: String(this.preserveCase),
      include_identifiers: String(this.includeIdentifiers),
      include_custom_fields: String(this.includeCustomFields),
      encoding: this.encoding,
      journal_mode: this.journalMode,
      doi_policy: this.doiPolicy,
      url_policy: this.urlPolicy,
      excluded_fields: this.excludedFields,
      sort_by: this.sortBy,
      citation_key_formula: this.citationKeyFormula,
      citation_key_force_ascii: String(this.citationKeyForceAscii),
    });
    return params.toString();
  },
  download() {
    window.location.href = `/documents/${this.$root.dataset.itemId}/citation?${this.params()}`;
  },
  async copy() {
    this.copied = false;
    this.copyError = false;
    try {
      const response = await fetch(
        `/documents/${this.$root.dataset.itemId}/citation-copy?${this.params()}`,
      );
      if (!response.ok) throw new Error("citation request failed");
      const text = await response.text();
      let succeeded = false;
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(text);
          succeeded = true;
        } catch {
          succeeded = false;
        }
      }
      if (!succeeded) {
        const node = document.createElement("textarea");
        node.value = text;
        document.body.appendChild(node);
        node.select();
        try {
          succeeded = document.execCommand("copy");
        } finally {
          node.remove();
        }
      }
      if (!succeeded) throw new Error("clipboard copy failed");
      this.copied = true;
      window.setTimeout(() => { this.copied = false; }, 1800);
    } catch {
      this.copyError = true;
      window.setTimeout(() => { this.copyError = false; }, 1800);
    }
  },
}));

Alpine.data("citationStyleCatalog", () => ({
  query: "",
  styles: [],
  init() { this.search(); },
  search() {
    fetch(`/api/citation-styles?query=${encodeURIComponent(this.query)}&limit=30`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("failed"))))
      .then((data) => { this.styles = (data.styles || []).filter((style) => style.scope === "builtin"); })
      .catch(() => { this.styles = []; });
  },
}));

Alpine.data("tagMatrix", () => ({
  filter: "",
  matches(name) {
    return matchesTag(name, this.query);
  },
  groupMatches(names) {
    return names.some((name) => matchesTag(name, this.query));
  },
  get query() {
    return this.filter.trim().toLowerCase();
  },
}));

Alpine.data("tagMerge", () => ({
  init() {
    this.ensureDifferentTags();
  },
  ensureDifferentTags() {
    const source = this.$root.querySelector('select[name="source_tag_id"]');
    const target = this.$root.querySelector('select[name="target_tag_id"]');
    if (!source || !target) return;
    Array.from(target.options).forEach((option) => {
      option.disabled = option.value === source.value;
    });
    if (target.value === source.value) {
      const alternative = Array.from(target.options).find((option) => !option.disabled);
      if (alternative) target.value = alternative.value;
    }
  },
}));

function makePersonEditor(field, { keepOneRow = false, corresponding = false } = {}) {
  const initialKey = `initial${field[0].toUpperCase()}${field.slice(1)}`;
  const emptyRow = () => {
    const row = { last_name: "", first_name: "", suggestions: [] };
    if (corresponding) row.is_corresponding = false;
    return row;
  };
  return () => ({
    [field]: [],
    init() {
      const placeholder = () => (keepOneRow ? [emptyRow()] : []);
      try {
        const initial = JSON.parse(this.$root.dataset[initialKey] || "[]");
        this[field] = initial.length ? initial : placeholder();
      } catch {
        this[field] = placeholder();
      }
    },
    add() {
      this[field].push(emptyRow());
    },
    remove(index) {
      if (keepOneRow && this[field].length === 1) {
        this[field][0] = emptyRow();
      } else {
        this[field].splice(index, 1);
      }
    },
    moveUp(index) {
      if (index > 0) {
        const item = this[field].splice(index, 1)[0];
        this[field].splice(index - 1, 0, item);
      }
    },
    moveDown(index) {
      if (index < this[field].length - 1) {
        const item = this[field].splice(index, 1)[0];
        this[field].splice(index + 1, 0, item);
      }
    },
    suggest(index) {
      const q = this[field][index].last_name;
      if (!q || q.length < 2) {
        this[field][index].suggestions = [];
        return;
      }
      fetch(`/api/authors/suggest?q=${encodeURIComponent(q)}`)
        .then((res) => (res.ok ? res.json() : []))
        .then((data) => {
          this[field][index].suggestions = data || [];
        })
        .catch(() => {
          this[field][index].suggestions = [];
        });
    },
    selectSuggestion(index, s) {
      this[field][index].last_name = s.last_name;
      this[field][index].first_name = s.first_name || "";
      this[field][index].suggestions = [];
    },
  });
}

Alpine.data("authorEditor", makePersonEditor("authors", { keepOneRow: true, corresponding: true }));
Alpine.data("editorEditor", makePersonEditor("editors"));

window.Alpine = Alpine;
Alpine.start();
