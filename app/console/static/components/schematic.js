import { SERVICE_STATE, num, stateChip } from "./ui.js";
import { h, s } from "../lib/dom.js";
import { href } from "../lib/state.js";

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
