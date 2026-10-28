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

const SOURCE_LABEL = { semantic: "Vector match", graph: "Graph link", hybrid: "Vector + graph", keyword: "Keyword match" };

function notice(kind, title, body, actions) {
  return h("div", { class: `notice notice-${kind}`, role: kind === "crit" ? "alert" : null },
    icon(kind === "crit" ? "crit" : kind === "warn" ? "warn" : "info"),
    h("div", null, h("strong", null, title), body ? h("p", null, body) : null),
    actions ? h("div", { class: "notice-actions" }, actions) : null,
  );
}

function empty(title, body, actions) {
  return h("div", { class: "empty" }, h("h3", null, title), h("p", null, body), actions || null);
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
    strip.append(h("li", null, stateChip("API unreachable", "crit")));
  } else {
    const svc = services();
    const names = [["postgres", "PostgreSQL"], ["qdrant", "Qdrant"], ["neo4j", "Neo4j"], ["llm", "Answer model"]];
    for (const [key, label] of names) {
      const st = svc[key]?.status;
      const [word, sev] = SERVICE_STATE[st] || ["Unknown", "muted"];
      let text = `${label}: ${word.toLowerCase()}`;
      if (key === "llm" && svc.llm?.synthetic) text = `${label}: test provider`;
      strip.append(h("li", null, stateChip(text, key === "llm" && svc.llm?.synthetic ? "info" : sev)));
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

/* ------------------------------------------------------- memory dialogs */

async function showMemory(id, { onChange } = {}) {
  openDialog("Loading record", skeleton());
  const r = await api(`/memories/${id}`);
  if (!r.ok) {
    openDialog("Record unavailable", notice("crit", "Couldn't load this record", r.error));
    return;
  }
  const m = r.data;
  const refresh = async (msg) => { toast(msg); closeDialog(); await refreshHealth(); onChange?.(); };

  const confirmArea = h("div", { class: "confirm" });
  const isActive = m.status === "active";

  const lifecycle = (action, verb, done) => {
    put(confirmArea, 
      notice("warn", `${verb} this record?`,
        action === "archive"
          ? "Archived records stay in PostgreSQL for audit but are excluded from search and answers."
          : "Disputed records stay visible here but are excluded from search and answers until resolved.",
        [
          h("button", { class: "btn btn-danger", type: "button", "data-autofocus": true, onclick: async (e) => {
            busy(e.currentTarget, true);
            const res = await api(`/memories/${m.id}/${action}`, { method: "POST", body: {} });
            busy(e.currentTarget, false);
            if (!res.ok) return toast(res.error, true);
            await refresh(done);
          } }, verb),
          h("button", { class: "btn", type: "button", onclick: () => put(confirmArea) }, "Keep as is"),
        ]),
    );
    confirmArea.querySelector("[data-autofocus]").focus();
  };

  const body = h("div", null,
    h("div", { class: "evidence-head" }, lifecycleChip(m.status), h("span", { class: "tag" }, typeLabel(m.memory_type)), m.is_synthetic ? h("span", { class: "tag" }, "Sample data") : null),
    h("p", { class: "record-body" }, m.content),
    h("dl", { class: "facts" },
      ...[
        ["Asset", m.asset_id], ["Facility", m.facility_id], ["Line or component", m.component_id], ["Incident", m.incident_id],
        ["Source", m.source_type], ["Observed", fmtWhen(m.observed_at)], ["Recorded", fmtWhen(m.created_at)],
        ["Confidence", pct(m.confidence)], ["Importance", pct(m.importance)],
        ["Supersedes", m.supersedes_memory_id ? h("code", null, m.supersedes_memory_id) : null],
        ["Record ID", h("code", null, m.id)],
      ].filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== "—").map(([k, v]) => [h("dt", null, k), h("dd", null, v)]),
    ),
    confirmArea,
  );

  const foot = [
    h("a", { class: "btn", href: `#/ask?anchor=${m.id}&q=${encodeURIComponent(`What else do we know about: ${m.title}?`)}`, onclick: closeDialog }, "Ask about this"),
    h("a", { class: "btn", href: `#/graph?anchor=${m.id}`, onclick: closeDialog }, "Show related"),
    h("span", { class: "spacer" }),
    isActive ? h("button", { class: "btn", type: "button", onclick: () => memoryForm({ supersede: m, onSaved: onChange }) }, "Supersede") : null,
    isActive ? h("button", { class: "btn btn-danger", type: "button", onclick: () => lifecycle("dispute", "Dispute", "Record marked disputed") }, "Dispute") : null,
    m.status !== "archived" && m.status !== "superseded" ? h("button", { class: "btn btn-danger", type: "button", onclick: () => lifecycle("archive", "Archive", "Record archived") }, "Archive") : null,
  ];
  openDialog(m.title, body, foot);
}

function memoryForm({ supersede = null, onSaved } = {}) {
  const base = supersede || {};
  const field = (name, label, input, hint) =>
    h("div", { class: `field${["content", "title"].includes(name) ? " span-2" : ""}` },
      h("label", { for: `f-${name}` }, label), input, hint ? h("small", { id: `f-${name}-hint` }, hint) : null,
      h("span", { class: "field-error", id: `f-${name}-err`, role: "alert" }));
  const text = (name, attrs = {}) => h("input", { type: "text", id: `f-${name}`, name, value: base[name] ?? "", ...attrs });

  const typeSelect = h("select", { id: "f-memory_type", name: "memory_type" },
    Object.entries(TYPE_LABEL).map(([v, l]) => h("option", { value: v, selected: (base.memory_type || "observation") === v }, l)));

  const form = h("form", { class: "form-grid", novalidate: true },
    field("memory_type", "Record type", typeSelect),
    field("source_type", "Source", text("source_type", { list: "source-types", required: true, value: base.source_type || "technician" }), "Who or what reported it"),
    field("title", "Title", text("title", { required: true, maxlength: 200 })),
    field("content", "What happened", h("textarea", { id: "f-content", name: "content", required: true, rows: 4 }, base.content || "")),
    field("asset_id", "Asset", text("asset_id", { placeholder: "e.g. robot-r17" })),
    field("facility_id", "Facility", text("facility_id")),
    field("component_id", "Line or component", text("component_id")),
    field("incident_id", "Incident", text("incident_id", { placeholder: "e.g. inc-2026-0042" })),
    field("observed_at", "Observed at", h("input", { type: "datetime-local", id: "f-observed_at", name: "observed_at" }), "Your local time"),
    field("confidence", "Confidence (0–1)", h("input", { type: "number", id: "f-confidence", name: "confidence", min: 0, max: 1, step: 0.01, value: base.confidence ?? 0.7 })),
    field("importance", "Importance (0–1)", h("input", { type: "number", id: "f-importance", name: "importance", min: 0, max: 1, step: 0.01, value: base.importance ?? 0.5 })),
    h("datalist", { id: "source-types" }, ["technician", "operator_report", "system", "manual", "sensor", "inspection"].map((v) => h("option", { value: v }))),
  );

  const submit = h("button", { class: "btn btn-primary", type: "button" }, supersede ? "Save replacement" : "Save record");
  submit.addEventListener("click", async () => {
    form.querySelectorAll(".field-error").forEach((e) => (e.textContent = ""));
    form.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
    const fd = new FormData(form);
    const payload = {};
    for (const [k, v] of fd.entries()) {
      const val = String(v).trim();
      if (val === "") continue;
      payload[k] = ["confidence", "importance"].includes(k) ? Number(val) : val;
    }
    if (payload.observed_at) payload.observed_at = new Date(payload.observed_at).toISOString();
    let invalid = null;
    for (const req of ["title", "content", "source_type"]) {
      if (!payload[req]) {
        const input = form.querySelector(`#f-${req}`);
        input.setAttribute("aria-invalid", "true");
        input.setAttribute("aria-describedby", `f-${req}-err`);
        form.querySelector(`#f-${req}-err`).textContent = "Required";
        invalid = invalid || input;
      }
    }
    for (const n of ["confidence", "importance"]) {
      if (payload[n] !== undefined && !(payload[n] >= 0 && payload[n] <= 1)) {
        const input = form.querySelector(`#f-${n}`);
        input.setAttribute("aria-invalid", "true");
        form.querySelector(`#f-${n}-err`).textContent = "Enter a number from 0 to 1";
        invalid = invalid || input;
      }
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
    onSaved?.();
  });

  openDialog(supersede ? `Supersede: ${supersede.title}` : "New record", h("div", null,
    supersede ? notice("info", "The original stays in history", "It will be marked superseded and linked to this replacement.") : null,
    form),
    [h("button", { class: "btn", type: "button", onclick: closeDialog }, "Cancel"), submit]);
}

/* ---------------------------------------------------------- sample data */

function sampleRecords() {
  const now = Date.now();
  const at = (hoursAgo) => new Date(now - hoursAgo * 3600e3).toISOString();
  const r17 = { asset_id: "robot-r17", facility_id: "west-assembly-plant", component_id: "body-shop-line-2", incident_id: "inc-2026-0042" };
  const c4 = { asset_id: "conveyor-c4", facility_id: "west-assembly-plant", component_id: "paint-shop-line-1", incident_id: "inc-2026-0057" };
  const p2 = { asset_id: "press-p2", facility_id: "north-stamping-plant", component_id: "stamping-line-3" };
  const rec = (memory_type, title, content, source_type, ctx, hoursAgo, confidence, importance) =>
    ({ memory_type, title, content, source_type, ...ctx, observed_at: at(hoursAgo), confidence, importance, is_synthetic: true, metadata: { sample: "aegisops-console" } });
  return [
    rec("incident", "Repeated servo fault on Robot R-17", "Robot R-17 triggered recurring servo axis faults during body panel transfer on Line 2.", "system", r17, 8, 0.82, 0.88),
    rec("observation", "Servo temperature rise on Robot R-17", "Servo temperature rose 18 °C above baseline after the third cycle batch.", "technician", r17, 7.3, 0.77, 0.72),
    rec("diagnosis", "Likely encoder cable fatigue on Robot R-17", "Intermittent signal loss on the encoder cable bundle near the axis bend radius.", "technician", r17, 6.75, 0.69, 0.81),
    rec("maintenance_action", "Re-terminated encoder connector on Robot R-17", "Re-terminated the connector, replaced the strain relief clamp, and added cable support.", "technician", r17, 5.8, 0.86, 0.74),
    rec("resolution", "Servo fault stable after harness repair", "No further servo faults across 240 cycles after the harness repair and connector rework.", "system", r17, 3.1, 0.9, 0.83),
    rec("recommendation", "Weekly cable bend inspection for Robot R-17", "Inspect servo cable bend radius and harness strain relief weekly.", "manual", r17, 4.3, 0.73, 0.79),
    rec("incident", "Conveyor C-4 belt slip at paint shop entry", "Conveyor C-4 stalled twice; carriers bunched at the paint shop entry and the line stopped for 11 minutes.", "operator_report", c4, 30, 0.8, 0.9),
    rec("observation", "Glazed drive pulley on Conveyor C-4", "Drive pulley lagging is glazed and belt tension reads 15% below spec.", "inspection", c4, 28, 0.84, 0.7),
    rec("diagnosis", "Belt tension loss on Conveyor C-4", "Belt stretch beyond the take-up range, worsened by the glazed lagging, causes slip under load.", "technician", c4, 26, 0.72, 0.8),
    rec("observation", "Hydraulic pressure drift on Press P-2", "Main ram pressure drifting 4% low during the second shift; no fault code yet.", "sensor", p2, 14, 0.66, 0.62),
    rec("recommendation", "Check accumulator pre-charge on Press P-2", "Verify the accumulator nitrogen pre-charge before the next planned stop.", "manual", p2, 12, 0.6, 0.58),
    rec("document_fact", "Press P-2 accumulator pre-charge spec", "OEM manual: accumulator pre-charge 90 bar ±5 at 20 °C; check every 500 operating hours.", "manual", p2, 200, 0.95, 0.5),
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

/* ============================================================== VIEWS */

/* ---------------------------------------------------------- overview */

async function viewOverview() {
  put(main, 
    pageHead("Plant overview", "What needs attention now, and whether the memory pipeline behind it is healthy."),
    h("div", { class: "panel schematic" }, skeleton()),
  );

  const [all, outbox] = await Promise.all([fetchAllMemories(), api("/system/outbox-stats")]);
  const svc = services();
  if (!all.ok) {
    add(main, notice("crit", "Records can't be loaded", all.error));
    return;
  }
  const items = all.items;
  const active = items.filter((m) => m.status === "active");
  const pending = outbox.ok ? outbox.data?.summary?.pending ?? 0 : null;
  const failed = outbox.ok ? outbox.data?.summary?.failed ?? 0 : null;

  // Incidents that are open: an incident record with no resolution in the same incident_id
  const resolved = new Set(items.filter((m) => m.memory_type === "resolution" && m.incident_id).map((m) => m.incident_id));
  const openIncidents = active
    .filter((m) => m.memory_type === "incident" && !(m.incident_id && resolved.has(m.incident_id)))
    .sort((a, b) => (b.importance - a.importance) || String(b.created_at).localeCompare(String(a.created_at)));

  put(main, 
    pageHead("Plant overview", "What needs attention now, and whether the memory pipeline behind it is healthy.",
      items.length ? [h("a", { class: "btn btn-primary", href: "#/ask" }, "Ask a question")] : null),
    schematic({ svc, total: items.length, active: active.length, pending, failed }),
    readouts([
      { label: "Open incidents", value: openIncidents.length, note: "Incident records without a resolution", sev: openIncidents.length ? "warn" : null },
      { label: "Active records", value: active.length, note: `${items.length - active.length} archived, disputed or superseded` },
      { label: "Waiting to project", value: pending, note: "Outbox events not yet in Qdrant or Neo4j", sev: pending > 0 ? "warn" : null },
      { label: "Failed projections", value: failed, note: "Gave up after retries; needs a look", sev: failed > 0 ? "crit" : null },
    ]),
  );

  if (!items.length) {
    add(main, h("div", { class: "panel", style: "margin-top:24px" }, empty("No operational records yet",
      "Record an incident or observation, or load a small labelled sample plant to explore the console.",
      h("div", { class: "page-actions", style: "justify-content:center" },
        h("button", { class: "btn btn-primary", type: "button", onclick: (e) => loadSampleData(e.currentTarget) }, "Load sample plant data"),
        h("button", { class: "btn", type: "button", onclick: () => memoryForm({ onSaved: render }) }, "Record an event")))));
    return;
  }

  const byType = {};
  for (const m of active) byType[m.memory_type] = (byType[m.memory_type] || 0) + 1;
  const recent = [...items].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, 6);

  add(main, 
    h("div", { class: "grid grid-main", style: "margin-top:24px" },
      h("section", { class: "panel", "aria-labelledby": "q-title" },
        h("div", { class: "panel-head" }, h("h2", { id: "q-title" }, "Incident queue"), h("p", null, "Highest importance first")),
        openIncidents.length
          ? h("ul", { class: "queue" }, openIncidents.slice(0, 6).map((m) => h("li", null, queueItem(m, [
              metaPair("Asset", m.asset_id), metaPair("Incident", m.incident_id), metaPair("Importance", pct(m.importance)), metaPair("Raised", fmtAgo(m.observed_at || m.created_at)),
            ]))))
          : empty("No open incidents", "Every incident record has a matching resolution."),
      ),
      h("section", { class: "panel", "aria-labelledby": "mix-title" },
        h("div", { class: "panel-head" }, h("h2", { id: "mix-title" }, "Active records by type")),
        barList(Object.entries(byType).sort((a, b) => b[1] - a[1]).map(([t, n]) => ({ label: typeLabel(t), value: n }))),
      ),
    ),
    h("section", { class: "panel", "aria-labelledby": "recent-title" },
      h("div", { class: "panel-head" }, h("h2", { id: "recent-title" }, "Latest activity"), h("a", { href: "#/memories" }, "All records")),
      h("ul", { class: "queue" }, recent.map((m) => h("li", null, queueItem(m, [
        h("span", { class: "tag" }, typeLabel(m.memory_type)), metaPair("Asset", m.asset_id), metaPair("Recorded", fmtAgo(m.created_at)),
      ], true)))),
    ),
  );
}

function queueItem(m, meta, showStatus = false) {
  return h("button", { class: "queue-item", type: "button", onclick: () => showMemory(m.id, { onChange: render }) },
    h("span", { class: "queue-title" }, m.title),
    showStatus ? lifecycleChip(m.status) : h("span"),
    h("span", { class: "queue-meta" }, meta),
  );
}

function readouts(list) {
  return h("dl", { class: "readouts" }, list.map((r) =>
    h("div", { class: `readout${r.sev ? ` is-${r.sev}` : ""}` },
      h("dt", null, r.label),
      h("dd", null, r.value === null || r.value === undefined ? "—" : num(r.value), h("span", { class: "readout-note" }, r.note)),
    )));
}

function barList(rows) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return h("ul", { class: "bars" }, rows.map((r) =>
    h("li", { class: "bar-row", title: `${r.label}: ${r.value}` },
      h("span", { class: "bar-label" }, r.label),
      h("span", { class: "bar-track", "aria-hidden": "true" }, h("span", { class: "bar-fill", style: `width:${(r.value / max) * 100}%` })),
      h("span", { class: "bar-value" }, num(r.value)),
    )));
}

/** Process schematic of the memory pipeline: the console's signature element. */
function schematic({ svc, total, active, pending, failed }) {
  const st = (name) => svc[name]?.status;
  const sev = (name) => {
    const v = st(name);
    if (v === "healthy") return "normal";
    if (v === "unhealthy") return "crit";
    return "warn";
  };
  const word = (name) => (SERVICE_STATE[st(name)] || ["Unknown"])[0];
  const llm = svc.llm || {};
  const llmSev = llm.status === "healthy" ? "normal" : "warn";

  const node = (x, y, w, name, role, value, stateText, severity, extra = "") => {
    const g = s("g", { class: `node is-${severity === "normal" ? "ok" : severity}${extra}`, transform: `translate(${x} ${y})` });
    g.append(
      s("rect", { width: w, height: 104, rx: 4 }),
      s("text", { class: "node-name", x: 14, y: 26 }, name),
      s("text", { class: "node-role", x: 14, y: 44 }, role),
      s("text", { class: "node-value", x: 14, y: 78 }, value),
      s("text", { class: "node-state", x: 14, y: 96 }, stateText),
    );
    return g;
  };
  const pipe = (d, ok = true, flow = true) => [
    s("path", { class: `pipe${ok ? "" : " pipe-broken"}`, d }),
    ok && flow ? s("path", { class: "pipe-flow", d }) : null,
  ];

  const qOk = st("qdrant") === "healthy";
  const nOk = st("neo4j") === "healthy";
  const pgSev = sev("postgres");

  const svg = s("svg", { viewBox: "0 0 1080 300", role: "img", "aria-labelledby": "sch-title sch-desc" },
    s("title", { id: "sch-title" }, "Memory pipeline"),
    s("desc", { id: "sch-desc" }, `PostgreSQL is ${word("postgres").toLowerCase()} with ${total} records. Outbox has ${pending ?? "unknown"} pending and ${failed ?? "unknown"} failed events. Qdrant is ${word("qdrant").toLowerCase()}. Neo4j is ${word("neo4j").toLowerCase()}. Answer model is ${llm.synthetic ? "the deterministic test provider" : word("llm").toLowerCase()}.`),
    ...pipe("M210 150 H290"),
    ...pipe("M470 150 H520 V70 H580", qOk),
    ...pipe("M470 150 H520 V230 H580", nOk),
    ...pipe("M760 70 H800 V150 H860", qOk),
    ...pipe("M760 230 H800 V150 H860", nOk),
    s("text", { class: "pipe-label", x: 214, y: 140 }, "commit"),
    s("text", { class: "pipe-label", x: 528, y: 62 }, "vectors"),
    s("text", { class: "pipe-label", x: 528, y: 252 }, "graph"),
    s("text", { class: "pipe-label", x: 810, y: 140 }, "cites"),
    node(20, 98, 190, "PostgreSQL", "Canonical record store", `${num(total)} records`, `${word("postgres")}, ${num(active)} active`, pgSev, " is-canonical"),
    node(290, 98, 180, "Outbox", "Projection queue", pending === null ? "—" : `${num(pending)} pending`, failed ? `${num(failed)} failed` : "No failures", failed ? "crit" : pending ? "warn" : "normal"),
    node(580, 18, 180, "Qdrant", "Vector projection", word("qdrant"), qOk ? "Semantic search on" : "Semantic search off", sev("qdrant")),
    node(580, 178, 180, "Neo4j", "Graph projection", word("neo4j"), nOk ? "Relationships on" : "Relationships off", sev("neo4j")),
    node(860, 98, 200, "Answers", "Evidence-grounded RAG", llm.synthetic ? "Test provider" : (SERVICE_STATE[llm.status] || ["Unknown"])[0], llm.active_model || llm.model || "", llm.synthetic ? "info" : llmSev),
  );

  const down = [!qOk && "Qdrant", !nOk && "Neo4j"].filter(Boolean);
  const caption = down.length
    ? `${down.join(" and ")} ${down.length > 1 ? "are" : "is"} unavailable. Records are still saved to PostgreSQL and queued in the outbox; the projection worker applies them once the store is back. Answers fall back to keyword matching in PostgreSQL meanwhile.`
    : "Every write lands in PostgreSQL first, then the outbox projects it into Qdrant for vector search and Neo4j for relationships. Answers cite only PostgreSQL records.";

  // Narrow screens get the same stages as a readable list instead of a tiny diagram.
  const stage = (name, role, value, label, severity) =>
    h("li", null, h("span", null, h("strong", null, name), h("span", { class: "cell-sub" }, `${role}: ${value}`)), stateChip(label, severity));
  const list = h("ol", { class: "pipeline-list", "aria-label": "Memory pipeline" },
    stage("PostgreSQL", "Canonical records", `${num(total)} records`, word("postgres"), pgSev),
    stage("Outbox", "Projection queue", pending === null ? "unknown" : `${num(pending)} pending`, failed ? `${num(failed)} failed` : pending ? "Backlog" : "Clear", failed ? "crit" : pending ? "warn" : "normal"),
    stage("Qdrant", "Vector projection", qOk ? "semantic search on" : "semantic search off", word("qdrant"), sev("qdrant")),
    stage("Neo4j", "Graph projection", nOk ? "relationships on" : "relationships off", word("neo4j"), sev("neo4j")),
    stage("Answers", "Evidence-grounded RAG", llm.active_model || llm.model || "unknown", llm.synthetic ? "Test provider" : (SERVICE_STATE[llm.status] || ["Unknown"])[0], llm.synthetic ? "info" : llmSev),
  );
  return h("figure", { class: "panel schematic schematic-figure" }, svg, list, h("figcaption", null, caption));
}

/* --------------------------------------------------------- incidents */

async function viewIncidents(params) {
  put(main, pageHead("Incidents", "Each incident with everything recorded against it, in the order it happened."), skeleton());
  const all = await fetchAllMemories();
  if (!all.ok) return add(main, notice("crit", "Records can't be loaded", all.error));

  const groups = new Map();
  for (const m of all.items) {
    if (!m.incident_id) continue;
    if (!groups.has(m.incident_id)) groups.set(m.incident_id, []);
    groups.get(m.incident_id).push(m);
  }
  const when = (m) => m.observed_at || m.created_at;
  const incidents = [...groups.entries()].map(([id, recs]) => {
    recs.sort((a, b) => String(when(a)).localeCompare(String(when(b))));
    const head = recs.find((r) => r.memory_type === "incident") || recs[0];
    const isResolved = recs.some((r) => r.memory_type === "resolution" && r.status === "active");
    return { id, recs, head, isResolved, last: when(recs[recs.length - 1]) };
  }).sort((a, b) => Number(a.isResolved) - Number(b.isResolved) || String(b.last).localeCompare(String(a.last)));

  put(main, pageHead("Incidents", "Each incident with everything recorded against it, in the order it happened.",
    [h("button", { class: "btn", type: "button", onclick: () => memoryForm({ onSaved: render }) }, "Record an event")]));

  if (!incidents.length) {
    add(main, empty("No incidents recorded", "Records with an incident ID are grouped here. Add one, or load the sample plant from the overview.",
      h("a", { class: "btn btn-primary", href: "#/overview" }, "Go to overview")));
    return;
  }

  const selectedId = params.get("id") && groups.has(params.get("id")) ? params.get("id") : incidents[0].id;
  const detail = h("section", { class: "panel", "aria-live": "polite" });

  const list = h("ul", { class: "incident-list", "aria-label": "Incidents" }, incidents.map((inc) =>
    h("li", null, h("button", {
      type: "button",
      "aria-pressed": inc.id === selectedId ? "true" : "false",
      onclick: (e) => {
        list.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", "false"));
        e.currentTarget.setAttribute("aria-pressed", "true");
        history.replaceState(null, "", `#/incidents?id=${encodeURIComponent(inc.id)}`);
        showIncident(inc);
      },
    },
      h("span", { class: "incident-id" }, inc.head.title),
      h("span", { class: "incident-sub" }, `${inc.id} on ${inc.head.asset_id || "unknown asset"}`),
      inc.isResolved ? stateChip("Resolved", "normal") : stateChip("Open", "warn"),
    ))));

  const showIncident = (inc) => {
    put(detail, 
      h("div", { class: "panel-head" },
        h("div", null, h("h2", null, inc.head.title), h("p", null, [inc.id, inc.head.asset_id, inc.head.facility_id].filter(Boolean).join(", "))),
        h("a", { class: "btn btn-primary", href: `#/ask?anchor=${inc.head.id}&q=${encodeURIComponent(`What caused ${inc.id} on ${inc.head.asset_id || "this asset"}, and what fixed it?`)}` }, "Ask about this incident"),
      ),
      h("ol", { class: "timeline" }, inc.recs.map((m) =>
        h("li", { class: `is-${m.memory_type}` },
          h("span", { class: "timeline-mark", "aria-hidden": "true" }, icon(m.memory_type === "incident" ? "warn" : m.memory_type === "resolution" ? "ok" : "info")),
          h("p", { class: "timeline-when" }, `${typeLabel(m.memory_type)}, ${fmtWhen(when(m))}`),
          h("h3", { class: "timeline-title" }, h("button", { type: "button", onclick: () => showMemory(m.id, { onChange: render }) }, m.title)),
          h("p", null, m.content),
          m.status !== "active" ? h("p", null, lifecycleChip(m.status)) : null,
        ))),
    );
  };

  showIncident(incidents.find((i) => i.id === selectedId));
  add(main, h("div", { class: "grid grid-split" }, h("div", null, list), detail));
}

/* ----------------------------------------------------------- records */

async function viewMemories(params) {
  const filters = {
    memory_type: params.get("type") || "",
    status: params.get("status") || "active",
    asset_id: params.get("asset") || "",
    facility_id: params.get("facility") || "",
    q: params.get("q") || "",
  };
  const pageSize = 25;
  let page = Number(params.get("page") || 1);

  put(main, pageHead("Records", "Every observation, incident, diagnosis and fix in canonical storage.", [
    h("button", { class: "btn", type: "button", onclick: (e) => loadSampleData(e.currentTarget) }, "Load sample data"),
    h("button", { class: "btn btn-primary", type: "button", onclick: () => memoryForm({ onSaved: render }) }, "New record"),
  ]));

  const all = await fetchAllMemories();
  if (!all.ok) return add(main, notice("crit", "Records can't be loaded", all.error));
  const items = all.items;
  const distinct = (k) => [...new Set(items.map((m) => m[k]).filter(Boolean))].sort();

  const select = (name, label, options, value) => h("div", { class: "field" },
    h("label", { for: `flt-${name}` }, label),
    h("select", { id: `flt-${name}`, name }, h("option", { value: "" }, "Any"), options.map(([v, l]) => h("option", { value: v, selected: v === value }, l))));

  const toolbar = h("form", { class: "toolbar", role: "search", "aria-label": "Filter records", onsubmit: (e) => e.preventDefault() },
    h("div", { class: "field field-grow" }, h("label", { for: "flt-q" }, "Find in title or text"),
      h("input", { type: "search", id: "flt-q", name: "q", value: filters.q, placeholder: "e.g. servo, glare, belt", "data-hotkey-target": true })),
    select("memory_type", "Type", Object.entries(TYPE_LABEL), filters.memory_type),
    select("status", "Status", Object.entries(LIFECYCLE).map(([k, [l]]) => [k, l]), filters.status),
    select("asset_id", "Asset", distinct("asset_id").map((v) => [v, v]), filters.asset_id),
    select("facility_id", "Facility", distinct("facility_id").map((v) => [v, v]), filters.facility_id),
  );

  const tableHost = h("div");
  add(main, toolbar, tableHost);

  const draw = () => {
    const q = filters.q.toLowerCase();
    const rows = items.filter((m) =>
      (!filters.memory_type || m.memory_type === filters.memory_type) &&
      (!filters.status || m.status === filters.status) &&
      (!filters.asset_id || m.asset_id === filters.asset_id) &&
      (!filters.facility_id || m.facility_id === filters.facility_id) &&
      (!q || `${m.title} ${m.content}`.toLowerCase().includes(q)))
      .sort((a, b) => String(b.observed_at || b.created_at).localeCompare(String(a.observed_at || a.created_at)));

    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    page = Math.min(Math.max(1, page), pages);
    const slice = rows.slice((page - 1) * pageSize, page * pageSize);

    if (!items.length) {
      put(tableHost, empty("No records yet", "Add the first record, or load the labelled sample plant.",
        h("button", { class: "btn btn-primary", type: "button", onclick: (e) => loadSampleData(e.currentTarget) }, "Load sample data")));
      return;
    }
    if (!rows.length) {
      put(tableHost, empty("Nothing matches these filters", "Clear a filter or set Status to Any to include archived and superseded records."));
      return;
    }
    const table = h("div", { class: "table-wrap" }, h("table", null,
      h("caption", null, `${rows.length} record${rows.length === 1 ? "" : "s"}. Select a row to open it.`),
      h("thead", null, h("tr", null, ["Record", "Type", "Status", "Asset", "Observed", "Confidence"].map((c, i) => h("th", { scope: "col", class: i === 5 ? "num" : null }, c)))),
      h("tbody", null, slice.map((m) => {
        const open = () => showMemory(m.id, { onChange: render });
        return h("tr", { class: "is-clickable", tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } } },
          h("td", null, h("span", { class: "cell-title" }, m.title), h("span", { class: "cell-sub" }, m.content.length > 120 ? `${m.content.slice(0, 120)}…` : m.content)),
          h("td", null, typeLabel(m.memory_type)),
          h("td", null, lifecycleChip(m.status)),
          h("td", null, m.asset_id || "—"),
          h("td", null, fmtWhen(m.observed_at || m.created_at)),
          h("td", { class: "num" }, pct(m.confidence)));
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
    const t = e.target;
    filters[t.name] = t.value;
    page = 1;
    const p = new URLSearchParams();
    if (filters.memory_type) p.set("type", filters.memory_type);
    p.set("status", filters.status);
    if (filters.asset_id) p.set("asset", filters.asset_id);
    if (filters.facility_id) p.set("facility", filters.facility_id);
    if (filters.q) p.set("q", filters.q);
    history.replaceState(null, "", `#/memories?${p}`);
    draw();
  });
  draw();
}

/* --------------------------------------------------------------- ask */

async function viewAsk(params) {
  const anchor = params.get("anchor") || "";
  const q = params.get("q") || "";
  const svc = services();
  const out = h("div", { "aria-live": "polite" });

  const question = h("textarea", { id: "ask-q", name: "question", rows: 3, required: true, placeholder: "e.g. Why does Robot R-17 keep faulting, and what fixed it last time?" }, q);
  const limit = h("select", { id: "ask-limit" }, [3, 5, 8, 10].map((n) => h("option", { value: n, selected: n === 5 }, `${n} records`)));
  const askBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Get answer");

  const form = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault();
    const text = question.value.trim();
    if (!text) { question.setAttribute("aria-invalid", "true"); question.focus(); return; }
    question.removeAttribute("aria-invalid");
    busy(askBtn, true);
    put(out, h("div", { class: "panel", style: "margin-top:24px" }, skeleton()));
    const r = await api("/graphrag/query", { method: "POST", timeout: 60000, body: { question: text, context_limit: Number(limit.value), anchor_memory_id: anchor || null } });
    busy(askBtn, false);
    if (!r.ok) return put(out, notice("crit", "No answer", r.error));
    put(out, renderAnswer(r.data));
  } },
    h("div", { class: "field" }, h("label", { for: "ask-q" }, "Your question"), question),
    h("div", { class: "toolbar", style: "margin:16px 0 0" },
      h("div", { class: "field" }, h("label", { for: "ask-limit" }, "Use up to"), limit),
      anchor ? h("p", { class: "field-grow", style: "align-self:center" }, "Starting from record ", h("code", null, shortId(anchor)), " ", h("a", { href: "#/ask" }, "Clear")) : h("span", { class: "field-grow" }),
      askBtn),
  );

  const warnings = [];
  if (!capable("qdrant") && !capable("neo4j")) {
    warnings.push(notice("warn", "Vector and graph search are offline", "Answers will use keyword matches from PostgreSQL until Qdrant or Neo4j is back."));
  }
  if (svc.llm?.synthetic) {
    warnings.push(notice("info", "Answers come from the deterministic test provider", "They show which records were retrieved but aren't written by a language model. Set LLM_PROVIDER=openai and OPENAI_API_KEY to enable model answers."));
  }

  put(main, pageHead("Ask AegisOps", "Answers cite the canonical records they're based on, and say so when the evidence is thin."), ...warnings, form, out);
  if (q) form.requestSubmit(); else question.focus();
}

function renderAnswer(d) {
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

  const modeNote = d.retrieval_mode === "keyword_fallback"
    ? notice("warn", "Matched by keywords", "Vector and graph stores didn't return candidates, so these records were matched by words in PostgreSQL. Treat the ranking as approximate.")
    : null;

  return h("div", { class: "grid grid-main", style: "margin-top:24px" },
    h("section", { class: "panel", "aria-labelledby": "ans-title" },
      h("div", { class: "panel-head" }, h("h2", { id: "ans-title" }, "Answer"), d.is_synthetic_response ? stateChip("Test provider", "info") : h("span", { class: "tag" }, d.model_name)),
      modeNote,
      h("p", { class: "answer" }, parts),
      h("div", { class: "latency" },
        h("span", null, h("strong", null, num(d.retrieval_latency_ms, 0)), "ms retrieval"),
        h("span", null, h("strong", null, num(d.generation_latency_ms, 0)), "ms generation"),
        h("span", null, h("strong", null, num(d.total_latency_ms, 0)), "ms total")),
    ),
    h("section", { class: "panel", "aria-labelledby": "ev-title" },
      h("div", { class: "panel-head" }, h("h2", { id: "ev-title" }, "Evidence"), h("p", null, `${d.evidence_count} record${d.evidence_count === 1 ? "" : "s"}`)),
      d.evidence.length
        ? h("ol", { class: "evidence" }, d.evidence.map((e, i) => h("li", { id: `ev-${i + 1}`, tabindex: "-1" },
            h("div", { class: "evidence-head" },
              h("span", { class: "evidence-n" }, `Record ${i + 1}`),
              h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(e.memory_id) }, e.title)),
            h("p", null, e.content_preview),
            h("div", { class: "queue-meta", style: "margin-top:8px" },
              h("span", { class: "tag" }, typeLabel(e.memory_type)),
              h("span", { class: "tag" }, SOURCE_LABEL[e.retrieval_source] || e.retrieval_source),
              metaPair("Asset", e.asset_id), metaPair("Confidence", pct(e.confidence))))))
        : empty("No supporting records", "Nothing in canonical storage matched. Rephrase with an asset name or symptom, or add the record that's missing."),
    ),
  );
}

/* ------------------------------------------------------------ search */

async function viewSearch(params) {
  const mode = params.get("mode") || "hybrid";
  const out = h("div", { "aria-live": "polite" });
  const query = h("input", { type: "search", id: "s-q", name: "query", value: params.get("q") || "", placeholder: "Describe a symptom, part or fix", required: true });
  const modes = [["semantic", "Meaning"], ["graph", "Relationships"], ["hybrid", "Both"]];
  const seg = h("fieldset", null, h("legend", null, "Match by"),
    h("div", { class: "segmented" }, modes.map(([v, l]) => h("label", null,
      h("input", { type: "radio", name: "mode", value: v, checked: v === mode }), h("span", null, l)))));
  const inactive = h("label", { class: "check" }, h("input", { type: "checkbox", name: "inactive" }), "Include archived and disputed");
  const go = h("button", { class: "btn btn-primary", type: "submit" }, "Search");

  const form = h("form", { class: "panel", role: "search", onsubmit: async (e) => {
    e.preventDefault();
    const text = query.value.trim();
    if (!text) return query.focus();
    const m = form.querySelector("input[name=mode]:checked").value;
    history.replaceState(null, "", `#/search?mode=${m}&q=${encodeURIComponent(text)}`);
    busy(go, true);
    const r = await api("/search/hybrid", { method: "POST", body: { query: text, mode: m, limit: 20, include_inactive: inactive.querySelector("input").checked } });
    busy(go, false);
    if (!r.ok) {
      return put(out, notice(r.status === 503 ? "warn" : "crit", r.status === 503 ? "This search mode is offline" : "Search failed", r.error,
        r.status === 503 ? [h("a", { class: "btn", href: "#/system" }, "Open System health"), h("a", { class: "btn", href: `#/memories?status=active&q=${encodeURIComponent(text)}` }, "Find by text in Records")] : null));
    }
    const res = r.data.results || [];
    put(out, res.length
      ? h("div", { class: "table-wrap", style: "margin-top:24px" }, h("table", null,
          h("caption", null, `${res.length} result${res.length === 1 ? "" : "s"} in ${num(r.data.latency_ms, 0)} ms`),
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
      : h("div", { style: "margin-top:24px" }, empty("No matches", "Try different words, switch to Both, or include archived records.")));
  } },
    h("div", { class: "toolbar", style: "margin:0" },
      h("div", { class: "field field-grow" }, h("label", { for: "s-q" }, "Search for"), query),
      seg, inactive, go));

  const notes = [];
  if (!capable("qdrant")) notes.push(notice("warn", "Meaning search is offline", "Qdrant is unavailable, so only relationship search can run."));
  if (!capable("neo4j")) notes.push(notice("warn", "Relationship search is offline", "Neo4j is unavailable, so only meaning search can run."));
  const emb = state.health?.embedding_provider;
  if (capable("qdrant") && emb && !emb.semantic) {
    notes.push(emb.name === "HashedTermEmbedding"
      ? notice("info", "Similarity is based on shared words", "The term-hashing embedding ranks records that use the same words as your query. Synonyms won't match until a semantic embedding model is configured.")
      : notice("info", "Similarity scores are test values", "The default test embedding hashes whole texts, so scores don't reflect meaning. Set EMBEDDING_PROVIDER=hashed_terms for word-based ranking, or configure a semantic model."));
  }

  put(main, pageHead("Search", "Find records by meaning, by their links to the same asset or incident, or both."), ...notes, form, out);
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
  put(main, pageHead("Relationships", "Records linked to one record through a shared asset, line, incident, source or supersession."), skeleton());
  const all = await fetchAllMemories();
  if (!all.ok) return add(main, notice("crit", "Records can't be loaded", all.error));
  const items = all.items;
  const byId = new Map(items.map((m) => [m.id, m]));
  const anchorId = params.get("anchor") && byId.has(params.get("anchor")) ? params.get("anchor") : (items.find((m) => m.memory_type === "incident") || items[0])?.id;

  const head = pageHead("Relationships", "Records linked to one record through a shared asset, line, incident, source or supersession.");
  if (!items.length) {
    put(main, head, empty("No records to connect", "Load the sample plant from the overview to see relationships.", h("a", { class: "btn btn-primary", href: "#/overview" }, "Go to overview")));
    return;
  }

  const picker = h("select", { id: "g-anchor" }, items.slice().sort((a, b) => a.title.localeCompare(b.title)).map((m) => h("option", { value: m.id, selected: m.id === anchorId }, `${m.title} (${typeLabel(m.memory_type)})`)));
  const hops = h("select", { id: "g-hops" }, [1, 2, 3].map((n) => h("option", { value: n, selected: n === Number(params.get("hops") || 2) }, `${n} step${n > 1 ? "s" : ""}`)));
  const out = h("div", { "aria-live": "polite", style: "margin-top:24px" });

  const run = async () => {
    history.replaceState(null, "", `#/graph?anchor=${picker.value}&hops=${hops.value}`);
    put(out, skeleton());
    const r = await api("/search/graph-related", { method: "POST", body: { memory_id: picker.value, max_hops: Number(hops.value), limit: 40 } });
    if (!r.ok) {
      return put(out, notice(r.status === 503 ? "warn" : "crit", r.status === 503 ? "Relationship store is offline" : "Couldn't load relationships", r.error,
        [h("a", { class: "btn", href: "#/system" }, "Open System health")]));
    }
    const related = (r.data.related_memory_ids || []).map((id) => byId.get(id) || { id, title: shortId(id), memory_type: "unknown", status: "unknown" });
    put(out, drawGraph(byId.get(picker.value), related));
  };

  const form = h("form", { class: "panel toolbar", onsubmit: (e) => { e.preventDefault(); run(); } },
    h("div", { class: "field field-grow" }, h("label", { for: "g-anchor" }, "Start from"), picker),
    h("div", { class: "field" }, h("label", { for: "g-hops" }, "Reach"), hops),
    h("button", { class: "btn btn-primary", type: "submit" }, "Show links"));

  put(main, head, !capable("neo4j") ? notice("warn", "Relationship store is offline", "Neo4j is unavailable. Links appear once it reconnects and the projection worker catches up.") : null, form, out);
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

  const table = h("div", { class: "table-wrap", style: "margin-top:16px" }, h("table", null,
    h("caption", null, "Linked records as a table"),
    h("thead", null, h("tr", null, ["Record", "Type", "Status", "Asset", "Incident"].map((c) => h("th", { scope: "col" }, c)))),
    h("tbody", null, related.map((m) => h("tr", null,
      h("td", null, h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(m.id) }, m.title)),
      h("td", null, typeLabel(m.memory_type)), h("td", null, lifecycleChip(m.status)), h("td", null, m.asset_id || "—"), h("td", null, m.incident_id || "—"))))));
  return h("div", null, svg, table);
}

/* -------------------------------------------------------- evaluation */

const evalState = { cases: [], results: null };

function recallAtK(ret, exp, k) { if (!exp.length) return 1; const top = new Set(ret.slice(0, k)); return exp.filter((e) => top.has(e)).length / exp.length; }
function mrr(ret, exp) { const set = new Set(exp); for (let i = 0; i < ret.length; i++) if (set.has(ret[i])) return 1 / (i + 1); return 0; }
function groundedness(answer) {
  const sentences = answer.split(/[.!?]+/).map((x) => x.trim()).filter((x) => x.length > 30);
  if (!sentences.length) return 1;
  return sentences.filter((x) => /\[Memory\s+\d+\]/.test(x)).length / sentences.length;
}
function citationAccuracy(answer, n) {
  if (!n) return 1;
  const refs = [...answer.matchAll(/\[Memory\s+(\d+)\]/g)].map((m) => Number(m[1]));
  if (!refs.length) return 1;
  return refs.filter((r) => r >= 1 && r <= n).length / refs.length;
}

async function viewEvaluation() {
  const all = await fetchAllMemories({ status: "active" });
  const items = all.items || [];

  const caseList = h("div");
  const results = h("div", { "aria-live": "polite" });
  const q = h("input", { type: "text", id: "e-q", placeholder: "e.g. What fixed the Robot R-17 servo fault?" });
  const expected = h("select", { id: "e-exp", multiple: true, size: 5 }, items.map((m) => h("option", { value: m.id }, m.title)));

  const drawCases = () => {
    put(caseList, evalState.cases.length
      ? h("div", { class: "table-wrap" }, h("table", null,
          h("caption", null, `${evalState.cases.length} benchmark question${evalState.cases.length === 1 ? "" : "s"}`),
          h("thead", null, h("tr", null, h("th", { scope: "col" }, "Question"), h("th", { scope: "col" }, "Expected records"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Remove")))),
          h("tbody", null, evalState.cases.map((c, i) => h("tr", null,
            h("td", null, c.question),
            h("td", null, c.expected.map((id) => items.find((m) => m.id === id)?.title || shortId(id)).join("; ") || "—"),
            h("td", { class: "num" }, h("button", { class: "btn btn-quiet", type: "button", onclick: () => { evalState.cases.splice(i, 1); drawCases(); } }, "Remove")))))))
      : empty("No benchmark questions", "Add a question and pick the records a good answer must retrieve."));
  };

  const run = h("button", { class: "btn btn-primary", type: "button" }, "Run benchmark");
  const modeBoxes = h("fieldset", null, h("legend", null, "Compare"),
    h("div", { class: "toolbar", style: "margin:0" }, [["semantic", "Meaning"], ["graph", "Relationships"], ["hybrid", "Both"]].map(([v, l]) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "emode", value: v, checked: true }), l))));

  run.addEventListener("click", async () => {
    if (!evalState.cases.length) return toast("Add at least one question first", true);
    const modes = [...modeBoxes.querySelectorAll("input:checked")].map((i) => i.value);
    if (!modes.length) return toast("Choose at least one retrieval mode", true);
    busy(run, true);
    const prog = h("progress", { max: evalState.cases.length * (modes.length + 1), value: 0, "aria-label": "Benchmark progress" });
    put(results, h("div", { class: "panel", style: "margin-top:24px" }, h("p", null, "Running benchmark"), prog));
    const rows = [], answers = [], unavailable = new Set();
    for (const c of evalState.cases) {
      for (const mode of modes) {
        const r = await api("/search/hybrid", { method: "POST", body: { query: c.question, mode, limit: 10, graph_hops: 2 } });
        prog.value += 1;
        if (!r.ok) { unavailable.add(`${mode}: ${r.error}`); continue; }
        const ids = (r.data.results || []).map((x) => x.memory_id);
        rows.push({ mode, r5: recallAtK(ids, c.expected, 5), r10: recallAtK(ids, c.expected, 10), mrr: mrr(ids, c.expected), ms: r.data.latency_ms });
      }
      const g = await api("/graphrag/query", { method: "POST", timeout: 60000, body: { question: c.question, context_limit: 5 } });
      prog.value += 1;
      if (g.ok) {
        const ids = g.data.evidence.map((e) => e.memory_id);
        answers.push({ question: c.question, recall: recallAtK(ids, c.expected, 5), grounded: groundedness(g.data.answer), cites: citationAccuracy(g.data.answer, g.data.evidence_count), ms: g.data.total_latency_ms, synthetic: g.data.is_synthetic_response, mode: g.data.retrieval_mode });
      }
    }
    busy(run, false);
    evalState.results = { rows, answers, unavailable: [...unavailable], ranAt: new Date().toISOString() };
    drawResults();
  });

  const drawResults = () => {
    const res = evalState.results;
    if (!res) return put(results);
    const byMode = {};
    for (const r of res.rows) (byMode[r.mode] ||= []).push(r);
    const mean = (arr, k) => arr.reduce((a, b) => a + (b[k] || 0), 0) / arr.length;
    const synthetic = res.answers.some((a) => a.synthetic);
    put(results, 
      h("div", { style: "margin-top:24px" },
        res.unavailable.length ? notice("warn", "Some modes didn't run", res.unavailable.join(" ")) : null,
        Object.keys(byMode).length ? h("section", { class: "panel" },
          h("div", { class: "panel-head" }, h("h2", null, "Retrieval"), h("p", null, `Mean over ${evalState.cases.length} question${evalState.cases.length === 1 ? "" : "s"}`)),
          h("div", { class: "table-wrap" }, h("table", null,
            h("thead", null, h("tr", null, ["Mode", "Recall at 5", "Recall at 10", "Mean reciprocal rank", "Latency"].map((c, i) => h("th", { scope: "col", class: i ? "num" : null }, c)))),
            h("tbody", null, Object.entries(byMode).map(([m, arr]) => h("tr", null,
              h("th", { scope: "row" }, { semantic: "Meaning", graph: "Relationships", hybrid: "Both" }[m]),
              h("td", { class: "num" }, scoreBar(mean(arr, "r5"))),
              h("td", { class: "num" }, scoreBar(mean(arr, "r10"))),
              h("td", { class: "num" }, scoreBar(mean(arr, "mrr"))),
              h("td", { class: "num" }, `${num(mean(arr, "ms"), 0)} ms`))))))) : null,
        res.answers.length ? h("section", { class: "panel" },
          h("div", { class: "panel-head" }, h("h2", null, "Answers"), synthetic ? stateChip("Test provider", "info") : null),
          synthetic ? notice("info", "Answer-quality scores aren't meaningful yet", "The test provider doesn't write citations. Recall of evidence is still a real measure of retrieval.") : null,
          h("div", { class: "table-wrap" }, h("table", null,
            h("thead", null, h("tr", null, ["Question", "Evidence recall", "Cited sentences", "Valid citations", "Latency"].map((c, i) => h("th", { scope: "col", class: i ? "num" : null }, c)))),
            h("tbody", null, res.answers.map((a) => h("tr", null,
              h("td", null, a.question, a.mode === "keyword_fallback" ? h("span", { class: "cell-sub" }, "Keyword fallback") : null),
              h("td", { class: "num" }, pct(a.recall)), h("td", { class: "num" }, pct(a.grounded)), h("td", { class: "num" }, pct(a.cites)), h("td", { class: "num" }, `${num(a.ms, 0)} ms`))))))) : null,
        h("p", { style: "margin-top:16px" }, h("button", { class: "btn", type: "button", onclick: () => {
          const blob = new Blob([JSON.stringify({ cases: evalState.cases, ...evalState.results }, null, 2)], { type: "application/json" });
          const a = h("a", { href: URL.createObjectURL(blob), download: `aegisops-benchmark-${Date.now()}.json` });
          document.body.append(a); a.click(); a.remove();
        } }, "Download results (JSON)")),
      ),
    );
  };

  put(main, 
    pageHead("Evaluation", "Measure whether retrieval finds the records a correct answer needs. Results come only from runs you start here."),
    !all.ok ? notice("crit", "Records can't be loaded", all.error) : null,
    h("div", { class: "grid grid-2" },
      h("form", { class: "panel", onsubmit: (e) => {
        e.preventDefault();
        const question = q.value.trim();
        if (!question) return q.focus();
        evalState.cases.push({ question, expected: [...expected.selectedOptions].map((o) => o.value) });
        q.value = ""; expected.selectedIndex = -1; drawCases(); q.focus();
      } },
        h("h2", null, "Add a question"),
        h("div", { class: "field", style: "margin-top:16px" }, h("label", { for: "e-q" }, "Question"), q),
        h("div", { class: "field", style: "margin-top:16px" }, h("label", { for: "e-exp" }, "Records a correct answer must use"), expected, h("small", null, "Hold Ctrl or ⌘ to choose several")),
        h("button", { class: "btn", type: "submit", style: "margin-top:16px" }, "Add question")),
      h("div", { class: "panel" }, h("h2", null, "Run"), h("div", { style: "margin:16px 0" }, modeBoxes), run),
    ),
    h("section", { style: "margin-top:24px" }, caseList),
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
  const s2 = key.replace(/_/g, " ").replace(/\bp(50|95)\b/g, "p$1").replace(/\bllm\b/gi, "LLM").replace(/\bdb\b/gi, "database").replace(/\bapi\b/gi, "API");
  return s2.charAt(0).toUpperCase() + s2.slice(1);
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

function metricTable(title, group) {
  const entries = Object.entries(group || {}).filter(([, v]) => v && typeof v === "object" && "status" in v);
  if (!entries.length) return null;
  return h("section", { class: "panel" },
    h("h2", null, title),
    h("div", { class: "table-wrap" }, h("table", { class: "metric-table" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Measure"), h("th", { scope: "col" }, "Value"), h("th", { scope: "col" }, "State"))),
      h("tbody", null, entries.map(([k, v]) => {
        const [label, sev] = METRIC_STATE[v.status] || [v.status, "muted"];
        return h("tr", null, h("th", { scope: "row" }, humanize(k)), h("td", null, metricValue(v)), h("td", null, stateChip(label, sev)));
      })))));
}

async function viewSystem() {
  put(main, pageHead("System health", "Service state, projection backlog and runtime measures. Unmeasured values are shown as such, never estimated."), skeleton());
  const [health, obs, proj] = await Promise.all([refreshHealth(), api("/system/observability"), api("/system/projection-metrics")]);
  const svc = health.services || {};

  const svcRows = [["postgres", "PostgreSQL", "Canonical record store"], ["qdrant", "Qdrant", "Vector projection"], ["neo4j", "Neo4j", "Graph projection"], ["llm", "Answer model", "GraphRAG generation"]];
  const svcTable = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", null, "Services"),
      h("button", { class: "btn", type: "button", onclick: () => render() }, "Check again")),
    health.status === "unreachable" ? notice("crit", "The API isn't answering", health.error) :
    h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Service", "Role", "State", "Details"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", null, svcRows.map(([k, label, role]) => {
        const v = svc[k] || {};
        const details = k === "llm"
          ? [v.provider && `Configured: ${v.provider} (${v.model})`, v.active_model && `In use: ${v.active_model}`, v.error].filter(Boolean).join(". ")
          : [v.url || v.uri, v.error, typeof v.retry_in_seconds === "number" ? `Next attempt in ${Math.ceil(v.retry_in_seconds)} s` : null].filter(Boolean).join(". ");
        return h("tr", null, h("th", { scope: "row" }, label), h("td", null, role), h("td", null, k === "llm" && v.synthetic ? stateChip("Test provider", "info") : serviceChip(v.status)), h("td", null, details || "—"));
      })))));

  const P = proj.ok ? proj.data : null;
  const O = obs.ok ? obs.data : null;
  put(main, 
    pageHead("System health", "Service state, projection backlog and runtime measures. Unmeasured values are shown as such, never estimated."),
    svcTable,
    !proj.ok ? notice("crit", "Projection metrics unavailable", proj.error) : null,
    h("div", { class: "grid grid-metrics", style: "margin-top:24px" },
      P ? metricTable("Outbox and Kafka", P.kafka_outbox) : null,
      P ? metricTable("Qdrant projection", P.qdrant) : null,
      P ? metricTable("Neo4j projection", P.neo4j) : null,
      O ? metricTable("API runtime", O.api_runtime) : null,
      O ? metricTable("Canonical storage", O.canonical_memory) : null,
      O ? metricTable("Retrieval", O.retrieval_runtime) : null,
      O ? metricTable("Language model", O.llm_runtime) : null,
      O ? metricTable("Sensor ingestion", O.scalar_sensor_ingestion) : null),
    h("section", { class: "panel" }, h("details", { class: "raw" }, h("summary", null, "Show raw payloads"), h("pre", null, JSON.stringify({ health, observability: O, projection: P }, null, 2)))),
  );
}

/* ------------------------------------------------------------ router */

const ROUTES = {
  overview: { title: "Plant overview", view: viewOverview },
  incidents: { title: "Incidents", view: viewIncidents },
  memories: { title: "Records", view: viewMemories },
  ask: { title: "Ask AegisOps", view: viewAsk },
  search: { title: "Search", view: viewSearch },
  graph: { title: "Relationships", view: viewGraph },
  evaluation: { title: "Evaluation", view: viewEvaluation },
  system: { title: "System health", view: viewSystem },
};

let renderToken = 0;
let lastRoute = null;

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, query] = raw.split("?");
  const name = ROUTES[path] ? path : "overview";
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
    if (parseHash().name !== "memories") location.hash = "#/memories";
    setTimeout(() => document.getElementById("flt-q")?.focus(), 50);
  } else if (e.key === "?") {
    openDialog("Keyboard shortcuts", h("dl", { class: "shortcut-list" },
      [["/", "Find in records"], ["g then o", "Plant overview"], ["g then i", "Incidents"], ["g then r", "Records"], ["g then a", "Ask AegisOps"], ["g then s", "System health"], ["n", "New record"], ["Esc", "Close a dialog"]]
        .map(([k, d]) => [h("dt", null, h("kbd", null, k)), h("dd", null, d)])));
  } else if (e.key === "n") {
    memoryForm({ onSaved: render });
  } else if (e.key === "g") {
    const once = (ev) => {
      const map = { o: "overview", i: "incidents", r: "memories", a: "ask", s: "system", e: "evaluation", l: "graph" };
      if (map[ev.key]) location.hash = `#/${map[ev.key]}`;
    };
    document.addEventListener("keydown", once, { once: true });
  }
});

setInterval(() => { if (!document.hidden) refreshHealth(); }, 20000);
render();
