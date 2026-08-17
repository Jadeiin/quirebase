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
  filtered: [],
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
    const q = this.tagFilter.trim().toLowerCase();
    this.filtered = q
      ? this.tags.filter((t) => t.name && t.name.toLowerCase().includes(q))
      : this.tags;
    const start = (this.page - 1) * this.pageSize;
    this.visibleIds = new Set(this.filtered.slice(start, start + this.pageSize).map((t) => t.id));
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
    const q = this.query;
    if (!q) return true;
    return name.toLowerCase().includes(q);
  },
  groupMatches(names) {
    const q = this.query;
    if (!q) return true;
    return names.some((n) => n.toLowerCase().includes(q));
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
