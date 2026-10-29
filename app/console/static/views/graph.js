import { sampleDataEmpty, showMemory } from "../components/records.js";
import { empty, lifecycleChip, notice, pageHead, shortId, skeleton, typeLabel } from "../components/ui.js";
import { api, fetchAllMemories } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { capable, go, href, main, navLink } from "../lib/state.js";

/* ------------------------------------------------------------- graph */

export async function viewGraph(params) {
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

// The API returns which records are linked, not why, so links are grouped by
// the shared field that can be read from the records themselves.
const GROUPS = [
  ["incident", "Same incident", (a, m) => a.incident_id && m.incident_id === a.incident_id],
  ["supersession", "Replaces or replaced by", (a, m) => m.supersedes_memory_id === a.id || a.supersedes_memory_id === m.id],
  ["asset", "Same asset, other incidents", (a, m) => a.asset_id && m.asset_id === a.asset_id],
  ["other", "Linked through a line, source or a second step", () => true],
];

export function drawGraph(anchor, related) {
  if (!related.length) return empty("No linked records", "This record doesn't share an asset, incident, line or source with any other record yet.");
  const buckets = GROUPS.map(([key, label]) => ({ key, label, items: [] }));
  for (const m of related) {
    const i = GROUPS.findIndex(([, , test]) => test(anchor, m));
    buckets.at(i).items.push(m);
  }
  const row = (m) => h("li", { class: m.status !== "active" ? "is-inactive" : null },
    h("span", { class: "tag" }, typeLabel(m.memory_type)),
    h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(m.id) }, m.title),
    m.status !== "active" ? lifecycleChip(m.status) : null,
    m.incident_id && m.incident_id !== anchor.incident_id ? navLink(m.incident_id, "incidents", { id: m.incident_id }, "rel-incident") : null);
  return h("div", { class: "rel-map" },
    h("section", { class: "rel-anchor", "aria-label": "Starting record" },
      h("p", { class: "prov-label" }, "Starting record"),
      h("h2", null, h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(anchor.id) }, anchor.title)),
      h("p", { class: "queue-meta" }, h("span", { class: "tag" }, typeLabel(anchor.memory_type)),
        anchor.asset_id ? h("span", null, `Asset ${anchor.asset_id}`) : null,
        anchor.incident_id ? h("span", null, `Incident ${anchor.incident_id}`) : null),
      h("p", { class: "toolbar-note" }, `${related.length} linked record${related.length === 1 ? "" : "s"}`)),
    h("div", { class: "rel-groups" }, buckets.filter((b) => b.items.length).map((b) =>
      h("section", { class: "rel-group", "aria-labelledby": `rel-${b.key}` },
        h("h3", { id: `rel-${b.key}` }, b.label, h("span", { class: "rel-count" }, String(b.items.length))),
        h("ul", null, b.items.map(row))))));
}
