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

window.Alpine = Alpine;
Alpine.start();
