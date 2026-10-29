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

export function drawGraph(anchor, related) {
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
