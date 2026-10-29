import { sampleDataEmpty, showMemory } from "../components/records.js";
import { SERVICE_STATE, barList, empty, fmtAgo, lifecycleChip, metaPair, notice, num, pageHead, readouts, skeleton, stateChip, typeLabel } from "../components/ui.js";
import { api, fetchAllMemories } from "../lib/api.js";
import { add, h, put, s } from "../lib/dom.js";
import { deriveIncidents, href, main, services, state } from "../lib/state.js";
import { isAdmin } from "../lib/session.js";

/* ============================================================== VIEWS */

/* ---------------------------------------------------------- overview */

export async function viewOverview() {
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
    isAdmin() ? schematic({ svc: services(), total: items.length, active: active.length, pending, failed }) : null,
    readouts([
      { label: "Open incidents", value: open.length, note: "Incidents without an active resolution", sev: open.length ? "warn" : null, to: href("incidents") },
      { label: "Active records", value: active.length, note: `${items.length - active.length} archived, disputed or superseded`, to: href("memories") },
      { label: "Waiting to project", value: pending, note: "Outbox events not yet in Qdrant or Neo4j", sev: pending > 0 ? "warn" : null, to: href("system"), admin: true },
      { label: "Failed projections", value: failed, note: "Gave up after retries; needs a look", sev: failed > 0 ? "crit" : null, to: href("system"), admin: true },
    ].filter((r) => !r.admin || isAdmin())),
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

/** Process schematic of the memory pipeline. Each stage links to the page it powers. */
export function schematic({ svc, total, active, pending, failed }) {
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
