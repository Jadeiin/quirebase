try {
  if (JSON.parse(localStorage.getItem("quirebase:sidebar-collapsed") || "false")) {
    document.documentElement.classList.add("sidebar-collapsed");
  } else {
    document.documentElement.classList.remove("sidebar-collapsed");
  }
} catch {}
