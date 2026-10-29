import { closeDialog } from "../components/dialog.js";
import { SERVICE_STATE, stateChip } from "../components/ui.js";
import { API, api } from "./api.js";
import { h, put } from "./dom.js";
import { ADMIN_ROUTES, isAdmin } from "./session.js";

export const main = document.getElementById("main");

/* --------------------------------------------------------------- health */

export const state = { health: null, healthAt: null };

export async function refreshHealth() {
  const r = await api("/system/health", { timeout: 12000 });
  state.health = r.ok ? r.data : { status: "unreachable", services: {}, error: r.error };
  state.healthAt = new Date();
  renderServiceStrip();
  return state.health;
}

export function services() {
  return state.health?.services || {};
}

export function capable(...names) {
  const svc = services();
  return names.every((n) => svc[n]?.status === "healthy" || svc[n]?.status === "degraded");
}

/** One plain-language status for plant users: whether every feature works,
 *  without naming the services behind them. */
export function plainStatus() {
  if (state.health?.status === "unreachable") return stateChip("AegisOps is unreachable", "crit");
  const svc = services();
  const limited = ["postgres", "qdrant", "neo4j", "llm"].some((k) => svc[k]?.status !== "healthy") || svc.llm?.synthetic;
  return limited ? stateChip("Some features limited", "warn") : stateChip("All features available", "normal");
}

export function renderServiceStrip() {
  const strip = document.getElementById("service-strip");
  put(strip);
  if (state.health?.status === "unreachable") {
    strip.append(h("li", null, h("a", { class: "strip-link", href: "#/system" }, stateChip("API unreachable", "crit"))));
  } else if (!isAdmin()) {
    strip.append(h("li", { class: "plain-status" }, plainStatus()));
  } else {
    const svc = services();
    const names = [["postgres", "PostgreSQL"], ["qdrant", "Qdrant"], ["neo4j", "Neo4j"], ["llm", "Answer model"]];
    for (const [key, label] of names) {
      const st = svc[key]?.status;
      const [word, sev] = SERVICE_STATE[st] || ["Unknown", "muted"];
      let text = `${label}: ${word.toLowerCase()}`;
      if (key === "llm" && svc.llm?.synthetic) text = `${label}: test provider`;
      strip.append(h("li", null, h("a", { class: "strip-link", href: "#/system", "aria-label": `${text}. Open System health.` },
        stateChip(text, key === "llm" && svc.llm?.synthetic ? "info" : sev))));
    }
  }
  const t = document.getElementById("health-updated");
  t.textContent = state.healthAt ? `Checked ${state.healthAt.toLocaleTimeString(undefined, { timeStyle: "short" })}` : "";
}

/* ------------------------------------------------------------ navigation */

// Every page links to the next step of the same operational loop:
// detect (overview) -> triage (incidents) -> investigate -> record finding
// -> resolve (records lifecycle) -> measure (evaluation), with System health
// explaining which capabilities are available at any moment.

export function href(route, params = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") p.set(k, v);
  const q = p.toString();
  return `#/${route}${q ? `?${q}` : ""}`;
}

export function go(route, params) {
  closeDialog();
  location.hash = href(route, params);
}

export function contextOf(m) {
  return { asset_id: m.asset_id, facility_id: m.facility_id, component_id: m.component_id, incident_id: m.incident_id };
}

/** A link that also closes any open dialog. Administration pages are not
 *  linked from the plant-user view. */
export function navLink(label, route, params, cls = "") {
  if (ADMIN_ROUTES.has(route) && !isAdmin()) return null;
  return h("a", { href: href(route, params), class: cls || null, onclick: closeDialog }, label);
}

export const evalState = loadEvalState();

export function loadEvalState() {
  try {
    const raw = localStorage.getItem("aegis-eval-cases");
    const cases = raw ? JSON.parse(raw) : [];
    return { cases: Array.isArray(cases) ? cases : [], pending: null, results: null };
  } catch {
    return { cases: [], pending: null, results: null };
  }
}

export function saveEvalCases() {
  try { localStorage.setItem("aegis-eval-cases", JSON.stringify(evalState.cases)); } catch {}
}

/* ------------------------------------------------------- shared derivations */

export const whenOf = (m) => m.observed_at || m.created_at;

// Mirrors CLOSED_STATUSES in app/ingestion/work_orders.py.
export const CLOSED_WO = new Set(["comp", "close", "closed", "complete", "completed", "teco", "clsd", "done", "finished"]);

/** Incidents derived from records sharing an incident_id. An incident is
 *  resolved by an active resolution record, or when every work order raised
 *  against it is closed in the CMMS. */
export function deriveIncidents(items) {
  const groups = new Map();
  for (const m of items) {
    if (!m.incident_id) continue;
    if (!groups.has(m.incident_id)) groups.set(m.incident_id, []);
    groups.get(m.incident_id).push(m);
  }
  return [...groups.entries()].map(([id, recs]) => {
    recs.sort((a, b) => String(whenOf(a)).localeCompare(String(whenOf(b))));
    const head = recs.find((r) => r.memory_type === "incident") || recs[0];
    const closedWo = (r) => r.source_type === "work_order" && CLOSED_WO.has(String(r.metadata?.work_order?.status || "").toLowerCase());
    const wos = recs.filter((r) => r.source_type === "work_order" && r.status === "active");
    const isResolved = recs.some((r) => r.memory_type === "resolution" && r.status === "active") || (wos.length > 0 && wos.every(closedWo));
    return { id, recs, head, isResolved, last: whenOf(recs[recs.length - 1]) };
  }).sort((a, b) => Number(a.isResolved) - Number(b.isResolved) || (b.head.importance - a.head.importance) || String(b.last).localeCompare(String(a.last)));
}
