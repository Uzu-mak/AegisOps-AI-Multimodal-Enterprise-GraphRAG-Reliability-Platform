import { notice, num, pageHead, pct, serviceChip, skeleton, stateChip } from "../components/ui.js";
import { render } from "../console.js";
import { API, api } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { href, main, refreshHealth } from "../lib/state.js";

/* ------------------------------------------------------------ system */

export const METRIC_STATE = {
  AVAILABLE: ["Measured", "normal"],
  NOT_INSTRUMENTED: ["Not measured", "muted"],
  NOT_CONNECTED: ["Not connected", "warn"],
  DEGRADED: ["Degraded", "warn"],
};

export function humanize(key) {
  const t = key.replace(/_/g, " ").replace(/\bllm\b/gi, "LLM").replace(/\bdb\b/gi, "database").replace(/\bapi\b/gi, "API");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function metricValue(m) {
  if (m.value === null || m.value === undefined) return m.detail || "—";
  const unit = { percent: "%", ms: " ms", seconds: " s", ratio: "", req_per_sec: " req/s", events_per_sec: " events/s" }[m.unit] ?? (m.unit ? ` ${m.unit}` : "");
  if (typeof m.value === "number") {
    if (m.unit === "ratio") return pct(m.value);
    return `${num(m.value, m.value < 10 ? 2 : 0)}${unit}`;
  }
  return String(m.value);
}

export function metricTable(title, group, id) {
  const entries = Object.entries(group || {}).filter(([, v]) => v && typeof v === "object" && "status" in v);
  if (!entries.length) return null;
  return h("section", { class: "panel", id },
    h("h2", null, title),
    h("div", { class: "table-wrap" }, h("table", { class: "metric-table" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Measure"), h("th", { scope: "col" }, "Value"), h("th", { scope: "col" }, "State"))),
      h("tbody", null, entries.map(([k, v]) => {
        const [label, sev] = METRIC_STATE[v.status] || [v.status, "muted"];
        return h("tr", null, h("th", { scope: "row" }, humanize(k)), h("td", null, metricValue(v)), h("td", null, stateChip(label, sev)));
      })))));
}

export async function viewSystem() {
  const head = pageHead("System health", "Which capabilities are available right now, what powers them, and how far behind the projections are. Unmeasured values are shown as such, never estimated.");
  put(main, head, skeleton());
  const [health, obs, proj] = await Promise.all([refreshHealth(), api("/system/observability"), api("/system/projection-metrics")]);
  const svc = health.services || {};
  const kafkaOn = health.integrations?.kafka_enabled;

  // What each dependency powers, so an outage maps directly to affected pages.
  const rows = [
    ["postgres", "PostgreSQL", "Canonical record store and outbox", [["Records", "memories"], ["Incidents", "incidents"], ["Investigate (keyword fallback)", "investigate"]]],
    ["qdrant", "Qdrant", "Vector projection", [["Search: Meaning", "search"], ["Investigate", "investigate"], ["Evaluation", "evaluation"]]],
    ["neo4j", "Neo4j", "Graph projection", [["Relationships", "graph"], ["Search: Relationships and Both", "search"], ["Investigate graph links", "investigate"]]],
    ["llm", "Answer model", "Writes investigation answers", [["Investigate", "investigate"]]],
  ];
  const svcTable = h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", null, "Services and what they power"), h("button", { class: "btn", type: "button", onclick: () => render() }, "Check again")),
    health.status === "unreachable" ? notice("crit", "The API isn't answering", health.error) :
    h("div", { class: "table-wrap" }, h("table", null,
      h("thead", null, h("tr", null, ["Service", "Role", "State", "Powers", "Details"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", null,
        rows.map(([k, label, role, powers]) => {
          const v = svc[k] || {};
          const details = k === "llm"
            ? [v.provider && `Configured: ${v.provider} (${v.model})`, v.active_model && `In use: ${v.active_model}`, v.error].filter(Boolean).join(". ")
            : [v.url || v.uri, v.error, v.projection_error, typeof v.retry_in_seconds === "number" ? `Next attempt in ${Math.ceil(v.retry_in_seconds)} s` : null].filter(Boolean).join(". ");
          return h("tr", null,
            h("th", { scope: "row" }, label), h("td", null, role),
            h("td", null, k === "llm" && v.synthetic ? stateChip("Test provider", "info") : serviceChip(v.status)),
            h("td", null, powers.map(([l, r], i) => [i ? ", " : "", h("a", { href: href(r) }, l)])),
            h("td", null, details || "—"));
        }),
        h("tr", null,
          h("th", { scope: "row" }, "Kafka"), h("td", null, "Outbound event stream for external systems"),
          h("td", null, kafkaOn ? stateChip("On", "normal") : stateChip("Off (optional)", "muted")),
          h("td", null, "No console page; projections don't depend on it"),
          h("td", null, kafkaOn ? "Outbox publisher sends every committed event" : "Start with: docker compose --profile integration up -d"))),
    )));

  const P = proj.ok ? proj.data : null;
  const O = obs.ok ? obs.data : null;
  put(main, head, svcTable,
    !proj.ok ? notice("crit", "Projection metrics unavailable", proj.error) : null,
    h("div", { class: "grid grid-metrics" },
      P ? metricTable("Projection outbox", P.kafka_outbox, "projection") : null,
      P ? metricTable("Qdrant projection", P.qdrant) : null,
      P ? metricTable("Neo4j projection", P.neo4j) : null,
      O ? metricTable("Investigations", O.investigations) : null,
      O ? metricTable("Retrieval", O.retrieval_runtime) : null,
      O ? metricTable("Answer model", O.llm) : null,
      O ? metricTable("Canonical storage", O.canonical_memory) : null,
      O ? metricTable("API runtime", O.api_runtime) : null),
    h("section", { class: "panel" }, h("details", { class: "raw" }, h("summary", null, "Show raw payloads"), h("pre", null, JSON.stringify({ health, observability: O, projection: P }, null, 2)))),
  );
}
