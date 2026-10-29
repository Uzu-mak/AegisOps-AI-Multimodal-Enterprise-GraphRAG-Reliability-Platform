import { memoryForm, sampleDataEmpty, showMemory } from "../components/records.js";
import { empty, fmtWhen, lifecycleChip, notice, pageHead, skeleton, stateChip, typeLabel } from "../components/ui.js";
import { fetchAllMemories } from "../lib/api.js";
import { h, icon, put, s } from "../lib/dom.js";
import { contextOf, deriveIncidents, href, main, navLink, whenOf } from "../lib/state.js";

/* --------------------------------------------------------- incidents */

export async function viewIncidents(params) {
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

  // Filters narrow the list only; the selected incident stays open.
  const filt = { status: params.get("status") || "", asset: params.get("asset") || "" };
  const assets = [...new Set(incidents.map((i) => i.head.asset_id).filter(Boolean))].sort();
  const pick = (name, label, options) => h("div", { class: "field" },
    h("label", { for: `inc-${name}` }, label),
    h("select", { id: `inc-${name}`, name }, options.map(([v, l]) => h("option", { value: v, selected: v === filt[name] }, l))));
  const filters = h("form", { class: "toolbar incident-filters", "aria-label": "Filter incidents", onsubmit: (e) => e.preventDefault() },
    pick("status", "Status", [["", "All"], ["open", "Open"], ["resolved", "Resolved"]]),
    pick("asset", "Asset", [["", "All assets"], ...assets.map((a) => [a, a])]));
  const list = h("ul", { class: "incident-list", "aria-label": "Incidents" });
  let current = selected;
  const select = (inc) => {
    current = inc;
    list.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === inc.id)));
    history.replaceState(null, "", href("incidents", { id: inc.id, status: filt.status, asset: filt.asset }));
    showIncident(inc);
  };
  const drawList = () => {
    const shown = incidents.filter((i) =>
      (!filt.status || (filt.status === "open") !== i.isResolved) && (!filt.asset || i.head.asset_id === filt.asset));
    put(list, shown.length ? shown.map((inc) => h("li", null, h("button", {
      type: "button",
      dataset: { id: inc.id },
      "aria-pressed": inc === current ? "true" : "false",
      onclick: () => select(inc),
    },
      h("span", { class: "incident-id" }, inc.head.title),
      h("span", { class: "incident-sub" }, `${inc.id} on ${inc.head.asset_id || "unknown asset"}`),
      inc.isResolved ? stateChip("Resolved", "normal") : stateChip("Open", "warn"),
    ))) : h("li", { class: "toolbar-note" }, "No incidents match these filters."));
  };
  filters.addEventListener("input", (e) => {
    filt[e.target.name] = e.target.value;
    history.replaceState(null, "", href("incidents", { id: current.id, status: filt.status, asset: filt.asset }));
    drawList();
  });
  drawList();

  // Other incidents on the same asset: the history a new investigation needs.
  const earlierOn = (inc) => {
    const others = inc.head.asset_id ? incidents.filter((o) => o !== inc && o.head.asset_id === inc.head.asset_id) : [];
    if (!others.length) return null;
    return h("div", { class: "related-incidents" },
      h("h3", null, `Other incidents on ${inc.head.asset_id}`),
      h("ul", null, others.map((o) => h("li", null,
        h("button", { class: "btn btn-quiet", type: "button", onclick: () => select(o) }, o.head.title),
        h("span", { class: "cell-sub" }, `${o.id}, ${fmtWhen(o.last)}`),
        o.isResolved ? stateChip("Resolved", "normal") : stateChip("Open", "warn")))));
  };

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
      earlierOn(inc),
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
  put(main, head(), h("div", { class: "grid grid-split" }, h("div", { class: "stack incident-side" }, filters, list), detail));
}
