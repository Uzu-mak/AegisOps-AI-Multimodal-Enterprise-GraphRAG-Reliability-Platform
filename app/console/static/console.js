// AegisOps console — dependency-free single-page app served by the FastAPI API.
// All data comes from the public /api/v1 routes; nothing is fabricated client-side.

const API = "/api/v1";
const main = document.getElementById("main");

/* ------------------------------------------------------------------ DOM */

function h(tag, attrs, ...children) {
  const el = tag === "svg" || attrs?.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false || k === "svg") continue;
      if (k === "class") el.setAttribute("class", v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v; // only ever used with static SVG markup
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** replaceChildren that ignores null/false (replaceChildren would print "null"). */
function put(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

/** append that ignores null/false. */
function add(el, ...children) {
  el.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

function s(tag, attrs, ...children) {
  return h(tag, { ...(attrs || {}), svg: true }, ...children);
}

const ICON = {
  ok: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 8.5 3 3 7-7"/></svg>',
  warn: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2 1.5 14h13zM8 7v3M8 12h.01"/></svg>',
  crit: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="6.5"/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5"/></svg>',
  info: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.5V11M8 5h.01"/></svg>',
  off: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="6.5"/><path d="M5 8h6"/></svg>',
};

function icon(name) {
  const wrap = document.createElement("span");
  wrap.innerHTML = ICON[name] || ICON.info;
  return wrap.firstChild;
}

/** Status chip. Severity drives colour; the word is always visible. */
function stateChip(label, severity = "normal") {
  const iconName = { normal: "ok", warn: "warn", crit: "crit", info: "info", muted: "off" }[severity] || "info";
  return h("span", { class: `state state-${severity}` }, icon(iconName), label);
}

const SERVICE_STATE = {
  healthy: ["Normal", "normal"],
  degraded: ["Degraded", "warn"],
  unavailable: ["Unavailable", "warn"],
  unconfigured: ["Not configured", "warn"],
  unhealthy: ["Down", "crit"],
};

function serviceChip(status) {
  const [label, sev] = SERVICE_STATE[status] || [status || "Unknown", "muted"];
  return stateChip(label, sev);
}

const LIFECYCLE = {
  active: ["Active", "normal"],
  disputed: ["Disputed", "warn"],
  archived: ["Archived", "muted"],
  superseded: ["Superseded", "muted"],
};
function lifecycleChip(status) {
  const [label, sev] = LIFECYCLE[status] || [status || "Unknown", "muted"];
  return stateChip(label, sev);
}

const TYPE_LABEL = {
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
const typeLabel = (t) => TYPE_LABEL[t] || (t ? String(t).replace(/_/g, " ") : "Unknown");

const SOURCE_LABEL = {
  semantic: "Vector match", graph: "Graph link", hybrid: "Vector + graph", keyword: "Keyword match",
  anchor: "Starting record", context: "Same incident or asset",
};

function notice(kind, title, body, actions) {
  return h("div", { class: `notice notice-${kind}`, role: kind === "crit" ? "alert" : null },
    icon(kind === "crit" ? "crit" : kind === "warn" ? "warn" : "info"),
    h("div", null, h("strong", null, title), body ? h("p", null, body) : null),
    actions ? h("div", { class: "notice-actions" }, actions) : null,
  );
}

function empty(title, body, actions) {
  const acts = actions && !(actions instanceof Element && actions.classList.contains("page-actions"))
    ? h("div", { class: "page-actions is-centered" }, actions)
    : actions;
  return h("div", { class: "empty" }, h("h3", null, title), h("p", null, body), acts || null);
}

function skeleton() {
  return h("div", { class: "skeleton", "aria-hidden": "true" }, h("span"), h("span"), h("span"));
}

function pageHead(title, lede, actions) {
  return h("div", { class: "page-head" },
    h("div", null, h("h1", { id: "page-title", tabindex: "-1" }, title), lede ? h("p", null, lede) : null),
    actions ? h("div", { class: "page-actions" }, actions) : null,
  );
}

function shortId(id) {
  return id ? String(id).slice(0, 8) : "";
}

function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (!Number.isFinite(diff)) return "";
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(diff) < 60) return rtf.format(-Math.round(diff), "second");
  if (Math.abs(diff) < 3600) return rtf.format(-Math.round(diff / 60), "minute");
  if (Math.abs(diff) < 86400) return rtf.format(-Math.round(diff / 3600), "hour");
  return rtf.format(-Math.round(diff / 86400), "day");
}

const pct = (v) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "—");
const num = (v, digits = 0) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: digits }) : "—");

function metaPair(label, value) {
  if (value === null || value === undefined || value === "") return null;
  return h("span", { class: "meta-pair" }, h("span", null, label), h("span", null, value));
}

function toast(message, isError = false) {
  const el = h("div", { class: `toast${isError ? " is-error" : ""}` }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), isError ? 8000 : 4000);
}

function busy(button, on) {
  if (!button) return;
  button.toggleAttribute("disabled", on);
  button.setAttribute("aria-busy", on ? "true" : "false");
}

/* ------------------------------------------------------------------ API */

async function api(path, { method = "GET", body, timeout = 20000, params } = {}) {
  const url = new URL(API + path, location.origin);
  if (params) for (const [k, v] of Object.entries(params)) if (v !== "" && v !== null && v !== undefined) url.searchParams.set(k, v);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!res.ok) return { ok: false, status: res.status, data, error: describeError(res.status, data) };
    return { ok: true, status: res.status, data };
  } catch (err) {
    const error = err.name === "AbortError"
      ? `The API took longer than ${Math.round(timeout / 1000)} s to answer ${path}. Check System health for a stalled dependency.`
      : `Can't reach the AegisOps API. Check that the api service is running, then reload.`;
    return { ok: false, status: 0, data: null, error };
  } finally {
    clearTimeout(timer);
  }
}

function describeError(status, data) {
  const detail = data && typeof data === "object" ? data.detail : data;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).filter((p) => p !== "body").join(".") || "request"}: ${d.msg}`).join("; ");
  }
  if (typeof detail === "string" && detail) return detail;
  if (status === 404) return "That record doesn't exist.";
  if (status >= 500) return `The API returned an error (${status}). Check the api service logs.`;
  return `Request failed (${status}).`;
}

async function fetchAllMemories(params = {}) {
  const out = [];
  const pageSize = 200;
  for (let offset = 0; offset < 2000; offset += pageSize) {
    const r = await api("/memories", { params: { ...params, limit: pageSize, offset } });
    if (!r.ok) return { ok: false, error: r.error, items: out };
    const items = r.data?.items || [];
    out.push(...items);
    if (items.length < pageSize) break;
  }
  return { ok: true, items: out };
}

/* --------------------------------------------------------------- health */

const state = { health: null, healthAt: null };

async function refreshHealth() {
  const r = await api("/system/health", { timeout: 12000 });
  state.health = r.ok ? r.data : { status: "unreachable", services: {}, error: r.error };
  state.healthAt = new Date();
  renderServiceStrip();
  return state.health;
}

function services() {
  return state.health?.services || {};
}

function capable(...names) {
  const svc = services();
  return names.every((n) => svc[n]?.status === "healthy" || svc[n]?.status === "degraded");
}

function renderServiceStrip() {
  const strip = document.getElementById("service-strip");
  put(strip);
  if (state.health?.status === "unreachable") {
    strip.append(h("li", null, h("a", { class: "strip-link", href: "#/system" }, stateChip("API unreachable", "crit"))));
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

/* --------------------------------------------------------------- dialog */

const dialog = document.getElementById("dialog");
let dialogReturnFocus = null;

function openDialog(titleText, body, foot) {
  dialogReturnFocus = document.activeElement;
  const inner = dialog.querySelector(".dialog-inner");
  put(inner, 
    h("div", { class: "dialog-head" },
      h("h2", { id: "dialog-title" }, titleText),
      h("button", { class: "btn btn-quiet dialog-close", type: "button", onclick: closeDialog },
        h("span", { class: "visually-hidden" }, "Close"),
        h("span", { "aria-hidden": "true" }, "✕")),
    ),
    body,
    foot ? h("div", { class: "dialog-foot" }, foot) : null,
  );
  if (!dialog.open) dialog.showModal();
  const first = inner.querySelector("input, select, textarea, [data-autofocus]");
  (first || inner.querySelector(".dialog-close")).focus();
}

function closeDialog() {
  if (dialog.open) dialog.close();
}
dialog.addEventListener("close", () => {
  if (dialogReturnFocus && document.contains(dialogReturnFocus)) dialogReturnFocus.focus();
});
dialog.addEventListener("click", (e) => { if (e.target === dialog) closeDialog(); });

/* ------------------------------------------------------------ navigation */

// Every page links to the next step of the same operational loop:
// detect (overview) -> triage (incidents) -> investigate -> record finding
// -> resolve (records lifecycle) -> measure (evaluation), with System health
// explaining which capabilities are available at any moment.

function href(route, params = {}) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") p.set(k, v);
  const q = p.toString();
  return `#/${route}${q ? `?${q}` : ""}`;
}

function go(route, params) {
  closeDialog();
  location.hash = href(route, params);
}

function contextOf(m) {
  return { asset_id: m.asset_id, facility_id: m.facility_id, component_id: m.component_id, incident_id: m.incident_id };
}

/** A link that also closes any open dialog. */
function navLink(label, route, params, cls = "") {
  return h("a", { href: href(route, params), class: cls || null, onclick: closeDialog }, label);
}

const evalState = loadEvalState();

function loadEvalState() {
  try {
    const raw = localStorage.getItem("aegis-eval-cases");
    const cases = raw ? JSON.parse(raw) : [];
    return { cases: Array.isArray(cases) ? cases : [], pending: null, results: null };
  } catch {
    return { cases: [], pending: null, results: null };
  }
}

function saveEvalCases() {
  try { localStorage.setItem("aegis-eval-cases", JSON.stringify(evalState.cases)); } catch {}
}

/* ------------------------------------------------------- record dialogs */

async function showMemory(id, { onChange } = {}) {
  openDialog("Loading record", skeleton());
  const r = await api(`/memories/${id}`);
  if (!r.ok) {
    openDialog("Record unavailable", notice("crit", "Couldn't load this record", r.error));
    return;
  }
  const m = r.data;
  const refresh = async (msg) => { toast(msg); closeDialog(); await refreshHealth(); (onChange || render)(); };

  const confirmArea = h("div", { class: "confirm" });
  const isActive = m.status === "active";

  const lifecycle = (action, verb, done) => {
    put(confirmArea,
      notice("warn", `${verb} this record?`,
        action === "archive"
          ? "Archived records stay in PostgreSQL for audit but are excluded from search, investigations and evaluation."
          : "Disputed records stay visible here but are excluded from search, investigations and evaluation until resolved.",
        [
          h("button", { class: "btn btn-danger", type: "button", "data-autofocus": true, onclick: async (e) => {
            busy(e.currentTarget, true);
            const res = await api(`/memories/${m.id}/${action}`, { method: "POST", body: {} });
            busy(e.currentTarget, false);
            if (!res.ok) return toast(res.error, true);
            await refresh(done);
          } }, verb),
          h("button", { class: "btn", type: "button", onclick: () => put(confirmArea) }, "Keep as is"),
        ]));
    confirmArea.querySelector("[data-autofocus]").focus();
  };

  const evidenceOf = m.metadata?.evidence_memory_ids || [];
  const wo = m.source_type === "work_order" ? (m.metadata?.work_order || {}) : null;
  const codes = wo ? [["Problem", wo.problem], ["Cause", wo.cause], ["Remedy", wo.remedy]].filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(", ") : null;
  const body = h("div", null,
    h("div", { class: "evidence-head" }, lifecycleChip(m.status), h("span", { class: "tag" }, typeLabel(m.memory_type)),
      m.source_type === "investigation" ? h("span", { class: "tag" }, "Recorded from an investigation") : null,
      wo ? h("span", { class: "tag" }, "Imported work order") : null,
      m.is_synthetic ? h("span", { class: "tag" }, "Sample data") : null),
    h("p", { class: "record-body" }, m.content),
    h("dl", { class: "facts" },
      ...[
        ["Asset", m.asset_id ? navLink(m.asset_id, "memories", { asset: m.asset_id, status: "any" }) : null],
        ["Facility", m.facility_id],
        ["Line or component", m.component_id],
        ["Incident", m.incident_id ? navLink(m.incident_id, "incidents", { id: m.incident_id }) : null],
        ["Source", wo ? `Work order ${m.source_id}` : m.source_type],
        ["Work type", wo ? [wo.work_type, wo.work_type_class && wo.work_type_class !== "unknown" ? `(${wo.work_type_class})` : null].filter(Boolean).join(" ") : null],
        ["CMMS status", wo?.status],
        ["Failure codes", codes],
        ["Reported", wo?.reported_at ? fmtWhen(wo.reported_at) : null],
        ["Finished", wo ? (wo.finished_at ? fmtWhen(wo.finished_at) : "Not finished") : null],
        ["Observed", wo ? null : fmtWhen(m.observed_at)],
        ["Recorded", fmtWhen(m.created_at)],
        ["Confidence", pct(m.confidence)],
        ["Importance", pct(m.importance)],
        ["Based on", evidenceOf.length ? basedOnList(evidenceOf) : null],
        ["Supersedes", m.supersedes_memory_id ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(m.supersedes_memory_id) }, `record ${shortId(m.supersedes_memory_id)}`) : null],
        ["Record ID", h("code", null, m.id)],
      ].filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== "—").map(([k, v]) => [h("dt", null, k), h("dd", null, v)]),
    ),
    confirmArea,
  );

  const foot = [
    navLink("Investigate from here", "investigate", { anchor: m.id, q: `What do we know about: ${m.title}?` }, "btn"),
    navLink("Show related", "graph", { anchor: m.id }, "btn"),
    h("span", { class: "spacer" }),
    isActive ? h("button", { class: "btn", type: "button", onclick: () => memoryForm({ supersede: m, onSaved: onChange || render }) }, "Supersede") : null,
    isActive ? h("button", { class: "btn btn-danger", type: "button", onclick: () => lifecycle("dispute", "Dispute", "Record marked disputed") }, "Dispute") : null,
    m.status !== "archived" && m.status !== "superseded" ? h("button", { class: "btn btn-danger", type: "button", onclick: () => lifecycle("archive", "Archive", "Record archived") }, "Archive") : null,
  ];
  openDialog(m.title, body, foot);
}

/** Evidence list for a finding; titles are filled in as they load. */
function basedOnList(ids) {
  const list = h("ul", { class: "based-on" }, ids.map((eid) => {
    const btn = h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(eid) }, `record ${shortId(eid)}`);
    api(`/memories/${eid}`).then((r) => { if (r.ok) btn.textContent = r.data.title; });
    return h("li", null, btn);
  }));
  return list;
}

function formField(name, label, input, hint, wide = false) {
  return h("div", { class: `field${wide ? " span-2" : ""}` },
    h("label", { for: `f-${name}` }, label), input,
    hint ? h("small", { id: `f-${name}-hint` }, hint) : null,
    h("span", { class: "field-error", id: `f-${name}-err`, role: "alert" }));
}

function markInvalid(form, name, message) {
  const input = form.querySelector(`#f-${name}`);
  input.setAttribute("aria-invalid", "true");
  input.setAttribute("aria-describedby", `f-${name}-err`);
  form.querySelector(`#f-${name}-err`).textContent = message;
  return input;
}

function clearInvalid(form) {
  form.querySelectorAll(".field-error").forEach((e) => (e.textContent = ""));
  form.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
}

/** New record, a record added to an existing incident (defaults), or a supersession. */
function memoryForm({ supersede = null, defaults = {}, title = null, onSaved } = {}) {
  const base = supersede || defaults;
  const text = (name, attrs = {}) => h("input", { type: "text", id: `f-${name}`, name, value: base[name] ?? "", ...attrs });
  const typeSelect = h("select", { id: "f-memory_type", name: "memory_type" },
    Object.entries(TYPE_LABEL).map(([v, l]) => h("option", { value: v, selected: (base.memory_type || "observation") === v }, l)));

  const form = h("form", { class: "form-grid", novalidate: true },
    formField("memory_type", "Record type", typeSelect),
    formField("source_type", "Source", text("source_type", { list: "source-types", required: true, value: base.source_type || "technician" }), "Who or what reported it"),
    formField("title", "Title", text("title", { required: true, maxlength: 200, value: supersede ? base.title : "" }), null, true),
    formField("content", "What happened", h("textarea", { id: "f-content", name: "content", required: true, rows: 4 }, supersede ? base.content : ""), null, true),
    formField("asset_id", "Asset", text("asset_id", { placeholder: "e.g. drill-cell-dc3" })),
    formField("facility_id", "Facility", text("facility_id")),
    formField("component_id", "Line or component", text("component_id")),
    formField("incident_id", "Incident", text("incident_id", { placeholder: "e.g. inc-2026-0108" })),
    formField("observed_at", "Observed at", h("input", { type: "datetime-local", id: "f-observed_at", name: "observed_at" }), "Your local time"),
    formField("confidence", "Confidence (0–1)", h("input", { type: "number", id: "f-confidence", name: "confidence", min: 0, max: 1, step: 0.01, value: base.confidence ?? 0.7 })),
    formField("importance", "Importance (0–1)", h("input", { type: "number", id: "f-importance", name: "importance", min: 0, max: 1, step: 0.01, value: base.importance ?? 0.5 })),
    h("datalist", { id: "source-types" }, ["technician", "operator_report", "inspection", "sensor", "system", "manual"].map((v) => h("option", { value: v }))),
  );

  const submit = h("button", { class: "btn btn-primary", type: "button" }, supersede ? "Save replacement" : "Save record");
  submit.addEventListener("click", async () => {
    clearInvalid(form);
    const payload = {};
    for (const [k, v] of new FormData(form).entries()) {
      const val = String(v).trim();
      if (val !== "") payload[k] = ["confidence", "importance"].includes(k) ? Number(val) : val;
    }
    if (payload.observed_at) payload.observed_at = new Date(payload.observed_at).toISOString();
    let invalid = null;
    for (const req of ["title", "content", "source_type"]) if (!payload[req]) invalid = invalid || markInvalid(form, req, "Required");
    for (const n of ["confidence", "importance"]) {
      if (payload[n] !== undefined && !(payload[n] >= 0 && payload[n] <= 1)) invalid = invalid || markInvalid(form, n, "Enter a number from 0 to 1");
    }
    if (invalid) return invalid.focus();

    busy(submit, true);
    const res = supersede
      ? await api(`/memories/${supersede.id}/supersede`, { method: "POST", body: { replacement: payload } })
      : await api("/memories", { method: "POST", body: payload });
    busy(submit, false);
    if (!res.ok) return toast(res.error, true);
    closeDialog();
    toast(supersede ? "Replacement saved; the original is now superseded" : "Record saved");
    (onSaved || render)();
  });

  openDialog(title || (supersede ? `Supersede: ${supersede.title}` : "New record"), h("div", null,
    supersede ? notice("info", "The original stays in history", "It will be marked superseded and linked to this replacement.") : null,
    form),
    [h("button", { class: "btn", type: "button", onclick: closeDialog }, "Cancel"), submit]);
}

/* ---------------------------------------------------------- sample data */

// Illustrative aerospace manufacturing records. Every record is flagged
// is_synthetic and shown as "Sample data"; none describe a real company.
function sampleRecords() {
  const now = Date.now();
  const at = (hoursAgo) => new Date(now - hoursAgo * 3600e3).toISOString();
  const dc3 = { asset_id: "drill-cell-dc3", facility_id: "final-assembly-bldg-2", component_id: "fuselage-join-cell", incident_id: "inc-2026-0108" };
  const ac2 = { asset_id: "autoclave-ac2", facility_id: "composites-bldg-5", component_id: "cure-cell-1", incident_id: "inc-2026-0115" };
  const us1 = { asset_id: "ndt-scanner-us1", facility_id: "composites-bldg-5", component_id: "ndt-cell-2" };
  const rec = (memory_type, title, content, source_type, ctx, hoursAgo, confidence, importance) =>
    ({ memory_type, title, content, source_type, ...ctx, observed_at: at(hoursAgo), confidence, importance, is_synthetic: true, metadata: { sample: "aegisops-console" } });
  return [
    rec("incident", "Oversize fastener holes from drill cell DC-3", "Hole-quality inspection found 6 of 120 fastener holes on frame 42 above the diameter tolerance on automated drilling cell DC-3.", "inspection", dc3, 30, 0.85, 0.92),
    rec("observation", "Spindle vibration rising on drill cell DC-3", "Spindle vibration rose from 1.1 to 2.4 mm/s RMS over the last 400 holes; spindle runout measured 0.03 mm.", "sensor", dc3, 29, 0.8, 0.78),
    rec("diagnosis", "Worn spindle bearing on drill cell DC-3", "Bearing wear causing spindle runout explains the oversize holes. Cutter wear ruled out: a new cutter gave the same result.", "technician", dc3, 27, 0.74, 0.85),
    rec("maintenance_action", "Replaced spindle bearing on drill cell DC-3", "Replaced the front spindle bearing and re-qualified the cell on a 20-hole test coupon.", "technician", dc3, 20, 0.9, 0.76),
    rec("resolution", "Drill cell DC-3 hole quality back in tolerance", "The next 400 holes were all within tolerance and spindle vibration returned to 1.0 mm/s RMS.", "inspection", dc3, 8, 0.92, 0.82),
    rec("recommendation", "Alert on spindle vibration for drilling cells", "Raise an alert when spindle vibration passes 1.8 mm/s RMS so bearing wear is caught before nonconforming holes are drilled.", "manual", dc3, 7, 0.78, 0.8),
    rec("incident", "Thermocouple lag during cure on autoclave AC-2", "Thermocouple TC-7 trailed the cure profile by 9 °C during the ramp on a composite skin panel cure. The cycle is on hold for engineering review.", "system", ac2, 6, 0.8, 0.95),
    rec("observation", "TC-7 reading jumps at the connector on autoclave AC-2", "The TC-7 reading jumps 4 to 6 °C when its lead is moved at the connector panel; neighbouring thermocouples agree with each other.", "technician", ac2, 5, 0.82, 0.8),
    rec("diagnosis", "Suspected damaged TC-7 lead on autoclave AC-2", "Insulation damage on the TC-7 lead at the connector likely causes the lag, not a true part temperature difference.", "technician", ac2, 4, 0.65, 0.84),
    rec("document_fact", "Cure thermocouple calibration and replacement rule", "Process specification: cure thermocouples are calibrated every 90 days and replaced if lead insulation is damaged.", "manual", { asset_id: "autoclave-ac2", facility_id: "composites-bldg-5" }, 400, 0.95, 0.6),
    rec("observation", "Coupling-loss alarms on ultrasonic scanner US-1", "Three coupling-loss alarms per shift on water-jet ultrasonic scanner US-1, all on the same gantry axis.", "sensor", us1, 15, 0.7, 0.62),
    rec("recommendation", "Inspect water-jet nozzle on ultrasonic scanner US-1", "Check the nozzle for scale and confirm water flow before the next panel inspection.", "manual", us1, 13, 0.66, 0.58),
  ];
}

async function loadSampleData(button) {
  busy(button, true);
  const existing = await fetchAllMemories();
  const titles = new Set((existing.items || []).map((m) => m.title));
  const todo = sampleRecords().filter((r) => !titles.has(r.title));
  let created = 0;
  for (const rec of todo) {
    const r = await api("/memories", { method: "POST", body: rec });
    if (!r.ok) { busy(button, false); return toast(`Stopped after ${created} records: ${r.error}`, true); }
    created += 1;
  }
  busy(button, false);
  toast(created ? `Added ${created} sample records, marked as sample data` : "Sample records are already loaded");
  await refreshHealth();
  render();
}

/* ------------------------------------------------------- shared derivations */

const whenOf = (m) => m.observed_at || m.created_at;

// Mirrors CLOSED_STATUSES in app/ingestion/work_orders.py.
const CLOSED_WO = new Set(["comp", "close", "closed", "complete", "completed", "teco", "clsd", "done", "finished"]);

/** Incidents derived from records sharing an incident_id. An incident is
 *  resolved by an active resolution record, or when every work order raised
 *  against it is closed in the CMMS. */
function deriveIncidents(items) {
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

function sampleDataEmpty(text) {
  return empty("No operational records yet", text || "Import the plant's work-order history, record an incident, or load the labelled sample plant to explore the console.",
    h("div", { class: "page-actions is-centered" },
      h("button", { class: "btn btn-primary", type: "button", onclick: (e) => loadSampleData(e.currentTarget) }, "Load sample plant data"),
      navLink("Import work orders", "import", {}, "btn"),
      h("button", { class: "btn", type: "button", onclick: () => memoryForm() }, "Record an event")));
}

/* ============================================================== VIEWS */

/* ---------------------------------------------------------- overview */

async function viewOverview() {
  const head = (actions) => pageHead("Plant overview", "What needs attention now, and whether the memory pipeline behind it is healthy.", actions);
  put(main, head(), h("div", { class: "panel schematic" }, skeleton()));

  const [all, outbox] = await Promise.all([fetchAllMemories(), api("/system/outbox-stats")]);
  if (!all.ok) return put(main, head(), notice("crit", "Records can't be loaded", all.error));
  const items = all.items;
  const active = items.filter((m) => m.status === "active");
  const pending = outbox.ok ? outbox.data?.summary?.pending ?? 0 : null;
  const failed = outbox.ok ? outbox.data?.summary?.failed ?? 0 : null;
  const incidents = deriveIncidents(items);
  const open = incidents.filter((i) => !i.isResolved);

  put(main,
    head(items.length ? [h("a", { class: "btn btn-primary", href: href("investigate") }, "Investigate")] : null),
    schematic({ svc: services(), total: items.length, active: active.length, pending, failed }),
    readouts([
      { label: "Open incidents", value: open.length, note: "Incidents without an active resolution", sev: open.length ? "warn" : null, to: href("incidents") },
      { label: "Active records", value: active.length, note: `${items.length - active.length} archived, disputed or superseded`, to: href("memories") },
      { label: "Waiting to project", value: pending, note: "Outbox events not yet in Qdrant or Neo4j", sev: pending > 0 ? "warn" : null, to: href("system") },
      { label: "Failed projections", value: failed, note: "Gave up after retries; needs a look", sev: failed > 0 ? "crit" : null, to: href("system") },
    ]),
  );

  if (!items.length) return add(main, sampleDataEmpty());

  const byType = {};
  for (const m of active) byType[m.memory_type] = (byType[m.memory_type] || 0) + 1;
  const recent = [...items].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, 6);

  add(main,
    h("div", { class: "grid grid-main" },
      h("section", { class: "panel", "aria-labelledby": "q-title" },
        h("div", { class: "panel-head" }, h("h2", { id: "q-title" }, "Open incidents"), h("a", { href: href("incidents") }, "All incidents")),
        open.length
          ? h("ul", { class: "queue" }, open.slice(0, 6).map((inc) => h("li", null,
              h("a", { class: "queue-item", href: href("incidents", { id: inc.id }) },
                h("span", { class: "queue-title" }, inc.head.title),
                stateChip("Open", "warn"),
                h("span", { class: "queue-meta" },
                  metaPair("Asset", inc.head.asset_id), metaPair("Incident", inc.id),
                  metaPair("Records", String(inc.recs.length)), metaPair("Last activity", fmtAgo(inc.last)))))))
          : empty("No open incidents", "Every incident has an active resolution."),
      ),
      h("section", { class: "panel", "aria-labelledby": "mix-title" },
        h("div", { class: "panel-head" }, h("h2", { id: "mix-title" }, "Active records by type"), h("p", null, "Select a type to list it")),
        barList(Object.entries(byType).sort((a, b) => b[1] - a[1]).map(([t, n]) => ({ label: typeLabel(t), value: n, to: href("memories", { type: t, status: "active" }) }))),
      ),
    ),
    h("section", { class: "panel", "aria-labelledby": "recent-title" },
      h("div", { class: "panel-head" }, h("h2", { id: "recent-title" }, "Latest activity"), h("a", { href: href("memories") }, "All records")),
      h("ul", { class: "queue" }, recent.map((m) => h("li", null,
        h("button", { class: "queue-item", type: "button", onclick: () => showMemory(m.id) },
          h("span", { class: "queue-title" }, m.title),
          lifecycleChip(m.status),
          h("span", { class: "queue-meta" }, h("span", { class: "tag" }, typeLabel(m.memory_type)), metaPair("Asset", m.asset_id), metaPair("Recorded", fmtAgo(m.created_at))))))),
    ),
  );
}

function readouts(list) {
  return h("dl", { class: "readouts" }, list.map((r) =>
    h("div", { class: `readout${r.sev ? ` is-${r.sev}` : ""}` },
      h("dt", null, r.to ? h("a", { href: r.to }, r.label) : r.label),
      h("dd", null, r.value === null || r.value === undefined ? "—" : num(r.value), h("span", { class: "readout-note" }, r.note)),
    )));
}

function barList(rows) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return h("ul", { class: "bars" }, rows.map((r) =>
    h("li", null, h(r.to ? "a" : "span", { class: "bar-row", href: r.to || null, title: `${r.label}: ${r.value}` },
      h("span", { class: "bar-label" }, r.label),
      h("span", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", style: `width:${(r.value / max) * 100}%` })),
      h("span", { class: "bar-value" }, num(r.value)),
    ))));
}

/** Process schematic of the memory pipeline. Each stage links to the page it powers. */
function schematic({ svc, total, active, pending, failed }) {
  const st = (name) => svc[name]?.status;
  const sev = (name) => (st(name) === "healthy" ? "normal" : st(name) === "unhealthy" ? "crit" : "warn");
  const word = (name) => (SERVICE_STATE[st(name)] || ["Unknown"])[0];
  const llm = svc.llm || {};
  const llmSev = llm.synthetic ? "info" : llm.status === "healthy" ? "normal" : "warn";
  const llmWord = llm.synthetic ? "Test provider" : (SERVICE_STATE[llm.status] || ["Unknown"])[0];
  const qOk = st("qdrant") === "healthy";
  const nOk = st("neo4j") === "healthy";
  const pgSev = sev("postgres");
  const outboxSev = failed ? "crit" : pending ? "warn" : "normal";

  const node = (x, y, w, name, role, value, stateText, severity, to, label, extra = "") => {
    const a = s("a", { href: to, "aria-label": label, class: `node is-${severity === "normal" ? "ok" : severity}${extra}`, transform: `translate(${x} ${y})` });
    a.append(
      s("rect", { width: w, height: 104, rx: 4 }),
      s("text", { class: "node-name", x: 14, y: 26 }, name),
      s("text", { class: "node-role", x: 14, y: 44 }, role),
      s("text", { class: "node-value", x: 14, y: 78 }, value),
      s("text", { class: "node-state", x: 14, y: 96 }, stateText),
    );
    return a;
  };
  const pipe = (d, ok = true) => [s("path", { class: `pipe${ok ? "" : " pipe-broken"}`, d }), ok ? s("path", { class: "pipe-flow", d }) : null];

  const svg = s("svg", { viewBox: "0 0 1080 300", role: "group", "aria-labelledby": "sch-title" },
    s("title", { id: "sch-title" }, "Memory pipeline. Each stage opens the page it powers."),
    ...pipe("M210 150 H290"),
    ...pipe("M470 150 H520 V70 H580", qOk),
    ...pipe("M470 150 H520 V230 H580", nOk),
    ...pipe("M760 70 H800 V150 H860", qOk),
    ...pipe("M760 230 H800 V150 H860", nOk),
    s("text", { class: "pipe-label", x: 214, y: 140 }, "commit"),
    s("text", { class: "pipe-label", x: 528, y: 62 }, "vectors"),
    s("text", { class: "pipe-label", x: 528, y: 252 }, "graph"),
    s("text", { class: "pipe-label", x: 810, y: 140 }, "cites"),
    node(20, 98, 190, "PostgreSQL", "Canonical record store", `${num(total)} records`, `${word("postgres")}, ${num(active)} active`, pgSev, href("memories"),
      `PostgreSQL, ${word("postgres")}, ${total} records. Open Records.`, " is-canonical"),
    node(290, 98, 180, "Outbox", "Projection queue", pending === null ? "—" : `${num(pending)} pending`, failed ? `${num(failed)} failed` : "No failures", outboxSev, href("system"),
      `Outbox, ${pending ?? "unknown"} pending, ${failed ?? "unknown"} failed. Open System health.`),
    node(580, 18, 180, "Qdrant", "Vector projection", word("qdrant"), qOk ? "Meaning search on" : "Meaning search off", sev("qdrant"), href("search"),
      `Qdrant, ${word("qdrant")}. Open Search.`),
    node(580, 178, 180, "Neo4j", "Graph projection", word("neo4j"), nOk ? "Relationships on" : "Relationships off", sev("neo4j"), href("graph"),
      `Neo4j, ${word("neo4j")}. Open Relationships.`),
    node(860, 98, 200, "Investigate", "Cited answers + checks", llmWord, llm.active_model || llm.model || "", llmSev, href("investigate"),
      `Investigations, answer model ${llmWord}. Open Investigate.`),
  );

  const stage = (name, role, value, label, severity, to) =>
    h("li", null, h("a", { href: to }, h("strong", null, name), h("span", { class: "cell-sub" }, `${role}: ${value}`)), stateChip(label, severity));
  const list = h("ol", { class: "pipeline-list", "aria-label": "Memory pipeline" },
    stage("PostgreSQL", "Canonical records", `${num(total)} records`, word("postgres"), pgSev, href("memories")),
    stage("Outbox", "Projection queue", pending === null ? "unknown" : `${num(pending)} pending`, failed ? `${num(failed)} failed` : pending ? "Backlog" : "Clear", outboxSev, href("system")),
    stage("Qdrant", "Vector projection", qOk ? "meaning search on" : "meaning search off", word("qdrant"), sev("qdrant"), href("search")),
    stage("Neo4j", "Graph projection", nOk ? "relationships on" : "relationships off", word("neo4j"), sev("neo4j"), href("graph")),
    stage("Investigate", "Cited answers", llm.active_model || llm.model || "unknown", llmWord, llmSev, href("investigate")),
  );

  const down = [!qOk && "Qdrant", !nOk && "Neo4j"].filter(Boolean);
  const caption = down.length
    ? `${down.join(" and ")} ${down.length > 1 ? "are" : "is"} unavailable. Records are still saved to PostgreSQL and queued in the outbox; the projection worker applies them once the store is back. ${down.length > 1 ? "Investigations fall back to keyword matching in PostgreSQL meanwhile." : ""}`
    : "Every write lands in PostgreSQL first, then the outbox projects it into Qdrant for vector search and Neo4j for relationships. Investigations cite only PostgreSQL records.";

  return h("figure", { class: "panel schematic schematic-figure" }, svg, list, h("figcaption", null, caption));
}

/* --------------------------------------------------------- incidents */

async function viewIncidents(params) {
  const head = () => pageHead("Incidents", "Each incident with everything recorded against it, in the order it happened.",
    [h("button", { class: "btn", type: "button", onclick: () => memoryForm({ defaults: { memory_type: "incident" }, title: "New incident" }) }, "New incident")]);
  put(main, head(), skeleton());
  const all = await fetchAllMemories();
  if (!all.ok) return put(main, head(), notice("crit", "Records can't be loaded", all.error));

  const incidents = deriveIncidents(all.items);
  if (!incidents.length) {
    return put(main, head(), all.items.length
      ? empty("No incidents recorded", "Records with an incident ID are grouped here. Create an incident to start one.")
      : sampleDataEmpty());
  }

  const selected = incidents.find((i) => i.id === params.get("id")) || incidents[0];
  const detail = h("section", { class: "panel", "aria-live": "polite" });

  const list = h("ul", { class: "incident-list", "aria-label": "Incidents" }, incidents.map((inc) =>
    h("li", null, h("button", {
      type: "button",
      "aria-pressed": inc === selected ? "true" : "false",
      onclick: (e) => {
        list.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        e.currentTarget.setAttribute("aria-pressed", "true");
        history.replaceState(null, "", href("incidents", { id: inc.id }));
        showIncident(inc);
      },
    },
      h("span", { class: "incident-id" }, inc.head.title),
      h("span", { class: "incident-sub" }, `${inc.id} on ${inc.head.asset_id || "unknown asset"}`),
      inc.isResolved ? stateChip("Resolved", "normal") : stateChip("Open", "warn"),
    ))));

  const showIncident = (inc) => {
    const ctx = contextOf(inc.head);
    const findings = inc.recs.filter((r) => r.source_type === "investigation").length;
    put(detail,
      h("div", { class: "panel-head" },
        h("div", null,
          h("h2", null, inc.head.title),
          h("p", null, inc.id, inc.head.asset_id ? [", ", navLink(inc.head.asset_id, "memories", { asset: inc.head.asset_id, status: "any" })] : null, inc.head.facility_id ? `, ${inc.head.facility_id}` : "")),
        inc.isResolved ? stateChip("Resolved", "normal") : stateChip("Open", "warn")),
      h("div", { class: "page-actions" },
        navLink("Investigate this incident", "investigate", { anchor: inc.head.id, q: `What caused ${inc.id} on ${inc.head.asset_id || "this asset"}, and what fixed it or should fix it?` }, "btn btn-primary"),
        h("button", { class: "btn", type: "button", onclick: () => memoryForm({ defaults: { ...ctx, memory_type: "observation" }, title: `Add to ${inc.id}` }) }, "Add to this incident"),
        navLink("Show relationships", "graph", { anchor: inc.head.id }, "btn")),
      h("p", { class: "toolbar-note" }, `${inc.recs.length} record${inc.recs.length === 1 ? "" : "s"}${findings ? `, ${findings} recorded from investigations` : ""}. Select a step to open it.`),
      h("ol", { class: "timeline" }, inc.recs.map((m) =>
        h("li", { class: `is-${m.memory_type}` },
          h("span", { class: "timeline-mark", "aria-hidden": "true" }, icon(m.memory_type === "incident" ? "warn" : m.memory_type === "resolution" ? "ok" : "info")),
          h("p", { class: "timeline-when" }, `${typeLabel(m.memory_type)}, ${fmtWhen(whenOf(m))}${m.source_type === "investigation" ? ", from an investigation" : ""}`),
          h("h3", { class: "timeline-title" }, h("button", { type: "button", onclick: () => showMemory(m.id) }, m.title)),
          h("p", null, m.content),
          m.status !== "active" ? h("p", null, lifecycleChip(m.status)) : null,
        ))),
    );
  };

  showIncident(selected);
  put(main, head(), h("div", { class: "grid grid-split" }, h("div", null, list), detail));
}

/* ----------------------------------------------------------- records */

async function viewMemories(params) {
  const filters = {
    memory_type: params.get("type") || "",
    status: params.get("status") === null ? "active" : params.get("status") === "any" ? "" : params.get("status"),
    asset_id: params.get("asset") || "",
    facility_id: params.get("facility") || "",
    source_type: params.get("source") || "",
    q: params.get("q") || "",
  };
  const pageSize = 25;
  let page = 1;
  const head = () => pageHead("Records", "Every observation, incident, diagnosis and fix in canonical storage.",
    [navLink("Import work orders", "import", {}, "btn"), h("button", { class: "btn btn-primary", type: "button", onclick: () => memoryForm() }, "New record")]);

  put(main, head(), skeleton());
  const all = await fetchAllMemories();
  if (!all.ok) return put(main, head(), notice("crit", "Records can't be loaded", all.error));
  const items = all.items;
  if (!items.length) return put(main, head(), sampleDataEmpty());
  const distinct = (k) => [...new Set(items.map((m) => m[k]).filter(Boolean))].sort();

  const select = (name, label, options, value) => h("div", { class: "field" },
    h("label", { for: `flt-${name}` }, label),
    h("select", { id: `flt-${name}`, name }, h("option", { value: "" }, "Any"), options.map(([v, l]) => h("option", { value: v, selected: v === value }, l))));

  const toolbar = h("form", { class: "toolbar", role: "search", "aria-label": "Filter records", onsubmit: (e) => e.preventDefault() },
    h("div", { class: "field field-grow" }, h("label", { for: "flt-q" }, "Find in title or text"),
      h("input", { type: "search", id: "flt-q", name: "q", value: filters.q, placeholder: "e.g. spindle, thermocouple, coupling" })),
    select("memory_type", "Type", Object.entries(TYPE_LABEL), filters.memory_type),
    select("status", "Status", Object.entries(LIFECYCLE).map(([k, [l]]) => [k, l]), filters.status),
    select("asset_id", "Asset", distinct("asset_id").map((v) => [v, v]), filters.asset_id),
    select("facility_id", "Facility", distinct("facility_id").map((v) => [v, v]), filters.facility_id),
    select("source_type", "Source", distinct("source_type").map((v) => [v, v === "work_order" ? "Work order (CMMS)" : v.replace(/_/g, " ")]), filters.source_type),
  );
  const tableHost = h("div", { class: "stack" });
  put(main, head(), h("div", { class: "panel" }, toolbar), tableHost);

  const draw = () => {
    const q = filters.q.toLowerCase();
    const rows = items.filter((m) =>
      (!filters.memory_type || m.memory_type === filters.memory_type) &&
      (!filters.status || m.status === filters.status) &&
      (!filters.asset_id || m.asset_id === filters.asset_id) &&
      (!filters.facility_id || m.facility_id === filters.facility_id) &&
      (!filters.source_type || m.source_type === filters.source_type) &&
      (!q || `${m.title} ${m.content}`.toLowerCase().includes(q)))
      .sort((a, b) => String(whenOf(b)).localeCompare(String(whenOf(a))));
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    page = Math.min(Math.max(1, page), pages);
    const slice = rows.slice((page - 1) * pageSize, page * pageSize);

    if (!rows.length) {
      return put(tableHost, empty("Nothing matches these filters", "Clear a filter, or set Status to Any to include archived and superseded records.",
        filters.q ? navLink("Search by meaning instead", "search", { q: filters.q }, "btn") : null));
    }
    const table = h("div", { class: "table-wrap" }, h("table", null,
      h("caption", null, `${rows.length} record${rows.length === 1 ? "" : "s"}. Select a row to open it.`),
      h("thead", null, h("tr", null, ["Record", "Type", "Status", "Asset", "Incident", "Observed"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", null, slice.map((m) => {
        const open = () => showMemory(m.id);
        return h("tr", { class: "is-clickable", tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } } },
          h("td", null, h("span", { class: "cell-title" }, m.title), h("span", { class: "cell-sub" }, m.content.length > 120 ? `${m.content.slice(0, 120)}…` : m.content)),
          h("td", null, typeLabel(m.memory_type)),
          h("td", null, lifecycleChip(m.status)),
          h("td", null, m.asset_id || "—"),
          h("td", null, m.incident_id ? h("a", { href: href("incidents", { id: m.incident_id }), onclick: (e) => e.stopPropagation() }, m.incident_id) : "—"),
          h("td", null, fmtWhen(whenOf(m))));
      })),
    ));
    const pager = h("div", { class: "pager" },
      h("span", null, `Page ${page} of ${pages}`),
      h("span", { class: "page-actions" },
        h("button", { class: "btn", type: "button", disabled: page <= 1, onclick: () => { page -= 1; draw(); } }, "Previous"),
        h("button", { class: "btn", type: "button", disabled: page >= pages, onclick: () => { page += 1; draw(); } }, "Next")));
    put(tableHost, table, pages > 1 ? pager : null);
  };

  toolbar.addEventListener("input", (e) => {
    filters[e.target.name] = e.target.value;
    page = 1;
    history.replaceState(null, "", href("memories", { type: filters.memory_type, status: filters.status || "any", asset: filters.asset_id, facility: filters.facility_id, source: filters.source_type, q: filters.q }));
    draw();
  });
  draw();
}

/* ------------------------------------------------------------ import */

// Maintenance history from the plant's CMMS (Maximo, SAP PM, ...). The same
// API call previews (dry_run) and writes, so what is shown is what is written.
async function viewImport() {
  const st = { csv: null, fileName: null, columnMap: {}, report: null };
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  const head = pageHead("Import work orders",
    "Load maintenance history exported from Maximo, SAP PM or another CMMS. Nothing is written until you confirm.",
    [h("a", { class: "btn", href: "samples/work-orders-sample.csv", download: "work-orders-sample.csv" }, "Download sample export")]);

  const fileInput = h("input", { type: "file", id: "f-file", name: "file", accept: ".csv,.txt,text/csv" });
  const synthetic = h("input", { type: "checkbox", name: "is_synthetic" });
  const dateOrder = h("select", { id: "f-date_order", name: "date_order" },
    h("option", { value: "month" }, "Month first (04/03/2026 = April 3)"),
    h("option", { value: "day" }, "Day first (04/03/2026 = 4 March)"));
  const tzInput = h("input", { type: "text", id: "f-timezone", name: "timezone", value: tz });
  const facility = h("input", { type: "text", id: "f-facility", name: "facility", placeholder: "Only used when the file has no site or plant column" });

  const form = h("form", { class: "form-grid", novalidate: true, onsubmit: (e) => e.preventDefault() },
    formField("file", "Work-order export (CSV)", fileInput, "Header row first. Comma, semicolon or tab separated; up to 20,000 rows.", true),
    formField("date_order", "Date order", dateOrder, "How dates like 04/03/2026 are written in the export"),
    formField("timezone", "Plant time zone", tzInput, "Used for dates without a time zone"),
    formField("facility", "Default facility", facility, null),
    h("div", { class: "field" }, h("span", null, "Data"), h("label", { class: "check" }, synthetic, "Sample or synthetic data (labelled as such everywhere)")),
  );
  const previewBtn = h("button", { class: "btn btn-primary", type: "button" }, "Preview import");
  const sampleBtn = h("button", { class: "btn", type: "button" }, "Preview the sample export");
  const result = h("div", { class: "stack", "aria-live": "polite" });

  const body = (dryRun) => ({
    csv: st.csv, file_name: st.fileName, dry_run: dryRun, is_synthetic: synthetic.checked,
    day_first: dateOrder.value === "day", timezone: tzInput.value.trim() || "UTC",
    default_facility_id: facility.value.trim() || null, column_map: st.columnMap,
  });

  const run = async (dryRun, button) => {
    if (!st.csv) { clearInvalid(form); markInvalid(form, "file", "Choose a CSV file first"); return; }
    busy(button, true);
    const r = await api("/imports/work-orders", { method: "POST", timeout: 120000, body: body(dryRun) });
    busy(button, false);
    if (!r.ok) return put(result, notice("crit", dryRun ? "The file can't be imported yet" : "Import failed; nothing was written", r.error));
    st.report = r.data;
    return dryRun ? showPreview(r.data) : showDone(r.data);
  };

  const readFile = (file) => new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => reject(fr.error);
    fr.readAsText(file);
  });

  fileInput.addEventListener("change", async () => {
    clearInvalid(form);
    const f = fileInput.files[0];
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) { markInvalid(form, "file", "Larger than 10 MB; split the export"); return; }
    st.csv = await readFile(f);
    st.fileName = f.name;
    st.columnMap = {};
    run(true, previewBtn);
  });
  previewBtn.addEventListener("click", () => run(true, previewBtn));
  sampleBtn.addEventListener("click", async () => {
    busy(sampleBtn, true);
    try {
      const res = await fetch("samples/work-orders-sample.csv");
      st.csv = await res.text();
    } catch (err) { busy(sampleBtn, false); return toast(`Couldn't load the sample: ${err.message}`, true); }
    busy(sampleBtn, false);
    st.fileName = "work-orders-sample.csv";
    st.columnMap = {};
    synthetic.checked = true;
    run(true, previewBtn);
  });

  const showPreview = (d) => {
    const toWrite = d.missing_required.length ? 0 : d.new + d.changed;
    const columnSelect = (m) => {
      const sel = h("select", { "aria-label": `CSV column for ${m.label}` },
        h("option", { value: "" }, m.required ? "Choose a column" : "Not used"),
        d.columns.map((c) => h("option", { value: c, selected: c === m.column }, c)));
      sel.addEventListener("change", () => { st.columnMap = { ...st.columnMap, [m.field]: sel.value }; run(true, previewBtn); });
      return sel;
    };
    const importBtn = h("button", { class: "btn btn-primary", type: "button", disabled: toWrite === 0 },
      d.missing_required.length ? "Map the required columns first"
        : toWrite ? `Import ${num(toWrite)} work order${toWrite === 1 ? "" : "s"}` : "Nothing new to import");
    importBtn.addEventListener("click", () => run(false, importBtn));

    put(result,
      d.missing_required.length ? notice("crit", `No column found for ${d.missing_required.map((m) => m.label.toLowerCase()).join(" or ")}`,
        `Pick ${d.missing_required.length === 1 ? "it" : "them"} under Column mapping below and the preview will run again. Columns in this file: ${d.columns.join(", ")}.`) : null,
      d.is_synthetic || d.missing_required.length ? null : notice("info", "These records will be treated as real plant history",
        "If this is a test or sample file, tick “Sample or synthetic data” above and preview again."),
      h("section", { class: "panel", "aria-labelledby": "imp-sum" },
        h("div", { class: "panel-head" }, h("h2", { id: "imp-sum" }, `Preview of ${d.file_name || "the file"}`),
          h("p", null, `${num(d.rows_read)} rows read, ${num(d.assets)} assets, ${d.facilities.length ? d.facilities.join(", ") : "no facility"}`,
            d.date_range ? `, ${fmtWhen(d.date_range[0])} to ${fmtWhen(d.date_range[1])}` : "")),
        readouts([
          { label: "New", value: d.new, note: "will be created" },
          { label: "Changed", value: d.changed, note: "replace the earlier version, which is kept as superseded" },
          { label: "Unchanged", value: d.unchanged, note: "already imported; skipped" },
          { label: "Problems", value: d.errors + d.warnings, note: `${d.errors} rows skipped, ${d.warnings} warnings`, sev: d.errors ? "crit" : d.warnings ? "warn" : null },
        ]),
        h("div", { class: "page-actions" }, importBtn)),
      h("section", { class: "panel", "aria-labelledby": "imp-map" },
        h("div", { class: "panel-head" }, h("h2", { id: "imp-map" }, "Column mapping"),
          h("p", null, "Detected from the header row. Change a column and the preview updates.")),
        h("div", { class: "table-wrap" }, h("table", null,
          h("caption", { class: "visually-hidden" }, "How CSV columns map to AegisOps fields"),
          h("thead", null, h("tr", null, ["AegisOps field", "CSV column"].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", null, d.mapping.map((m) => h("tr", null,
            h("td", null, m.label, m.required ? h("span", { class: "cell-sub" }, "Required") : null),
            h("td", null, columnSelect(m))))))),
        d.unmapped_columns.length
          ? h("p", { class: "toolbar-note" }, `Kept on each record as extra fields: ${d.unmapped_columns.join(", ")}.`) : null),
      d.issues.length ? h("section", { class: "panel", "aria-labelledby": "imp-iss" },
        h("div", { class: "panel-head" }, h("h2", { id: "imp-iss" }, "Rows to check"),
          h("p", null, d.issues_truncated ? `First ${d.issues.length} shown; ${d.issues_truncated} more.` : "Row numbers count data rows after the header.")),
        h("div", { class: "table-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Row", "Severity", "Problem"].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", null, d.issues.map((i) => h("tr", null,
            h("td", null, String(i.row)),
            h("td", null, i.level === "error" ? stateChip("Skipped", "crit") : stateChip("Warning", "warn")),
            h("td", null, i.message))))))) : null,
      d.sample.length ? h("section", { class: "panel", "aria-labelledby": "imp-smp" },
        h("div", { class: "panel-head" }, h("h2", { id: "imp-smp" }, "How the first records will look")),
        h("ul", { class: "queue" }, d.sample.map((r) => h("li", null, h("div", { class: "queue-item" },
          h("span", { class: "queue-title" }, r.title),
          h("span", { class: "cell-sub" }, r.content.length > 220 ? `${r.content.slice(0, 220)}…` : r.content),
          h("span", { class: "queue-meta" },
            metaPair("Asset", r.asset_id), metaPair("Location", r.component_id), metaPair("Incident", r.incident_id),
            r.finished_at ? metaPair("Finished", fmtWhen(r.finished_at)) : metaPair("Reported", r.reported_at ? fmtWhen(r.reported_at) : "no date"),
            metaPair("Work type", r.work_type_class))))))) : null,
    );
  };

  const showDone = (d) => {
    const w = d.written.created + d.written.superseded;
    put(result, notice("info", `Imported ${num(d.written.created)} new and ${num(d.written.superseded)} updated work orders`,
      `${num(d.unchanged)} were already up to date. The records are in PostgreSQL now and findable by keyword; ` +
      `the projection worker is indexing ${num(w)} of them for meaning and relationships (see System health for progress).`,
      [navLink("Open imported records", "memories", { source: "work_order", status: "active" }, "btn btn-primary"),
       navLink("Investigate", "investigate", {}, "btn"), navLink("System health", "system", {}, "btn")]));
    refreshHealth();
  };

  put(main, head,
    h("section", { class: "panel", "aria-labelledby": "imp-src" },
      h("div", { class: "panel-head" }, h("h2", { id: "imp-src" }, "Choose an export"),
        h("p", null, "One row per work order. Re-importing a newer export is safe: unchanged work orders are skipped and changed ones keep their history.")),
      form, h("div", { class: "page-actions" }, previewBtn, sampleBtn)),
    result);
}

/* ------------------------------------------------------- investigate */

async function viewInvestigate(params) {
  const anchor = params.get("anchor") || "";
  const q = params.get("q") || "";
  const svc = services();
  const out = h("div", { class: "stack", "aria-live": "polite" });

  const question = h("textarea", { id: "ask-q", name: "question", rows: 3, required: true, placeholder: "e.g. Why are drill cell DC-3 holes oversize, and what fixed it last time?" }, q);
  const limit = h("select", { id: "ask-limit" }, [3, 5, 8, 10].map((n) => h("option", { value: n, selected: n === 5 }, `${n} records`)));
  const askBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Investigate");
  const anchorNote = h("p", { class: "field-grow toolbar-note" });

  if (anchor) {
    put(anchorNote, "Starting from a record ");
    api(`/memories/${anchor}`).then((r) => {
      put(anchorNote, "Starting from ",
        h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(anchor) }, r.ok ? r.data.title : `record ${shortId(anchor)}`),
        " ", h("a", { href: href("investigate", { q: question.value }) }, "Clear"));
    });
  }

  const form = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault();
    const text = question.value.trim();
    if (!text) { question.setAttribute("aria-invalid", "true"); question.focus(); return; }
    question.removeAttribute("aria-invalid");
    history.replaceState(null, "", href("investigate", { q: text, anchor }));
    busy(askBtn, true);
    put(out, h("div", { class: "panel" }, skeleton()));
    const r = await api("/investigations", { method: "POST", timeout: 60000, body: { question: text, context_limit: Number(limit.value), anchor_memory_id: anchor || null } });
    busy(askBtn, false);
    if (!r.ok) return put(out, notice("crit", "The investigation didn't complete", r.error));
    put(out, ...renderInvestigation(r.data, anchor));
  } },
    h("div", { class: "field" }, h("label", { for: "ask-q" }, "Question"), question),
    h("div", { class: "toolbar" },
      h("div", { class: "field" }, h("label", { for: "ask-limit" }, "Use up to"), limit),
      anchor ? anchorNote : h("span", { class: "field-grow" }),
      askBtn),
  );

  const warnings = [];
  if (!capable("qdrant") && !capable("neo4j")) warnings.push(notice("warn", "Vector and graph search are offline", "Investigations will use keyword matches from PostgreSQL until Qdrant or Neo4j is back.", [navLink("Open System health", "system", {}, "btn")]));
  else if (!capable("neo4j")) warnings.push(notice("warn", "Relationship store is offline", "Investigations use vector matches only; graph links return when Neo4j reconnects."));
  if (svc.llm?.synthetic) warnings.push(notice("info", "Answers come from the deterministic test provider", "It lists the retrieved records with citations and adds no reasoning. Set LLM_PROVIDER=openai and OPENAI_API_KEY for model-written answers."));

  put(main, pageHead("Investigate", "Ask about an asset, symptom or incident. The answer cites canonical records, shows how it was built, and is checked before you record anything."), ...warnings, form, out);
  if (q) form.requestSubmit(); else question.focus();
}

function renderInvestigation(d, anchor) {
  const parts = [];
  const re = /\[Memory\s+(\d+)\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(d.answer))) {
    parts.push(d.answer.slice(last, m.index));
    const n = Number(m[1]);
    parts.push(n >= 1 && n <= d.evidence.length
      ? h("a", { class: "cite", href: `#ev-${n}`, onclick: (e) => { e.preventDefault(); const el = document.getElementById(`ev-${n}`); el.scrollIntoView({ block: "center" }); el.focus(); } }, `Record ${n}`)
      : h("span", { class: "cite" }, `Record ${n} (not in evidence)`));
    last = m.index + m[0].length;
  }
  parts.push(d.answer.slice(last));

  const critic = d.critic || {};
  const verdict = critic.is_supported ? stateChip("Citations verified", "normal") : stateChip("Not verified", "warn");
  const modeNote = d.retrieval_mode === "keyword_fallback"
    ? notice("warn", "Matched by keywords", "Vector and graph stores returned nothing, so evidence was matched by words in PostgreSQL. Treat the ranking as approximate.")
    : null;
  const canRecord = d.evidence.length > 0;

  const answer = h("section", { class: "panel", "aria-labelledby": "ans-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "ans-title" }, "Answer"), h("span", { class: "page-actions" }, d.is_synthetic_response ? stateChip("Test provider", "info") : h("span", { class: "tag" }, d.model_name), verdict)),
    modeNote,
    h("p", { class: "answer" }, parts),
    !critic.is_supported && critic.notes ? h("p", { class: "toolbar-note" }, `Check: ${critic.notes}`) : null,
    h("div", { class: "page-actions" },
      h("button", { class: "btn btn-primary", type: "button", disabled: !canRecord, onclick: () => findingForm(d, anchor) }, "Record finding"),
      h("button", { class: "btn", type: "button", disabled: !canRecord, onclick: () => {
        evalState.pending = { question: d.question, candidates: d.evidence.map((e) => ({ id: e.memory_id, title: e.title })) };
        go("evaluation");
      } }, "Add to benchmark"),
      navLink("Compare search modes", "search", { q: d.question, mode: "hybrid" }, "btn")),
  );

  const evidence = h("section", { class: "panel", "aria-labelledby": "ev-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "ev-title" }, "Evidence"), h("p", null, `${d.evidence_count} record${d.evidence_count === 1 ? "" : "s"}`)),
    d.evidence.length
      ? h("ol", { class: "evidence" }, d.evidence.map((e, i) => h("li", { id: `ev-${i + 1}`, tabindex: "-1" },
          h("div", { class: "evidence-head" },
            h("span", { class: "evidence-n" }, `Record ${i + 1}`),
            h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(e.memory_id) }, e.title)),
          h("p", null, e.content_preview),
          h("div", { class: "queue-meta" },
            h("span", { class: "tag" }, typeLabel(e.memory_type)),
            h("span", { class: "tag" }, SOURCE_LABEL[e.retrieval_source] || e.retrieval_source),
            metaPair("Asset", e.asset_id), metaPair("Confidence", pct(e.confidence))))))
      : empty("No supporting records", "Nothing in canonical storage matched. Rephrase with an asset name or symptom, or record what's missing.",
          h("button", { class: "btn", type: "button", onclick: () => memoryForm() }, "New record")),
  );

  const stepNames = { retrieval: "Retrieve", graph_reasoning: "Follow graph links", synthesis: "Write answer", critic: "Check citations" };
  const steps = h("section", { class: "panel", "aria-labelledby": "steps-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "steps-title" }, "How this answer was built"), h("p", null, `${num(d.total_latency_ms, 0)} ms in total`)),
    h("ol", { class: "steps" }, d.steps.map((st) => h("li", null,
      h("strong", null, stepNames[st.type] || st.type),
      h("span", null, st.description),
      st.latency_ms ? h("span", { class: "cell-sub" }, `${num(st.latency_ms, 0)} ms`) : null))),
  );

  return [h("div", { class: "grid grid-main" }, h("div", { class: "stack" }, answer, steps), evidence)];
}

/** Turn a confirmed conclusion into a canonical record, linked to its evidence and incident. */
function findingForm(d, anchor) {
  const typeSelect = h("select", { id: "f-memory_type", name: "memory_type" },
    [["diagnosis", "Diagnosis"], ["recommendation", "Recommendation"], ["observation", "Observation"], ["resolution", "Resolution"]].map(([v, l]) => h("option", { value: v }, l)));
  const evidenceBoxes = h("fieldset", { class: "span-2" }, h("legend", null, "Evidence this finding rests on"),
    h("div", { class: "check-list" }, d.evidence.map((e, i) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "evidence", value: e.memory_id, checked: true }), `Record ${i + 1}: ${e.title}`))));
  const form = h("form", { class: "form-grid", novalidate: true },
    formField("memory_type", "Finding type", typeSelect),
    h("div", { class: "field" }),
    formField("title", "Title", h("input", { type: "text", id: "f-title", maxlength: 200, value: "" }), "State the conclusion, e.g. “Worn spindle bearing caused oversize holes”", true),
    formField("content", "Finding", h("textarea", { id: "f-content", rows: 4 }, d.is_synthetic_response ? "" : d.answer),
      d.is_synthetic_response ? "Write the conclusion in your own words; the test provider only listed records." : "Edit the model's answer into the conclusion you're confirming.", true),
    evidenceBoxes,
    formField("confidence", "Confidence (0–1)", h("input", { type: "number", id: "f-confidence", min: 0, max: 1, step: 0.01, value: 0.7 }), "Findings need 0.6 or more"),
    formField("importance", "Importance (0–1)", h("input", { type: "number", id: "f-importance", min: 0, max: 1, step: 0.01, value: 0.6 }), "Findings need 0.4 or more"),
  );
  const submit = h("button", { class: "btn btn-primary", type: "button" }, "Record finding");
  submit.addEventListener("click", async () => {
    clearInvalid(form);
    const title = form.querySelector("#f-title").value.trim();
    const content = form.querySelector("#f-content").value.trim();
    const evidence = [...form.querySelectorAll("input[name=evidence]:checked")].map((i) => i.value);
    let invalid = null;
    if (!title) invalid = invalid || markInvalid(form, "title", "Required");
    if (!content) invalid = invalid || markInvalid(form, "content", "Required");
    if (invalid) return invalid.focus();
    if (!evidence.length) return toast("Select at least one evidence record", true);
    busy(submit, true);
    const res = await api("/investigations/findings", { method: "POST", body: {
      question: d.question,
      memory_type: form.querySelector("#f-memory_type").value,
      title, content,
      evidence_memory_ids: evidence,
      anchor_memory_id: anchor || d.anchor_memory_id || evidence[0],
      confidence: Number(form.querySelector("#f-confidence").value),
      importance: Number(form.querySelector("#f-importance").value),
      answer_was_synthetic: d.is_synthetic_response,
    } });
    busy(submit, false);
    if (!res.ok) return toast(res.error, true);
    closeDialog();
    const rec = res.data;
    toast(rec.incident_id ? `Finding recorded on ${rec.incident_id}` : "Finding recorded");
    if (rec.incident_id) go("incidents", { id: rec.incident_id }); else showMemory(rec.id);
  });
  openDialog("Record finding", h("div", null,
    notice("info", "You are confirming this, not the system", "The finding is saved as a canonical record with its evidence attached. It inherits the asset and incident of the record you started from, or of the top evidence record."),
    form), [h("button", { class: "btn", type: "button", onclick: closeDialog }, "Cancel"), submit]);
}

/* ------------------------------------------------------------ search */

async function viewSearch(params) {
  const mode = params.get("mode") || "hybrid";
  const out = h("div", { class: "stack", "aria-live": "polite" });
  const query = h("input", { type: "search", id: "s-q", name: "query", value: params.get("q") || "", placeholder: "Describe a symptom, part or fix", required: true });
  const modes = [["semantic", "Meaning"], ["graph", "Relationships"], ["hybrid", "Both"]];
  const seg = h("fieldset", null, h("legend", null, "Match by"),
    h("div", { class: "segmented" }, modes.map(([v, l]) => h("label", null,
      h("input", { type: "radio", name: "mode", value: v, checked: v === mode }), h("span", null, l)))));
  const inactive = h("label", { class: "check" }, h("input", { type: "checkbox", name: "inactive" }), "Include archived and disputed");
  const go2 = h("button", { class: "btn btn-primary", type: "submit" }, "Search");

  const form = h("form", { class: "panel", role: "search", onsubmit: async (e) => {
    e.preventDefault();
    const text = query.value.trim();
    if (!text) return query.focus();
    const m = form.querySelector("input[name=mode]:checked").value;
    history.replaceState(null, "", href("search", { mode: m, q: text }));
    busy(go2, true);
    const r = await api("/search/hybrid", { method: "POST", body: { query: text, mode: m, limit: 20, include_inactive: inactive.querySelector("input").checked } });
    busy(go2, false);
    if (!r.ok) {
      return put(out, notice(r.status === 503 ? "warn" : "crit", r.status === 503 ? "This search mode is offline" : "Search failed", r.error,
        r.status === 503 ? [navLink("Open System health", "system", {}, "btn"), navLink("Find by text in Records", "memories", { q: text }, "btn")] : null));
    }
    const res = r.data.results || [];
    const anchorRow = r.data.anchor_memory_id ? res.find((x) => x.memory_id === r.data.anchor_memory_id) : null;
    put(out,
      h("div", { class: "page-actions" },
        navLink("Investigate this question", "investigate", { q: text }, "btn"),
        r.data.anchor_memory_id ? navLink("Show relationships of the top match", "graph", { anchor: r.data.anchor_memory_id }, "btn") : null),
      res.length
        ? h("div", { class: "table-wrap" }, h("table", null,
            h("caption", null, `${res.length} result${res.length === 1 ? "" : "s"} in ${num(r.data.latency_ms, 0)} ms${r.data.anchor_memory_id && m !== "semantic" ? `. Graph links are relative to ${anchorRow ? `“${anchorRow.title}”` : "the best vector match"}.` : ""}`),
            h("thead", null, h("tr", null, ["Record", "Found by", "Similarity", "Status", "Asset"].map((c) => h("th", { scope: "col" }, c)))),
            h("tbody", null, res.map((x) => {
              const open = () => showMemory(x.memory_id);
              return h("tr", { class: "is-clickable", tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
                h("td", null, h("span", { class: "cell-title" }, x.title || shortId(x.memory_id)), h("span", { class: "cell-sub" }, x.content_preview || "Not found in PostgreSQL")),
                h("td", null, h("span", { class: "tag" }, SOURCE_LABEL[x.retrieval_source] || x.retrieval_source)),
                h("td", null, typeof x.semantic_score === "number" ? scoreBar(x.semantic_score) : "—"),
                h("td", null, x.status ? lifecycleChip(x.status) : "—"),
                h("td", null, x.asset_id || "—"));
            }))))
        : empty("No matches", "Try different words, switch to Both, or include archived records."));
  } },
    h("div", { class: "toolbar" },
      h("div", { class: "field field-grow" }, h("label", { for: "s-q" }, "Search for"), query),
      seg, inactive, go2));

  const notes = [];
  if (!capable("qdrant")) notes.push(notice("warn", "Meaning search is offline", "Qdrant is unavailable. Relationship search also needs it to pick a starting record from your words."));
  if (!capable("neo4j")) notes.push(notice("warn", "Relationship search is offline", "Neo4j is unavailable, so only meaning search can run."));
  const emb = state.health?.embedding_provider;
  if (capable("qdrant") && emb && !emb.semantic) {
    notes.push(emb.name === "HashedTermEmbedding"
      ? notice("info", "Similarity is based on shared words", "The term-hashing embedding ranks records that use the same words as your query. Synonyms won't match until a semantic embedding model is configured.")
      : notice("info", "Similarity scores are test values", "The default test embedding hashes whole texts, so scores don't reflect meaning. Set EMBEDDING_PROVIDER=hashed_terms for word-based ranking, or configure a semantic model."));
  }

  put(main, pageHead("Search", "Find records by meaning, by their links to the best match, or both. These are the same retrieval modes the benchmark measures."), ...notes, form, out);
  if (params.get("q")) form.requestSubmit(); else query.focus();
}

function scoreBar(v) {
  const clamped = Math.max(0, Math.min(1, v));
  return h("span", { class: "score", title: v.toFixed(3) },
    h("span", { class: "score-track", "aria-hidden": "true" }, h("span", { class: "score-fill", style: `width:${clamped * 100}%` })),
    h("span", null, v.toFixed(2)));
}

/* ------------------------------------------------------------- graph */

async function viewGraph(params) {
  const head = () => pageHead("Relationships", "Records linked to one record through a shared asset, line, incident, source or supersession.");
  put(main, head(), skeleton());
  const all = await fetchAllMemories({ status: "" });
  if (!all.ok) return put(main, head(), notice("crit", "Records can't be loaded", all.error));
  const items = all.items;
  if (!items.length) return put(main, head(), sampleDataEmpty());
  const byId = new Map(items.map((m) => [m.id, m]));
  const anchorId = byId.has(params.get("anchor")) ? params.get("anchor") : (items.find((m) => m.memory_type === "incident") || items[0]).id;

  const picker = h("select", { id: "g-anchor" }, items.slice().sort((a, b) => a.title.localeCompare(b.title)).map((m) => h("option", { value: m.id, selected: m.id === anchorId }, `${m.title} (${typeLabel(m.memory_type)})`)));
  const hops = h("select", { id: "g-hops" }, [1, 2, 3].map((n) => h("option", { value: n, selected: n === Number(params.get("hops") || 2) }, `${n} step${n > 1 ? "s" : ""}`)));
  const out = h("div", { class: "stack", "aria-live": "polite" });

  const run = async () => {
    history.replaceState(null, "", href("graph", { anchor: picker.value, hops: hops.value }));
    put(out, skeleton());
    const r = await api("/search/graph-related", { method: "POST", body: { memory_id: picker.value, max_hops: Number(hops.value), limit: 40 } });
    if (!r.ok) {
      return put(out, notice(r.status === 503 ? "warn" : "crit", r.status === 503 ? "Relationship store is offline" : "Couldn't load relationships", r.error,
        [navLink("Open System health", "system", {}, "btn"), navLink("Investigate from this record instead", "investigate", { anchor: picker.value }, "btn")]));
    }
    const related = (r.data.related_memory_ids || []).map((id) => byId.get(id) || { id, title: shortId(id), memory_type: "unknown", status: "unknown" });
    put(out, drawGraph(byId.get(picker.value), related));
  };

  const form = h("form", { class: "panel", onsubmit: (e) => { e.preventDefault(); run(); } },
    h("div", { class: "toolbar" },
      h("div", { class: "field field-grow" }, h("label", { for: "g-anchor" }, "Start from"), picker),
      h("div", { class: "field" }, h("label", { for: "g-hops" }, "Reach"), hops),
      h("button", { class: "btn btn-primary", type: "submit" }, "Show links"),
      h("button", { class: "btn", type: "button", onclick: () => go("investigate", { anchor: picker.value, q: `What do we know about: ${byId.get(picker.value).title}?` }) }, "Investigate from here")));

  put(main, head(), !capable("neo4j") ? notice("warn", "Relationship store is offline", "Neo4j is unavailable. Links appear once it reconnects and the projection worker catches up.") : null, form, out);
  if (capable("neo4j")) run();
}

function drawGraph(anchor, related) {
  if (!related.length) return empty("No linked records", "This record doesn't share an asset, incident, line or source with any other record yet.");
  const W = 900, H = 520, cx = W / 2, cy = H / 2;
  const R = Math.min(210, 90 + related.length * 8);
  const svg = s("svg", { class: "graph-canvas", viewBox: `0 0 ${W} ${H}`, role: "group", "aria-label": `${anchor.title} and ${related.length} linked records` });
  const pos = related.map((m, i) => {
    const a = (i / related.length) * Math.PI * 2 - Math.PI / 2;
    return { m, x: cx + Math.cos(a) * R * 1.45, y: cy + Math.sin(a) * R };
  });
  for (const p of pos) svg.append(s("line", { class: "edge", x1: cx, y1: cy, x2: p.x, y2: p.y }));
  const gnode = (m, x, y, isAnchor) => {
    const label = m.title.length > 34 ? `${m.title.slice(0, 33)}…` : m.title;
    const g = s("g", { class: `gnode${isAnchor ? " is-anchor" : ""}${m.status !== "active" ? " is-inactive" : ""}`, transform: `translate(${x} ${y})`, tabindex: "0", role: "button", "aria-label": `${m.title}, ${typeLabel(m.memory_type)}, ${m.status}` });
    g.append(s("circle", { r: isAnchor ? 14 : 9 }), s("text", { x: 0, y: isAnchor ? 34 : 26, "text-anchor": "middle" }, label));
    const open = () => showMemory(m.id);
    g.addEventListener("click", open);
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    return g;
  };
  for (const p of pos) svg.append(gnode(p.m, p.x, p.y, false));
  svg.append(gnode(anchor, cx, cy, true));

  const table = h("div", { class: "table-wrap" }, h("table", null,
    h("caption", null, "Linked records as a table"),
    h("thead", null, h("tr", null, ["Record", "Type", "Status", "Asset", "Incident"].map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", null, related.map((m) => h("tr", null,
      h("td", null, h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(m.id) }, m.title)),
      h("td", null, typeLabel(m.memory_type)), h("td", null, lifecycleChip(m.status)), h("td", null, m.asset_id || "—"),
      h("td", null, m.incident_id ? navLink(m.incident_id, "incidents", { id: m.incident_id }) : "—"))))));
  return h("div", { class: "stack" }, svg, table);
}

/* -------------------------------------------------------- evaluation */

const MODE_LABEL = { semantic: "Meaning", graph: "Relationships", hybrid: "Both", agentic: "Investigation" };

async function viewEvaluation() {
  const head = pageHead("Evaluation", "Measure whether retrieval finds the records a correct answer needs. Runs use the same retrieval and metrics as the recorded CLI benchmark.");
  put(main, head, skeleton());
  const all = await fetchAllMemories({ status: "active" });
  const items = all.items || [];
  const titleOf = (id) => items.find((m) => m.id === id)?.title || `record ${shortId(id)}`;

  const caseList = h("div", { class: "stack" });
  const results = h("div", { class: "stack", "aria-live": "polite" });
  const q = h("input", { type: "text", id: "e-q", placeholder: "e.g. What fixed the oversize holes on drill cell DC-3?" });
  const expected = h("select", { id: "e-exp", multiple: true, size: 6 }, items.map((m) => h("option", { value: m.id }, m.title)));

  const drawCases = () => {
    put(caseList, evalState.cases.length
      ? h("div", { class: "table-wrap" }, h("table", null,
          h("caption", null, `${evalState.cases.length} benchmark question${evalState.cases.length === 1 ? "" : "s"}, saved in this browser`),
          h("thead", null, h("tr", null, h("th", { scope: "col" }, "Question"), h("th", { scope: "col" }, "Records a correct answer must use"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
          h("tbody", null, evalState.cases.map((c, i) => h("tr", null,
            h("td", null, c.question),
            h("td", null, c.expected.map(titleOf).join("; ") || "—"),
            h("td", { class: "num" }, h("button", { class: "btn btn-quiet", type: "button", onclick: () => { evalState.cases.splice(i, 1); saveEvalCases(); drawCases(); } }, "Remove")))))))
      : empty("No benchmark questions", "Add a question and pick the records a good answer must retrieve, or use Add to benchmark from an investigation."));
  };

  const pendingPanel = () => {
    const p = evalState.pending;
    if (!p) return null;
    const boxes = p.candidates.map((c) => h("label", { class: "check" }, h("input", { type: "checkbox", value: c.id }), c.title));
    const panel = h("section", { class: "panel", "aria-labelledby": "pend-title" },
      h("div", { class: "panel-head" }, h("h2", { id: "pend-title" }, "Label a question from your investigation")),
      h("p", { class: "toolbar-note" }, `“${p.question}”. Tick only the records a correct answer must use. These labels are your judgement, so nothing is ticked for you.`),
      h("div", { class: "check-list" }, boxes),
      h("div", { class: "page-actions" },
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          const ids = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
          if (!ids.length) return toast("Tick at least one record, or discard the question", true);
          evalState.cases.push({ question: p.question, expected: ids });
          evalState.pending = null; saveEvalCases(); panel.remove(); drawCases();
          toast("Question added to the benchmark");
        } }, "Add labelled question"),
        h("button", { class: "btn", type: "button", onclick: () => { evalState.pending = null; panel.remove(); } }, "Discard")));
    return panel;
  };

  const kSel = h("select", { id: "e-k" }, [5, 10, 20].map((n) => h("option", { value: n, selected: n === 10 }, String(n))));
  const modeBoxes = h("fieldset", null, h("legend", null, "Compare"),
    h("div", { class: "toolbar" }, Object.entries(MODE_LABEL).map(([v, l]) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "emode", value: v, checked: v !== "agentic" }), l))));
  const run = h("button", { class: "btn btn-primary", type: "button" }, "Run benchmark");

  run.addEventListener("click", async () => {
    if (!evalState.cases.length) return toast("Add at least one question first", true);
    const modes = [...modeBoxes.querySelectorAll("input:checked")].map((i) => i.value);
    if (!modes.length) return toast("Choose at least one mode", true);
    busy(run, true);
    put(results, h("div", { class: "panel" }, h("p", null, "Running benchmark"), skeleton()));
    const r = await api("/evaluation/runs", { method: "POST", timeout: 120000, body: {
      cases: evalState.cases.map((c, i) => ({ case_id: `q-${String(i + 1).padStart(3, "0")}`, question: c.question, expected_memory_ids: c.expected })),
      modes, k: Number(kSel.value) } });
    busy(run, false);
    if (!r.ok) return put(results, notice("crit", "The benchmark didn't run", r.error));
    evalState.results = r.data;
    drawResults();
  });

  const download = (name, text, type) => {
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
    document.body.append(a); a.click(); a.remove();
  };

  const drawResults = () => {
    const res = evalState.results;
    if (!res) return put(results);
    const k = res.k;
    const unavailable = Object.entries(res.unavailable_modes || {});
    put(results,
      unavailable.length ? notice("warn", "Some modes didn't run", unavailable.map(([m, why]) => `${MODE_LABEL[m]}: ${why}.`).join(" ") + " They are reported as not measured, not as zero.", [navLink("Open System health", "system", {}, "btn")]) : null,
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", null, "Retrieval"), h("p", null, `${res.embedding_model}; mean over labelled questions`)),
        h("div", { class: "table-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Mode", "Recall at 5", `Recall at ${k}`, `MRR at ${k}`, "Cited sentences", "Latency p50"].map((c, i) => h("th", { scope: "col", class: i ? "num" : null }, c)))),
          h("tbody", null, res.modes_run.map((m) => {
            const v = res.per_mode[m];
            return h("tr", null,
              h("th", { scope: "row" }, MODE_LABEL[m]),
              h("td", { class: "num" }, v.recall_at_5 === null ? "—" : scoreBar(v.recall_at_5)),
              h("td", { class: "num" }, v.recall_at_k === null ? "—" : scoreBar(v.recall_at_k)),
              h("td", { class: "num" }, v.mrr === null ? "—" : scoreBar(v.mrr)),
              h("td", { class: "num" }, v.groundedness === null ? "Not applicable" : pct(v.groundedness)),
              h("td", { class: "num" }, `${num(v.latency_p50_ms, 0)} ms`));
          })))),
      ),
      h("section", { class: "panel" },
        h("div", { class: "panel-head" }, h("h2", null, "Per question")),
        h("div", { class: "table-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Question", "Mode", `Recall at ${k}`, "First relevant rank", h("span", { class: "visually-hidden" }, "Inspect")].map((c, i) => h("th", { scope: "col", class: i >= 2 && i < 4 ? "num" : null }, c)))),
          h("tbody", null, res.cases.map((c) => h("tr", null,
            h("td", null, c.question), h("td", null, MODE_LABEL[c.mode]),
            h("td", { class: "num" }, c.error ? "Error" : pct(c.recall_at_k)),
            h("td", { class: "num" }, c.error ? "—" : c.mrr ? String(Math.round(1 / c.mrr)) : `Not in top ${k}`),
            h("td", null, c.mode === "agentic" ? navLink("Open investigation", "investigate", { q: c.question }) : navLink("Open in Search", "search", { q: c.question, mode: c.mode })))))))),
      h("div", { class: "page-actions" },
        h("button", { class: "btn", type: "button", onclick: () => download(`aegisops-run-${res.run_id}.json`, JSON.stringify({ cases: evalState.cases, ...res }, null, 2), "application/json") }, "Download run (JSON)")),
    );
  };

  const exportJsonl = () => evalState.cases.map((c, i) => JSON.stringify({
    query_id: `q-${String(i + 1).padStart(3, "0")}`, query_text: c.question,
    fault_family: (items.find((m) => m.id === c.expected[0])?.asset_id || "unassigned"),
    relevant_memory_ids: c.expected, notes: "Labelled in the AegisOps console",
  })).join("\n") + "\n";

  put(main, head,
    !all.ok ? notice("crit", "Records can't be loaded", all.error) : null,
    pendingPanel(),
    h("div", { class: "grid grid-2" },
      h("form", { class: "panel", onsubmit: (e) => {
        e.preventDefault();
        const question = q.value.trim();
        if (!question) return q.focus();
        const ids = [...expected.selectedOptions].map((o) => o.value);
        if (!ids.length) return toast("Pick at least one record a correct answer must use", true);
        evalState.cases.push({ question, expected: ids });
        saveEvalCases(); q.value = ""; expected.selectedIndex = -1; drawCases(); q.focus();
      } },
        h("h2", null, "Add a question"),
        h("div", { class: "field" }, h("label", { for: "e-q" }, "Question"), q),
        h("div", { class: "field" }, h("label", { for: "e-exp" }, "Records a correct answer must use"), expected, h("small", null, "Hold Ctrl or ⌘ to choose several")),
        h("div", null, h("button", { class: "btn", type: "submit" }, "Add question"))),
      h("div", { class: "panel" },
        h("h2", null, "Run"),
        modeBoxes,
        h("div", { class: "toolbar" }, h("div", { class: "field" }, h("label", { for: "e-k" }, "Top k"), kSel), run),
        h("p", { class: "toolbar-note" }, "To record results for a report, export the questions and run the CLI benchmark against the full stack:"),
        h("pre", { class: "cmd" }, "python -m evals.run_benchmark --queries evals/queries.jsonl --k 10"),
        h("div", { class: "page-actions" },
          h("button", { class: "btn", type: "button", onclick: () => evalState.cases.length ? download("queries.jsonl", exportJsonl(), "application/x-ndjson") : toast("Add a question first", true) }, "Export queries.jsonl"))),
    ),
    h("section", { "aria-label": "Benchmark questions" }, caseList),
    results,
  );
  drawCases();
  drawResults();
}

/* ------------------------------------------------------------ system */

const METRIC_STATE = {
  AVAILABLE: ["Measured", "normal"],
  NOT_INSTRUMENTED: ["Not measured", "muted"],
  NOT_CONNECTED: ["Not connected", "warn"],
  DEGRADED: ["Degraded", "warn"],
};

function humanize(key) {
  const t = key.replace(/_/g, " ").replace(/\bllm\b/gi, "LLM").replace(/\bdb\b/gi, "database").replace(/\bapi\b/gi, "API");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function metricValue(m) {
  if (m.value === null || m.value === undefined) return m.detail || "—";
  const unit = { percent: "%", ms: " ms", seconds: " s", ratio: "", req_per_sec: " req/s", events_per_sec: " events/s" }[m.unit] ?? (m.unit ? ` ${m.unit}` : "");
  if (typeof m.value === "number") {
    if (m.unit === "ratio") return pct(m.value);
    return `${num(m.value, m.value < 10 ? 2 : 0)}${unit}`;
  }
  return String(m.value);
}

function metricTable(title, group, id) {
  const entries = Object.entries(group || {}).filter(([, v]) => v && typeof v === "object" && "status" in v);
  if (!entries.length) return null;
  return h("section", { class: "panel", id },
    h("h2", null, title),
    h("div", { class: "table-wrap" }, h("table", { class: "metric-table" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Measure"), h("th", { scope: "col" }, "Value"), h("th", { scope: "col" }, "State"))),
      h("tbody", null, entries.map(([k, v]) => {
        const [label, sev] = METRIC_STATE[v.status] || [v.status, "muted"];
        return h("tr", null, h("th", { scope: "row" }, humanize(k)), h("td", null, metricValue(v)), h("td", null, stateChip(label, sev)));
      })))));
}

async function viewSystem() {
  const head = pageHead("System health", "Which capabilities are available right now, what powers them, and how far behind the projections are. Unmeasured values are shown as such, never estimated.");
  put(main, head, skeleton());
  const [health, obs, proj] = await Promise.all([refreshHealth(), api("/system/observability"), api("/system/projection-metrics")]);
  const svc = health.services || {};
  const kafkaOn = health.integrations?.kafka_enabled;

  // What each dependency powers, so an outage maps directly to affected pages.
  const rows = [
    ["postgres", "PostgreSQL", "Canonical record store and outbox", [["Records", "memories"], ["Incidents", "incidents"], ["Investigate (keyword fallback)", "investigate"]]],
    ["qdrant", "Qdrant", "Vector projection", [["Search: Meaning", "search"], ["Investigate", "investigate"], ["Evaluation", "evaluation"]]],
    ["neo4j", "Neo4j", "Graph projection", [["Relationships", "graph"], ["Search: Relationships and Both", "search"], ["Investigate graph links", "investigate"]]],
    ["llm", "Answer model", "Writes investigation answers", [["Investigate", "investigate"]]],
  ];
  const svcTable = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", null, "Services and what they power"), h("button", { class: "btn", type: "button", onclick: () => render() }, "Check again")),
    health.status === "unreachable" ? notice("crit", "The API isn't answering", health.error) :
    h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Service", "Role", "State", "Powers", "Details"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", null,
        rows.map(([k, label, role, powers]) => {
          const v = svc[k] || {};
          const details = k === "llm"
            ? [v.provider && `Configured: ${v.provider} (${v.model})`, v.active_model && `In use: ${v.active_model}`, v.error].filter(Boolean).join(". ")
            : [v.url || v.uri, v.error, typeof v.retry_in_seconds === "number" ? `Next attempt in ${Math.ceil(v.retry_in_seconds)} s` : null].filter(Boolean).join(". ");
          return h("tr", null,
            h("th", { scope: "row" }, label), h("td", null, role),
            h("td", null, k === "llm" && v.synthetic ? stateChip("Test provider", "info") : serviceChip(v.status)),
            h("td", null, powers.map(([l, r], i) => [i ? ", " : "", h("a", { href: href(r) }, l)])),
            h("td", null, details || "—"));
        }),
        h("tr", null,
          h("th", { scope: "row" }, "Kafka"), h("td", null, "Outbound event stream for external systems"),
          h("td", null, kafkaOn ? stateChip("On", "normal") : stateChip("Off (optional)", "muted")),
          h("td", null, "No console page; projections don't depend on it"),
          h("td", null, kafkaOn ? "Outbox publisher sends every committed event" : "Start with: docker compose --profile integration up -d"))),
    )));

  const P = proj.ok ? proj.data : null;
  const O = obs.ok ? obs.data : null;
  put(main, head, svcTable,
    !proj.ok ? notice("crit", "Projection metrics unavailable", proj.error) : null,
    h("div", { class: "grid grid-metrics" },
      P ? metricTable("Projection outbox", P.kafka_outbox, "projection") : null,
      P ? metricTable("Qdrant projection", P.qdrant) : null,
      P ? metricTable("Neo4j projection", P.neo4j) : null,
      O ? metricTable("Investigations", O.investigations) : null,
      O ? metricTable("Retrieval", O.retrieval_runtime) : null,
      O ? metricTable("Answer model", O.llm) : null,
      O ? metricTable("Canonical storage", O.canonical_memory) : null,
      O ? metricTable("API runtime", O.api_runtime) : null),
    h("section", { class: "panel" }, h("details", { class: "raw" }, h("summary", null, "Show raw payloads"), h("pre", null, JSON.stringify({ health, observability: O, projection: P }, null, 2)))),
  );
}

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

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const resolved = ALIASES[path] || path;
  const name = ROUTES[resolved] ? resolved : "overview";
  return { name, params: new URLSearchParams(query || "") };
}

async function render() {
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
