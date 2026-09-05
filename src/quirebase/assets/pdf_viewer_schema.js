export const uiSchema = {
  id: "quirebase-pdf-ui",
  version: "1",
  toolbars: {
    "quirebase-toolbar": {
      id: "quirebase-toolbar",
      permanent: true,
      position: { placement: "top", slot: "main", order: 0 },
      items: [
        { type: "command-button", id: "sidebar-button", commandId: "panel:toggle-sidebar", variant: "icon" },
        { type: "command-button", id: "page-settings-button", commandId: "page:settings", variant: "icon" },
        { type: "divider", id: "reader-divider" },
        { type: "command-button", id: "previous-page", commandId: "scroll:previous-page", variant: "icon" },
        { type: "command-button", id: "next-page", commandId: "scroll:next-page", variant: "icon" },
        { type: "custom", id: "zoom-toolbar", componentId: "zoom-toolbar" },
        { type: "command-button", id: "search", commandId: "panel:toggle-search", variant: "icon" },
        { type: "divider", id: "annotation-divider" },
        { type: "command-button", id: "highlight", commandId: "annotation:add-highlight", variant: "icon" },
        { type: "command-button", id: "underline", commandId: "annotation:add-underline", variant: "icon" },
        { type: "command-button", id: "strikeout", commandId: "annotation:add-strikeout", variant: "icon" },
        { type: "command-button", id: "note", commandId: "annotation:add-comment", variant: "icon" },
        { type: "command-button", id: "free-text", commandId: "annotation:add-text", variant: "icon" },
        { type: "command-button", id: "ink", commandId: "annotation:add-ink", variant: "icon" },
        { type: "command-button", id: "rectangle", commandId: "annotation:add-rectangle", variant: "icon" },
        { type: "command-button", id: "ellipse", commandId: "annotation:add-circle", variant: "icon" },
        { type: "command-button", id: "line", commandId: "annotation:add-line", variant: "icon" },
        { type: "command-button", id: "arrow", commandId: "annotation:add-arrow", variant: "icon" },
        { type: "command-button", id: "annotation-style", commandId: "panel:toggle-annotation-style", variant: "icon" },
        { type: "command-button", id: "comments", commandId: "panel:toggle-comment", variant: "icon" },
      ],
    },
  },
  menus: {
    "zoom-menu": {
      id: "zoom-menu",
      items: [
        ...[25, 50, 100, 125, 150, 200, 400, 800, 1600].map((level) => ({
          type: "command",
          id: `zoom-menu:${level}`,
          commandId: `zoom:${level}`,
        })),
        { type: "divider", id: "zoom-direction-divider" },
        { type: "command", id: "zoom-menu:in", commandId: "zoom:in" },
        { type: "command", id: "zoom-menu:out", commandId: "zoom:out" },
        { type: "divider", id: "zoom-fit-divider" },
        { type: "command", id: "zoom-fit-page", commandId: "zoom:fit-page" },
        { type: "command", id: "zoom-fit-width", commandId: "zoom:fit-width" },
        { type: "command", id: "zoom-marquee", commandId: "zoom:marquee" },
      ],
    },
    "page-settings-menu": {
      id: "page-settings-menu",
      items: [
        {
          type: "section",
          id: "spread-mode-section",
          labelKey: "page.spreadMode",
          label: "Spread Mode",
          items: [
            { type: "command", id: "spread-none", commandId: "spread:none" },
            { type: "command", id: "spread-odd", commandId: "spread:odd" },
            { type: "command", id: "spread-even", commandId: "spread:even" },
          ],
        },
        { type: "divider", id: "spread-scroll-divider" },
        {
          type: "section",
          id: "scroll-layout-section",
          labelKey: "page.scrollLayout",
          label: "Scroll Layout",
          items: [
            { type: "command", id: "scroll-vertical", commandId: "scroll:vertical" },
            { type: "command", id: "scroll-horizontal", commandId: "scroll:horizontal" },
          ],
        },
      ],
    },
  },
  sidebars: {
    "sidebar-panel": {
      id: "sidebar-panel",
      position: { placement: "left", slot: "main", order: 0 },
      content: {
        type: "tabs",
        tabs: [
          {
            id: "thumbnails",
            labelKey: "panel.thumbnails",
            label: "Thumbnails",
            icon: "squares",
            componentId: "thumbnails-sidebar",
          },
          {
            id: "outline",
            labelKey: "panel.outline",
            label: "Outline",
            icon: "listTree",
            componentId: "outline-sidebar",
          },
        ],
      },
      width: "250px",
      collapsible: true,
      defaultOpen: false,
    },
    "annotation-panel": {
      id: "annotation-panel",
      position: { placement: "left", slot: "main", order: 0 },
      content: { type: "component", componentId: "annotation-sidebar" },
      width: "250px",
      collapsible: true,
    },
    "search-panel": {
      id: "search-panel",
      position: { placement: "right", slot: "main", order: 0 },
      content: { type: "component", componentId: "search-sidebar" },
      width: "280px",
      collapsible: true,
    },
    "comment-panel": {
      id: "comment-panel",
      position: { placement: "right", slot: "main", order: 0 },
      content: { type: "component", componentId: "comment-sidebar" },
      width: "300px",
      collapsible: true,
    },
  },
  modals: {},
  overlays: {
    "page-controls": {
      id: "page-controls",
      position: { anchor: "bottom-center", offset: { bottom: "1.5rem" } },
      content: { type: "component", componentId: "page-controls" },
      defaultEnabled: true,
    },
  },
  selectionMenus: {
    selection: {
      id: "selection",
      items: [
        { type: "command-button", id: "selection-highlight", commandId: "annotation:add-highlight", variant: "icon" },
        { type: "command-button", id: "selection-underline", commandId: "annotation:add-underline", variant: "icon" },
        { type: "command-button", id: "selection-strikeout", commandId: "annotation:add-strikeout", variant: "icon" },
      ],
    },
    annotation: {
      id: "annotation",
      categories: ["annotation"],
      items: [
        { type: "command-button", id: "annotation-comment", commandId: "annotation:toggle-comment", variant: "icon" },
        { type: "command-button", id: "annotation-style", commandId: "annotation:toggle-annotation-style", variant: "icon" },
        { type: "command-button", id: "annotation-delete", commandId: "annotation:delete-selected", variant: "icon" },
      ],
    },
  },
};

export const disabledCategories = [
  "document-open", "document-close", "document-print", "document-export", "document-protect",
  "document-capture", "form", "insert", "redaction", "stamp", "signature",
  "annotation-callout", "annotation-ink-highlighter", "annotation-insert-text",
  "annotation-link", "annotation-polygon", "annotation-polyline", "annotation-replace-text",
  "annotation-squiggly", "annotation-widget-edit", "annotation-group",
];
