import { dialog, openDialog } from "./components/dialog.js";
import { memoryForm } from "./components/records.js";
import { notice, pageHead } from "./components/ui.js";
import { h, put, s } from "./lib/dom.js";
import { href, main, refreshHealth, renderServiceStrip, state } from "./lib/state.js";
import { ADMIN_ROUTES, canAdmin, isAdmin, session, setView } from "./lib/session.js";
import { auth, hasRole, initAuth, roleSummary, signIn, signOut, signedIn } from "./lib/auth.js";
import { viewEvaluation } from "./views/evaluation.js";
import { viewGraph } from "./views/graph.js";
import { viewImport } from "./views/import.js";
import { viewIncidents } from "./views/incidents.js";
import { viewInvestigate } from "./views/investigate.js";
import { viewOverview } from "./views/overview.js";
import { viewMemories } from "./views/records.js";
import { viewSearch } from "./views/search.js";
import { viewSystem } from "./views/system.js";

// AegisOps console — dependency-free single-page app served by the FastAPI API.
// All data comes from the public /api/v1 routes; nothing is fabricated client-side.

// Sign-in first (AUTH_MODE=oidc): finish a returning sign-in or go to the
// provider. In local mode this returns at once.
const authReady = await initAuth();

/* ------------------------------------------------------------ router */

const ROUTES = {
  overview: { title: "Plant overview", view: viewOverview },
  incidents: { title: "Incidents", view: viewIncidents },
  memories: { title: "Records", view: viewMemories },
  import: { title: "Import work orders", view: viewImport },
  investigate: { title: "Investigate", view: viewInvestigate },
  search: { title: "Search", view: viewSearch },
  graph: { title: "Relationships", view: viewGraph },
  evaluation: { title: "Evaluation", view: viewEvaluation },
  system: { title: "System health", view: viewSystem },
};
const ALIASES = { ask: "investigate" };

let renderToken = 0;
let lastRoute = null;

export function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const resolved = ALIASES[path] || path;
  const name = ROUTES[resolved] ? resolved : "overview";
  return { name, params: new URLSearchParams(query || "") };
}

export async function render() {
  const token = ++renderToken;
  const { name, params } = parseHash();
  const route = ROUTES[name];
  document.title = `${route.title} | AegisOps`;
  document.querySelectorAll(".nav a").forEach((a) => (a.dataset.route === name ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  document.querySelector(".rail").classList.remove("is-open");
  document.querySelector(".menu-toggle").setAttribute("aria-expanded", "false");
  if (!state.health) await refreshHealth();
  if (token !== renderToken) return;
  try {
    if (ADMIN_ROUTES.has(name) && !isAdmin()) {
      put(main, pageHead(route.title), canAdmin()
        ? notice("info", "This page is for administrators",
          "You're viewing AegisOps as a plant user. Switch the view back to administrator to open it.",
          [h("button", { class: "btn", type: "button", onclick: () => { setView("admin"); syncView(); render(); } }, "Switch to administrator view")])
        : notice("info", "This page isn't available to your role",
          `You're signed in as ${roleSummary()}. Ask an administrator for the engineer, reviewer or administrator role if you need it.`));
    } else {
      await route.view(params);
    }
  } catch (err) {
    console.error(err);
    put(main, pageHead(route.title), notice("crit", "This page hit an unexpected error", String(err?.message || err), [h("button", { class: "btn", type: "button", onclick: render }, "Try again")]));
  }
  if (lastRoute !== name) {
    lastRoute = name;
    document.getElementById("page-title")?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
}

window.addEventListener("hashchange", render);

/* ------------------------------------------------------------ chrome */

document.querySelector(".menu-toggle").addEventListener("click", (e) => {
  const rail = document.querySelector(".rail");
  const open = !rail.classList.contains("is-open");
  rail.classList.toggle("is-open", open);
  e.currentTarget.setAttribute("aria-expanded", String(open));
});

const themeBtn = document.getElementById("theme-toggle");
function currentTheme() {
  const t = document.documentElement.dataset.theme;
  if (t) return t;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function syncTheme() {
  themeBtn.setAttribute("aria-pressed", String(currentTheme() === "dark"));
}
const densityBtn = document.getElementById("density-toggle");
function syncDensity() {
  densityBtn.setAttribute("aria-pressed", String(document.documentElement.dataset.density === "compact"));
}
densityBtn.addEventListener("click", () => {
  const compact = document.documentElement.dataset.density !== "compact";
  if (compact) document.documentElement.dataset.density = "compact"; else delete document.documentElement.dataset.density;
  try { localStorage.setItem("aegis-density", compact ? "compact" : "comfortable"); } catch {}
  syncDensity();
});
syncDensity();

const viewBtn = document.getElementById("view-toggle");
function syncView() {
  // A viewer gets the plant-user view whatever was last chosen in this browser.
  document.documentElement.dataset.view = isAdmin() ? "admin" : "plant";
  viewBtn.setAttribute("aria-pressed", String(!isAdmin()));
  // Importing changes data: hide it from people whose role can't.
  const imp = document.querySelector('.nav a[data-route="import"]')?.closest("li");
  if (imp) imp.hidden = !hasRole("engineer", "admin");
  viewBtn.hidden = !canAdmin();
  const local = auth.mode === "local";
  const who = signedIn() ? `${auth.user.display_name || auth.user.username} · ${roleSummary()}` : null;
  document.getElementById("view-meta").textContent = who
    ? `${who}${canAdmin() ? (isAdmin() ? " · administrator view" : " · plant-user view") : ""}`
    : isAdmin()
      ? (local ? "Local mode: administrator view" : "Administrator view")
      : "Plant-user view: administration hidden";
  let out = document.getElementById("sign-out");
  if (signedIn() && !out) {
    out = h("button", { id: "sign-out", class: "theme-toggle", type: "button", onclick: signOut }, "Sign out");
    document.getElementById("view-meta").after(out);
  }
}
viewBtn.addEventListener("click", () => {
  setView(isAdmin() ? "plant" : "admin");
  syncView();
  renderServiceStrip();
  render();
});
syncView();

themeBtn.addEventListener("click", () => {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("aegis-theme", next); } catch {}
  syncTheme();
});
syncTheme();

document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  if (typing || e.metaKey || e.ctrlKey || e.altKey || dialog.open) return;
  if (e.key === "/") {
    e.preventDefault();
    if (parseHash().name !== "memories") location.hash = href("memories");
    setTimeout(() => document.getElementById("flt-q")?.focus(), 80);
  } else if (e.key === "?") {
    openDialog("Keyboard shortcuts", h("dl", { class: "shortcut-list" },
      [["/", "Find in records"], ["g then o", "Plant overview"], ["g then i", "Incidents"], ["g then r", "Records"], ["g then m", "Import work orders"], ["g then v", "Investigate"], ["g then l", "Relationships"], ["g then e", "Evaluation"], ["g then s", "System health"], ["n", "New record"], ["Esc", "Close a dialog"]]
        .map(([k, d]) => [h("dt", null, h("kbd", null, k)), h("dd", null, d)])));
  } else if (e.key === "n") {
    memoryForm();
  } else if (e.key === "g") {
    const once = (ev) => {
      const map = { o: "overview", i: "incidents", r: "memories", m: "import", v: "investigate", s: "system", e: "evaluation", l: "graph" };
      if (map[ev.key]) location.hash = href(map[ev.key]);
    };
    document.addEventListener("keydown", once, { once: true });
  }
});

if (authReady !== false) {
  if (auth.error) {
    put(main, pageHead("Sign in"), notice("crit", "Sign-in didn't complete", auth.error,
      [h("button", { class: "btn btn-primary", type: "button", onclick: signIn }, "Sign in again")]));
  } else {
    setInterval(() => { if (!document.hidden) refreshHealth(); }, 20000);
    render();
  }
}
