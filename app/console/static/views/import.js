import { clearInvalid, formField, markInvalid } from "../components/records.js";
import { busy, fmtWhen, metaPair, notice, num, pageHead, readouts, stateChip, toast } from "../components/ui.js";
import { api } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { href, main, navLink, refreshHealth } from "../lib/state.js";

/* ------------------------------------------------------------ import */

// Maintenance history from the plant's CMMS (Maximo, SAP PM, ...). The same
// API call previews (dry_run) and writes, so what is shown is what is written.
export async function viewImport() {
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

  // Where the operator is: 1 choose, 2 check the preview, 3 import.
  const stepNames = ["Choose an export", "Check the preview", "Import"];
  const stepper = h("ol", { class: "stepper", "aria-label": "Import progress" }, stepNames.map((n, i) => h("li", null, h("span", { class: "stepper-n", "aria-hidden": "true" }, String(i + 1)), n)));
  const setStep = (active, done = false) => [...stepper.children].forEach((li, i) => {
    li.className = i < active || (done && i === active) ? "is-done" : i === active ? "is-current" : "";
    if (i === active && !done) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
  });
  setStep(0);

  const showPreview = (d) => {
    setStep(1);
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
    setStep(2, true);
    const w = d.written.created + d.written.superseded;
    put(result, notice("info", `Imported ${num(d.written.created)} new and ${num(d.written.superseded)} updated work orders`,
      `${num(d.unchanged)} were already up to date. The records are in PostgreSQL now and findable by keyword; ` +
      `the projection worker is indexing ${num(w)} of them for meaning and relationships (see System health for progress).`,
      [navLink("Open imported records", "memories", { source: "work_order", status: "active" }, "btn btn-primary"),
       navLink("Investigate", "investigate", {}, "btn"), navLink("System health", "system", {}, "btn")]));
    refreshHealth();
  };

  put(main, head, stepper,
    h("section", { class: "panel", "aria-labelledby": "imp-src" },
      h("div", { class: "panel-head" }, h("h2", { id: "imp-src" }, "Choose an export"),
        h("p", null, "One row per work order. Re-importing a newer export is safe: unchanged work orders are skipped and changed ones keep their history.")),
      form, h("div", { class: "page-actions" }, previewBtn, sampleBtn)),
    result);
}
