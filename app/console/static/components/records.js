import { closeDialog, openDialog } from "./dialog.js";
import { TYPE_LABEL, busy, empty, fmtWhen, lifecycleChip, notice, pct, shortId, skeleton, stateChip, toast, typeLabel } from "./ui.js";
import { render } from "../console.js";
import { api, fetchAllMemories, showSignIn } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { navLink, refreshHealth } from "../lib/state.js";

/* ------------------------------------------------------- record dialogs */

export async function showMemory(id, { onChange } = {}) {
  openDialog("Loading record", skeleton(), null, { drawer: true });
  const r = await api(`/memories/${id}`);
  if (!r.ok) {
    openDialog("Record unavailable", notice("crit", "Couldn't load this record", r.error), null, { drawer: true });
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
            if (res.status === 401) showSignIn();
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
      m.source_type === "investigation" ? stateChip("Confirmed finding", "normal") : null,
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
  openDialog(m.title, body, foot, { drawer: true });
}

/** Evidence list for a finding; titles are filled in as they load. */
export function basedOnList(ids) {
  const list = h("ul", { class: "based-on" }, ids.map((eid) => {
    const btn = h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(eid) }, `record ${shortId(eid)}`);
    api(`/memories/${eid}`).then((r) => { if (r.ok) btn.textContent = r.data.title; });
    return h("li", null, btn);
  }));
  return list;
}

export function formField(name, label, input, hint, wide = false) {
  return h("div", { class: `field${wide ? " span-2" : ""}` },
    h("label", { for: `f-${name}` }, label), input,
    hint ? h("small", { id: `f-${name}-hint` }, hint) : null,
    h("span", { class: "field-error", id: `f-${name}-err`, role: "alert" }));
}

export function markInvalid(form, name, message) {
  const input = form.querySelector(`#f-${name}`);
  input.setAttribute("aria-invalid", "true");
  input.setAttribute("aria-describedby", `f-${name}-err`);
  form.querySelector(`#f-${name}-err`).textContent = message;
  return input;
}

export function clearInvalid(form) {
  form.querySelectorAll(".field-error").forEach((e) => (e.textContent = ""));
  form.querySelectorAll("[aria-invalid]").forEach((e) => e.removeAttribute("aria-invalid"));
}

/** New record, a record added to an existing incident (defaults), or a supersession. */
export function memoryForm({ supersede = null, defaults = {}, title = null, onSaved } = {}) {
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
    if (res.status === 401) showSignIn();
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
export function sampleRecords() {
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

export async function loadSampleData(button) {
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

export function sampleDataEmpty(text) {
  return empty("No operational records yet", text || "Import the plant's work-order history, record an incident, or load the labelled sample plant to explore the console.",
    h("div", { class: "page-actions is-centered" },
      h("button", { class: "btn btn-primary", type: "button", onclick: (e) => loadSampleData(e.currentTarget) }, "Load sample plant data"),
      navLink("Import work orders", "import", {}, "btn"),
      h("button", { class: "btn", type: "button", onclick: () => memoryForm() }, "Record an event")));
}
