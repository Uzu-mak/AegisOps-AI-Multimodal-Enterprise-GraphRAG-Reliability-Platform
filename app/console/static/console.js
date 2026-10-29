import { dialog, openDialog } from "./components/dialog.js";
import { memoryForm } from "./components/records.js";
import { notice, pageHead } from "./components/ui.js";
import { h, put, s } from "./lib/dom.js";
import { href, main, refreshHealth, state } from "./lib/state.js";
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
    await route.view(params);
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

setInterval(() => { if (!document.hidden) refreshHealth(); }, 20000);
render();
