// Who the console is showing itself to. User accounts are on hold, so the view
// is a presentation switch: local mode starts as administrator, and an
// administrator can preview the plant-user view. The API still enforces roles
// on its own (app/core/security.py); hiding here is never the security boundary.

/** Routes that only administrators see in the navigation. */
export const ADMIN_ROUTES = new Set(["evaluation", "system"]);

function readView() {
  try { return localStorage.getItem("aegis-view") === "plant" ? "plant" : "admin"; } catch { return "admin"; }
}

export const session = { view: readView() };

export const isAdmin = () => session.view === "admin";

/** The given children for administrators; nothing for plant users. */
export const adminOnly = (...children) => (isAdmin() ? children : null);

export function setView(view) {
  session.view = view === "plant" ? "plant" : "admin";
  document.documentElement.dataset.view = session.view;
  try { localStorage.setItem("aegis-view", session.view); } catch {}
}
