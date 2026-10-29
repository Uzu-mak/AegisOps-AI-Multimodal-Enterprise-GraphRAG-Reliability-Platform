import { sampleDataEmpty, showMemory } from "../components/records.js";
import { barList, empty, fmtAgo, lifecycleChip, metaPair, notice, num, pageHead, readouts, skeleton, stateChip, typeLabel } from "../components/ui.js";
import { api, fetchAllMemories } from "../lib/api.js";
import { add, h, put } from "../lib/dom.js";
import { deriveIncidents, href, main, navLink } from "../lib/state.js";
import { isAdmin } from "../lib/session.js";

/* ---------------------------------------------------------- overview */

// Situational awareness first: which assets have open incidents, then what
// changed. The data pipeline behind it lives on System health.
export async function viewOverview() {
  const head = (actions) => pageHead("Plant overview", "Open incidents by asset, and what was recorded most recently.", actions);
  put(main, head(), h("div", { class: "panel" }, skeleton()));

  const [all, outbox] = await Promise.all([fetchAllMemories(), isAdmin() ? api("/system/outbox-stats") : Promise.resolve(null)]);
  if (!all.ok) return put(main, head(), notice("crit", "Records can't be loaded", all.error));
  const items = all.items;
  const active = items.filter((m) => m.status === "active");
  const incidents = deriveIncidents(items);
  const open = incidents.filter((i) => !i.isResolved);
  const openAssets = new Set(open.map((i) => i.head.asset_id || ""));
  const findings = active.filter((m) => m.source_type === "investigation").length;
  const pending = outbox?.ok ? outbox.data?.summary?.pending ?? 0 : 0;
  const failed = outbox?.ok ? outbox.data?.summary?.failed ?? 0 : 0;

  put(main,
    head(items.length ? [h("a", { class: "btn btn-primary", href: href("investigate") }, "Investigate")] : null),
    failed || pending ? notice(failed ? "crit" : "warn", failed ? `${num(failed)} record updates failed to reach search` : `${num(pending)} record updates waiting for search`,
      "Records are safe in PostgreSQL; search and relationships catch up once the projection worker applies them.",
      [navLink("Open System health", "system", {}, "btn")]) : null,
    readouts([
      { label: "Open incidents", value: open.length, note: "Without an active resolution", sev: open.length ? "warn" : null, to: href("incidents", { status: "open" }) },
      { label: "Assets affected", value: openAssets.size, note: "Assets with at least one open incident", sev: openAssets.size ? "warn" : null },
      { label: "Confirmed findings", value: findings, note: "Recorded by engineers from investigations", to: href("memories", { source: "investigation", status: "active" }) },
      { label: "Active records", value: active.length, note: `${items.length - active.length} archived, disputed or superseded`, to: href("memories") },
    ]),
  );

  if (!items.length) return add(main, sampleDataEmpty());

  // Group open incidents by asset; assets with the most open incidents first.
  const groups = new Map();
  for (const inc of open) {
    const key = inc.head.asset_id || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(inc);
  }
  const ordered = [...groups.entries()].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));

  const byType = {};
  for (const m of active) byType[m.memory_type] = (byType[m.memory_type] || 0) + 1;
  const recent = [...items].sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, 6);

  add(main,
    h("div", { class: "grid grid-main" },
      h("section", { class: "panel", "aria-labelledby": "q-title" },
        h("div", { class: "panel-head" }, h("h2", { id: "q-title" }, "Open incidents by asset"), h("a", { href: href("incidents") }, "All incidents")),
        ordered.length
          ? h("div", { class: "asset-groups" }, ordered.map(([asset, list]) => h("section", { class: "asset-group", "aria-label": asset || "No asset" },
              h("div", { class: "asset-group-head" },
                h("h3", null, asset ? h("a", { href: href("memories", { asset, status: "any" }) }, asset) : "No asset recorded"),
                stateChip(`${list.length} open`, "warn")),
              h("ul", { class: "queue" }, list.map((inc) => h("li", null,
                h("a", { class: "queue-item", href: href("incidents", { id: inc.id }) },
                  h("span", { class: "queue-title" }, inc.head.title),
                  h("span", { class: "queue-meta" },
                    metaPair("Incident", inc.id), metaPair("Records", String(inc.recs.length)), metaPair("Last activity", fmtAgo(inc.last))))))))))
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
