import Alpine from "@alpinejs/csp";

const matchesTag = (name, query) => !query || Boolean(name && name.toLowerCase().includes(query));

const exportPreferenceDefaults = {
  citation: {
    format: "csl",
    style: "apa",
    includeAbstract: true,
    preserveCase: false,
    abbreviateJournal: false,
    includeIdentifiers: false,
    includeCustomFields: false,
  },
  document: {
    includeAnnotations: false,
    includeSupplements: false,
  },
};

const validExportFormats = new Set(["csl", "bibtex", "ris", "endnote"]);
const citationBooleanPreferences = [
  "includeAbstract",
  "preserveCase",
  "abbreviateJournal",
  "includeIdentifiers",
  "includeCustomFields",
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

Alpine.data("appShell", () => ({
  sidebarOpen: false,
  toggleSidebar() {
    this.sidebarOpen = !this.sidebarOpen;
  },
  closeSidebar() {
    this.sidebarOpen = false;
  },
  openDetails() {
    const details = document.querySelector(this.$event.currentTarget.hash);
    if (details) details.open = true;
  },
}));

Alpine.data("libraryWorkspace", () => ({
  action: "",
  style: "apa",
  styleQuery: "",
  citationStyles: [],
  includeAbstract: true,
  preserveCase: false,
  abbreviateJournal: false,
  includeIdentifiers: false,
  includeCustomFields: false,
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
    this.abbreviateJournal = preferences.abbreviateJournal;
    this.includeIdentifiers = preferences.includeIdentifiers;
    this.includeCustomFields = preferences.includeCustomFields;
    const documentPreferences = readExportPreferences(this.storageKey).document;
    this.includeAnnotations = documentPreferences.includeAnnotations;
    this.includeSupplements = documentPreferences.includeSupplements;
    this.$watch("action", (action) => {
      if (action.startsWith("export_")) this.saveExportPreferences(action.replace("export_", ""));
    });
    ["style", ...citationBooleanPreferences].forEach((field) => {
      this.$watch(field, () => this.saveExportPreferences());
    });
    documentBooleanPreferences.forEach((field) => {
      this.$watch(field, () => this.saveDocumentPreferences());
    });
    this.searchCitationStyles();
  },
  saveExportPreferences(format = null) {
    storeExportPreferences(this.storageKey, "citation", {
      format: format || readExportPreferences(this.storageKey).citation.format,
      style: this.style,
      includeAbstract: this.includeAbstract,
      preserveCase: this.preserveCase,
      abbreviateJournal: this.abbreviateJournal,
      includeIdentifiers: this.includeIdentifiers,
      includeCustomFields: this.includeCustomFields,
    });
  },
  saveDocumentPreferences() {
    storeExportPreferences(this.storageKey, "document", {
      includeAnnotations: this.includeAnnotations,
      includeSupplements: this.includeSupplements,
    });
  },
  searchCitationStyles() {
    fetch(`/api/citation-styles?query=${encodeURIComponent(this.styleQuery)}&limit=100`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("failed"))))
      .then((data) => {
        this.citationStyles = data.styles || [];
        if (!this.citationStyles.some((style) => style.key === this.style)) {
          this.style = this.citationStyles[0]?.key || "apa";
        }
      })
      .catch(() => { this.citationStyles = []; });
  },
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
  selectMethod() {
    this.active = this.$event.currentTarget.dataset.method;
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
  storageKey: "",
  init() {
    this.storageKey = this.$root.dataset.exportPreferencesKey || "";
    const preferences = readExportPreferences(this.storageKey).document;
    this.includeAnnotations = preferences.includeAnnotations;
    this.includeSupplements = preferences.includeSupplements;
    documentBooleanPreferences.forEach((field) => {
      this.$watch(field, () => this.saveExportPreferences());
    });
  },
  saveExportPreferences() {
    storeExportPreferences(this.storageKey, "document", {
      includeAnnotations: this.includeAnnotations,
      includeSupplements: this.includeSupplements,
    });
  },
  download() {
    const params = new URLSearchParams({
      include_annotations: String(this.includeAnnotations),
      include_supplements: String(this.includeSupplements),
    });
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
  abbreviateJournal: false,
  includeIdentifiers: false,
  includeCustomFields: false,
  copied: false,
  storageKey: "",
  init() {
    this.storageKey = this.$root.dataset.exportPreferencesKey || "";
    const preferences = readExportPreferences(this.storageKey).citation;
    this.format = preferences.format;
    this.style = preferences.style;
    this.includeAbstract = preferences.includeAbstract;
    this.preserveCase = preferences.preserveCase;
    this.abbreviateJournal = preferences.abbreviateJournal;
    this.includeIdentifiers = preferences.includeIdentifiers;
    this.includeCustomFields = preferences.includeCustomFields;
    const first = this.$root.querySelector("select[name=style]")?.value;
    this.style = preferences.style || first || "apa";
    ["format", "style", ...citationBooleanPreferences].forEach((field) => {
      this.$watch(field, () => this.saveExportPreferences());
    });
    this.searchStyles();
  },
  saveExportPreferences() {
    storeExportPreferences(this.storageKey, "citation", {
      format: this.format,
      style: this.style,
      includeAbstract: this.includeAbstract,
      preserveCase: this.preserveCase,
      abbreviateJournal: this.abbreviateJournal,
      includeIdentifiers: this.includeIdentifiers,
      includeCustomFields: this.includeCustomFields,
    });
  },
  searchStyles() {
    fetch(`/api/citation-styles?query=${encodeURIComponent(this.query)}`)
      .then((response) => (response.ok ? response.json() : Promise.reject(new Error("failed"))))
      .then((data) => { this.styles = data.styles || []; })
      .catch(() => { this.styles = []; });
  },
  params() {
    const params = new URLSearchParams({
      file_format: this.format,
      style: this.style,
      include_abstract: String(this.includeAbstract),
      preserve_case: String(this.preserveCase),
      abbreviate_journal: String(this.abbreviateJournal),
      include_identifiers: String(this.includeIdentifiers),
      include_custom_fields: String(this.includeCustomFields),
    });
    return params.toString();
  },
  download() {
    window.location.href = `/documents/${this.$root.dataset.itemId}/citation?${this.params()}`;
  },
  async copy() {
    const response = await fetch(`/documents/${this.$root.dataset.itemId}/citation-copy?${this.params()}`);
    if (!response.ok) return;
    const text = await response.text();
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const node = document.createElement("textarea");
      node.value = text;
      document.body.appendChild(node);
      node.select();
      document.execCommand("copy");
      node.remove();
    }
    this.copied = true;
    window.setTimeout(() => { this.copied = false; }, 1800);
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
