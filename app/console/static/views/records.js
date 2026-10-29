import { memoryForm, sampleDataEmpty, showMemory } from "../components/records.js";
import { LIFECYCLE, TYPE_LABEL, empty, fmtWhen, lifecycleChip, notice, pageHead, skeleton, typeLabel } from "../components/ui.js";
import { fetchAllMemories } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { href, main, navLink, whenOf } from "../lib/state.js";

/* ----------------------------------------------------------- records */

export async function viewMemories(params) {
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
