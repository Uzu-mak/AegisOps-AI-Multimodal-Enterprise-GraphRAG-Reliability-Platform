// Who the console is showing itself to. In local mode the view is a
// presentation switch that starts as administrator. When people sign in
// (AUTH_MODE=oidc), viewers only get the plant-user view; engineers, reviewers
// and administrators can use both. The API enforces roles on its own
// (app/core/security.py); hiding here is never the security boundary.
import { auth, hasRole } from "./auth.js";

/** Routes that only administrators see in the navigation. */
export const ADMIN_ROUTES = new Set(["evaluation", "system"]);

function readView() {
  try { return localStorage.getItem("aegis-view") === "plant" ? "plant" : "admin"; } catch { return "admin"; }
}

export const session = { view: readView() };

/** Can this person use the administration pages at all? */
export const canAdmin = () => auth.mode !== "oidc" || hasRole("admin", "engineer", "reviewer");

export const isAdmin = () => session.view === "admin" && canAdmin();

/** The given children for administrators; nothing for plant users. */
export const adminOnly = (...children) => (isAdmin() ? children : null);

export function setView(view) {
  session.view = view === "plant" ? "plant" : "admin";
  document.documentElement.dataset.view = session.view;
  try { localStorage.setItem("aegis-view", session.view); } catch {}
}
