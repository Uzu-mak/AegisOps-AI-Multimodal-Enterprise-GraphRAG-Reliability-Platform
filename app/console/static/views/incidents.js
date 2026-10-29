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
