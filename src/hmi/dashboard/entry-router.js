// Load only the route's owner. A full navigation separates operational listeners.
function compatibilityRoute() {
  const modes = new URLSearchParams(window.location.search).getAll("view");
  return window.location.hash === "#compatibility" || (modes.length === 1 && modes[0] === "compatibility");
}
const compatibility = compatibilityRoute();
if (compatibility && window.location.hash === "#compatibility") {
  const canonical = new URL(window.location.href);
  canonical.searchParams.set("view", "compatibility");
  window.history.replaceState(null, "", canonical);
}
const entry = document.getElementById("entry-shell");
const legacy = document.getElementById("compatibility-shell");
const drawer = document.getElementById("auth-drawer");
// Neither route may let an unbound native credential form submit into a URL.
drawer.inert = true;
window.addEventListener("hashchange", () => {
  if (compatibilityRoute() !== compatibility) window.location.reload();
});

if (compatibility) {
  entry.hidden = true;
  legacy.hidden = false;
  await import("./app.js");
  drawer.inert = false;
  legacy.dataset.ready = "true";
} else {
  document.body.dataset.dashboardEntry = "true";
  // client.js imports dom.js, which captures IDs once. Move the one existing
  // login form before that import; never duplicate the credential controls.
  document.getElementById("entry-auth-slot").append(drawer);
  await import("./dashboard-entry.js");
  drawer.inert = false;
  entry.dataset.ready = "true";
}
