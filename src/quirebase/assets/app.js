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

Alpine.data("pdfToolbar", () => ({
  annotationOpen: false,
  toggleAnnotations() {
    this.annotationOpen = !this.annotationOpen;
  },
}));

window.Alpine = Alpine;
Alpine.start();
