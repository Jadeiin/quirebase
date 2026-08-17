import Alpine from "@alpinejs/csp";

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
  filtersOpen: true,
  selected: [],
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
  init() {
    const script = document.getElementById("tools-tags-data");
    if (script && script.textContent) {
      try {
        this.tags = JSON.parse(script.textContent);
      } catch (e) {
        this.tags = [];
      }
    }
    this.$watch("tagFilter", () => {
      this.page = 1;
    });
  },
  get filteredTags() {
    const q = this.tagFilter.trim().toLowerCase();
    if (!q) return this.tags;
    return this.tags.filter((t) => t.name && t.name.toLowerCase().includes(q));
  },
  get totalPages() {
    if (!this.tags || this.tags.length === 0) return 1;
    return Math.max(1, Math.ceil(this.filteredTags.length / this.pageSize));
  },
  get pagedTagIds() {
    if (!this.tags || this.tags.length === 0) return null;
    const start = (this.page - 1) * this.pageSize;
    const paged = this.filteredTags.slice(start, start + this.pageSize);
    return new Set(paged.map((t) => t.id));
  },
  isTagVisible(tagId) {
    if (this.pagedTagIds === null) return true;
    return this.pagedTagIds.has(tagId);
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
  toggleAnnotations() {
    this.annotationOpen = !this.annotationOpen;
  },
}));

Alpine.data("formattedCitation", () => ({
  style: "",
  output: "",
  init() {
    const select = this.$root.querySelector("select");
    this.style = select?.value || "apa";
    this.render();
  },
  render() {
    if (!this.style) {
      const select = this.$root.querySelector("select");
      this.style = select?.value || "apa";
    }
    const url = `/documents/${this.$root.dataset.itemId}/citation-text?style=${encodeURIComponent(this.style)}`;
    fetch(url, { headers: { Accept: "text/plain" } })
      .then((response) => (response.ok ? response.text() : Promise.reject(new Error("failed"))))
      .then((text) => { this.output = text; })
      .catch(() => { this.output = ""; });
  },
  async copy() {
    try {
      await navigator.clipboard.writeText(this.output);
    } catch {
      const node = document.createElement("textarea");
      node.value = this.output;
      document.body.appendChild(node);
      node.select();
      document.execCommand("copy");
      node.remove();
    }
  },
}));

Alpine.data("tagMatrix", () => ({
  filter: "",
  matches(name) {
    if (!this.filter.trim()) return true;
    return name.toLowerCase().includes(this.filter.trim().toLowerCase());
  },
  groupMatches(names) {
    if (!this.filter.trim()) return true;
    const q = this.filter.trim().toLowerCase();
    return names.some((n) => n.toLowerCase().includes(q));
  },
}));

Alpine.data("authorEditor", () => ({
  authors: [],
  init() {
    try {
      const initial = JSON.parse(this.$root.dataset.initialAuthors || "[]");
      this.authors = initial.length
        ? initial
        : [{ last_name: "", first_name: "", is_corresponding: false, suggestions: [] }];
    } catch {
      this.authors = [{ last_name: "", first_name: "", is_corresponding: false, suggestions: [] }];
    }
  },
  add() {
    this.authors.push({ last_name: "", first_name: "", is_corresponding: false, suggestions: [] });
  },
  remove(index) {
    if (this.authors.length > 1) {
      this.authors.splice(index, 1);
    } else {
      this.authors[0] = { last_name: "", first_name: "", is_corresponding: false, suggestions: [] };
    }
  },
  moveUp(index) {
    if (index > 0) {
      const item = this.authors.splice(index, 1)[0];
      this.authors.splice(index - 1, 0, item);
    }
  },
  moveDown(index) {
    if (index < this.authors.length - 1) {
      const item = this.authors.splice(index, 1)[0];
      this.authors.splice(index + 1, 0, item);
    }
  },
  suggest(index) {
    const q = this.authors[index].last_name;
    if (!q || q.length < 2) {
      this.authors[index].suggestions = [];
      return;
    }
    fetch(`/api/authors/suggest?q=${encodeURIComponent(q)}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        this.authors[index].suggestions = data || [];
      })
      .catch(() => {
        this.authors[index].suggestions = [];
      });
  },
  selectSuggestion(index, s) {
    this.authors[index].last_name = s.last_name;
    this.authors[index].first_name = s.first_name || "";
    this.authors[index].suggestions = [];
  },
}));

Alpine.data("editorEditor", () => ({
  editors: [],
  init() {
    try {
      const initial = JSON.parse(this.$root.dataset.initialEditors || "[]");
      this.editors = initial.length ? initial : [];
    } catch {
      this.editors = [];
    }
  },
  add() {
    this.editors.push({ last_name: "", first_name: "", suggestions: [] });
  },
  remove(index) {
    this.editors.splice(index, 1);
  },
  suggest(index) {
    const q = this.editors[index].last_name;
    if (!q || q.length < 2) {
      this.editors[index].suggestions = [];
      return;
    }
    fetch(`/api/authors/suggest?q=${encodeURIComponent(q)}`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        this.editors[index].suggestions = data || [];
      })
      .catch(() => {
        this.editors[index].suggestions = [];
      });
  },
  selectSuggestion(index, s) {
    this.editors[index].last_name = s.last_name;
    this.editors[index].first_name = s.first_name || "";
    this.editors[index].suggestions = [];
  },
}));

window.Alpine = Alpine;
Alpine.start();
