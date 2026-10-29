import { h, icon } from "../lib/dom.js";
import { href, state } from "../lib/state.js";

/** Status chip. Severity drives colour; the word is always visible. */
export function stateChip(label, severity = "normal") {
  const iconName = { normal: "ok", warn: "warn", crit: "crit", info: "info", muted: "off" }[severity] || "info";
  return h("span", { class: `state state-${severity}` }, icon(iconName), label);
}

export const SERVICE_STATE = {
  healthy: ["Normal", "normal"],
  degraded: ["Degraded", "warn"],
  unavailable: ["Unavailable", "warn"],
  unconfigured: ["Not configured", "warn"],
  unhealthy: ["Down", "crit"],
};

export function serviceChip(status) {
  const [label, sev] = SERVICE_STATE[status] || [status || "Unknown", "muted"];
  return stateChip(label, sev);
}

export const LIFECYCLE = {
  active: ["Active", "normal"],
  disputed: ["Disputed", "warn"],
  archived: ["Archived", "muted"],
  superseded: ["Superseded", "muted"],
};
export function lifecycleChip(status) {
  const [label, sev] = LIFECYCLE[status] || [status || "Unknown", "muted"];
  return stateChip(label, sev);
}

export const TYPE_LABEL = {
  observation: "Observation",
  incident: "Incident",
  diagnosis: "Diagnosis",
  maintenance_action: "Maintenance action",
  resolution: "Resolution",
  recommendation: "Recommendation",
  document_fact: "Document fact",
  agent_interaction: "Agent interaction",
  feedback: "Feedback",
};
export const typeLabel = (t) => TYPE_LABEL[t] || (t ? String(t).replace(/_/g, " ") : "Unknown");

export const SOURCE_LABEL = {
  semantic: "Vector match", graph: "Graph link", hybrid: "Vector + graph", keyword: "Keyword match",
  anchor: "Starting record", context: "Same incident or asset",
};

export function notice(kind, title, body, actions) {
  return h("div", { class: `notice notice-${kind}`, role: kind === "crit" ? "alert" : null },
    icon(kind === "crit" ? "crit" : kind === "warn" ? "warn" : "info"),
    h("div", null, h("strong", null, title), body ? h("p", null, body) : null),
    actions ? h("div", { class: "notice-actions" }, actions) : null,
  );
}

export function empty(title, body, actions) {
  const acts = actions && !(actions instanceof Element && actions.classList.contains("page-actions"))
    ? h("div", { class: "page-actions is-centered" }, actions)
    : actions;
  return h("div", { class: "empty" }, h("h3", null, title), h("p", null, body), acts || null);
}

export function skeleton() {
  return h("div", { class: "skeleton", "aria-hidden": "true" }, h("span"), h("span"), h("span"));
}

export function pageHead(title, lede, actions) {
  return h("div", { class: "page-head" },
    h("div", null, h("h1", { id: "page-title", tabindex: "-1" }, title), lede ? h("p", null, lede) : null),
    actions ? h("div", { class: "page-actions" }, actions) : null,
  );
}

export function shortId(id) {
  return id ? String(id).slice(0, 8) : "";
}

export function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function fmtAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "";
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(diff) < 60) return rtf.format(-Math.round(diff), "second");
  if (Math.abs(diff) < 3600) return rtf.format(-Math.round(diff / 60), "minute");
  if (Math.abs(diff) < 86400) return rtf.format(-Math.round(diff / 3600), "hour");
  return rtf.format(-Math.round(diff / 86400), "day");
}

export const pct = (v) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "—");
export const num = (v, digits = 0) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: digits }) : "—");

export function metaPair(label, value) {
  if (value === null || value === undefined || value === "") return null;
  return h("span", { class: "meta-pair" }, h("span", null, label), h("span", null, value));
}

export function toast(message, isError = false) {
  const el = h("div", { class: `toast${isError ? " is-error" : ""}` }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), isError ? 8000 : 4000);
}

export function busy(button, on) {
  if (!button) return;
  button.toggleAttribute("disabled", on);
  button.setAttribute("aria-busy", on ? "true" : "false");
}

export function readouts(list) {
  return h("dl", { class: "readouts" }, list.map((r) =>
    h("div", { class: `readout${r.sev ? ` is-${r.sev}` : ""}` },
      h("dt", null, r.to ? h("a", { href: r.to }, r.label) : r.label),
      h("dd", null, r.value === null || r.value === undefined ? "—" : num(r.value), h("span", { class: "readout-note" }, r.note)),
    )));
}

export function barList(rows) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return h("ul", { class: "bars" }, rows.map((r) =>
    h("li", null, h(r.to ? "a" : "span", { class: "bar-row", href: r.to || null, title: `${r.label}: ${r.value}` },
      h("span", { class: "bar-label" }, r.label),
      h("span", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", style: `width:${(r.value / max) * 100}%` })),
      h("span", { class: "bar-value" }, num(r.value)),
    ))));
}

export function scoreBar(v) {
  const clamped = Math.max(0, Math.min(1, v));
  return h("span", { class: "score", title: v.toFixed(3) },
    h("span", { class: "score-track", "aria-hidden": "true" }, h("span", { class: "score-fill", style: `width:${clamped * 100}%` })),
    h("span", null, v.toFixed(2)));
}
