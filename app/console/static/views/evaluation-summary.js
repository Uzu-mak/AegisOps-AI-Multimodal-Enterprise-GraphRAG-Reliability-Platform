// Evaluation summary for managers: the latest run in plain language, with
// status against working targets, the change since the last comparable run
// and the trend over saved runs. Every number is read from a saved or local
// run; nothing is estimated. Shown in the Evaluation page's Summary tab.
import { empty, fmtWhen, notice, num, pct, shortId, skeleton, stateChip } from "../components/ui.js";
import { groupedBars, legend, lineTrend, withTooltip } from "../components/charts.js";
import { evidenceStrength } from "../lib/evalmath.js";
import { api } from "../lib/api.js";
import { h, put } from "../lib/dom.js";
import { MODE_LABEL, setEvidence } from "./evaluation.js";

// Working targets for this pilot. They are a starting point to agree with the
// plant, not an industry standard; the page says so next to every status.
export const TARGETS = { evidence: 0.9, citations: 0.9, seconds: 5 };
const ANSWER_CONTEXT = 5; // the answer writer reads the top 5 records (GraphRAGPipeline.context_limit)

const labelledQuestions = (run, mode) => run.cases.filter((c) => c.mode === mode && c.labeled !== false);
const questionSet = (run) => [...new Set(run.cases.filter((c) => c.labeled !== false).map((c) => c.question))].sort().join("\u0000");
const comparable = (a, b) => a.k === b.k && a.embedding_model === b.embedding_model
  && (a.per_mode?.agentic?.context_limit ?? null) === (b.per_mode?.agentic?.context_limit ?? null);
const primaryMode = (run) => ["agentic", "hybrid", "semantic", "graph"].find((m) => (run.modes_run || []).includes(m));
const status = (v, target, higherIsBetter = true) => {
  if (typeof v !== "number") return stateChip("Not measured", "info");
  const ok = higherIsBetter ? v >= target : v <= target;
  const near = higherIsBetter ? v >= target - 0.15 : v <= target * 1.5;
  return ok ? stateChip("On target", "normal") : near ? stateChip("Watch", "warn") : stateChip("Below target", "crit");
};
const pts = (v) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.round(Math.abs(v) * 100)} pts`;

function tile({ label, value, note, chip, change }) {
  return h("div", { class: "kpi" },
    h("div", { class: "kpi-label" }, label),
    h("div", { class: "kpi-value" }, value),
    h("div", { class: "kpi-meta" }, chip, change ? h("span", { class: "kpi-change" }, change) : null),
    h("p", { class: "kpi-note" }, note));
}

export async function managerSummary(host, { latest, history, items }) {
  if (!latest) return put(host, empty("No evaluation run yet", "Once an engineer runs an evaluation, this page summarises it for managers."));
  put(host, h("div", { class: "panel" }, skeleton()));
  const mode = primaryMode(latest);
  const pm = latest.per_mode || {};
  const rows = labelledQuestions(latest, mode).filter((c) => !c.error);
  const n = rows.length;
  if (!n) return put(host, notice("info", "The latest run has no labelled questions", "Label questions first; the summary reports on labelled questions only."));

  // Previous comparable runs (same embedding and top k), oldest first, for change and trend.
  const sameKind = (history || []).filter((r) => comparable(r, latest)).slice(0, 12);
  const full = (await Promise.all(sameKind.map((r) => (r.run_id === latest.run_id ? { ok: true, data: latest } : api(`/evaluation/history/${r.run_id}`)))))
    .filter((r) => r.ok).map((r) => r.data).filter((r) => (r.modes_run || []).includes(mode)).reverse();
  if (!full.some((r) => r.run_id === latest.run_id)) full.push(latest);
  const idx = full.findIndex((r) => r.run_id === latest.run_id);
  const prev = idx > 0 ? full[idx - 1] : null;
  const sameQuestions = prev && questionSet(prev) === questionSet(latest);

  const hits5 = rows.filter((c) => c.recall_at_5 > 0).length;
  const r5 = pm[mode]?.recall_at_5;
  const cites = pm[mode]?.groundedness;
  const secs = typeof pm[mode]?.latency_p50_ms === "number" ? pm[mode].latency_p50_ms / 1000 : null;
  const change = (key) => {
    if (!prev) return "First comparable run";
    if (!sameQuestions) return "Test questions changed since the last run";
    const a = pm[mode]?.[key], b = prev.per_mode?.[mode]?.[key];
    return typeof a === "number" && typeof b === "number" ? `${pts(a - b)} since ${fmtWhen(prev.generated_at)}` : null;
  };

  // Facts for "what this means", each computed from the run.
  const byQ = (m) => new Map(labelledQuestions(latest, m).map((c) => [c.question, c.recall_at_k > 0]));
  const sem = byQ("semantic"), gr = byQ("graph"), hyb = byQ("hybrid");
  const rescued = [...hyb.keys()].filter((q) => hyb.get(q) && sem.has(q) && gr.has(q) && sem.get(q) !== gr.get(q)).length;
  const missedAll = rows.filter((c) => !c.recall_at_k).length;
  const plain = ["semantic", "graph", "hybrid"].filter((m) => typeof pm[m]?.latency_p50_ms === "number");
  const fastest = plain.sort((a, b) => pm[a].latency_p50_ms - pm[b].latency_p50_ms)[0];
  const byId = new Map((items || []).map((m) => [m.id, m]));
  const expected = new Set(rows.flatMap((c) => c.expected_memory_ids || []));
  const incidents = new Set([...expected].map((id) => byId.get(id)?.incident_id).filter(Boolean));
  const assets = new Set([...expected].map((id) => byId.get(id)?.asset_id).filter(Boolean));
  const plural = (k, word) => `${k} ${word}${k === 1 ? "" : "s"}`;
  const coverage = !incidents.size && !assets.size
    ? `${plural(expected.size, "labelled record")}, not linked to incidents or assets.`
    : `${plural(incidents.size, "incident")} and ${plural(assets.size, "asset")} covered.`;
  const semantic = !/fake|hashedterm/i.test(latest.embedding_model || "");
  const strength = evidenceStrength({ n, semantic, ...setEvidence(latest.question_set) });

  const facts = [
    `For ${hits5} of ${n} test question${n === 1 ? "" : "s"}, the right maintenance record was among the ${ANSWER_CONTEXT} records the assistant reads before it answers.`,
    missedAll ? `${missedAll} question${missedAll === 1 ? " was" : "s were"} not answered with the right record even in the top ${latest.k}: see Failure analysis.` : `Every question had a right record somewhere in the top ${latest.k}.`,
    sem.size && gr.size && hyb.size ? (rescued ? `Combining the two search methods recovered ${rescued} question${rescued === 1 ? "" : "s"} that one method alone missed.` : "Combining the two search methods did not recover any question that one method alone missed in this run.") : null,
    (() => {
      const ab = pm.agentic?.abstentions || [];
      const no = ab.filter((a) => a.expects_no_answer);
      return no.length ? `When no record answered the question, the assistant said so ${no.filter((a) => a.abstained).length} of ${no.length} times instead of guessing.` : null;
    })(),
    secs !== null && fastest ? `A full investigation takes about ${secs.toFixed(1)} s per question, ${Math.round(pm[mode].latency_p50_ms / pm[fastest].latency_p50_ms)}× a plain search, because it writes an answer as well.` : null,
  ].filter(Boolean);

  const bars = withTooltip(h("div", { class: "chart-wrap" },
    legend([{ cls: "is-s1", label: `Found in the first ${ANSWER_CONTEXT} (what the assistant reads)` }, { cls: "is-s2", label: `Found in the first ${latest.k}` }]),
    groupedBars({
      rows: (latest.modes_run || []).map((m) => ({ label: MODE_LABEL[m], values: { a: pm[m]?.recall_at_5 ?? null, b: pm[m]?.recall_at_k ?? null } })),
      series: [{ key: "a", label: `First ${ANSWER_CONTEXT}`, cls: "is-s1" }, { key: "b", label: `First ${latest.k}`, cls: "is-s2" }],
      format: pct, label: "Share of needed records found, by search method",
    })));
  const oneDay = new Set(full.map((r) => new Date(r.generated_at).toDateString())).size === 1;
  const trendPts = full.map((r, i) => ({
    label: oneDay ? new Date(r.generated_at).toLocaleTimeString(undefined, { timeStyle: "short" }) : new Date(r.generated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    value: r.per_mode?.[mode]?.recall_at_5,
    breakBefore: i > 0 && questionSet(r) !== questionSet(full[i - 1]),
    tip: `${fmtWhen(r.generated_at)}: ${pct(r.per_mode?.[mode]?.recall_at_5)} with ${num(labelledQuestions(r, mode).length)} questions`,
  }));
  const trend = full.length < 2
    ? empty("The trend starts with the next run", "Each saved run measured the same way adds a point here, so you can see whether reliability is improving.")
    : withTooltip(h("div", { class: "chart-wrap" }, lineTrend({ points: trendPts, format: pct, label: `${MODE_LABEL[mode]}: right evidence in the first ${ANSWER_CONTEXT}, by run` })));

  put(host,
    h("section", { class: "panel summary", "aria-labelledby": "mgr-head" },
      h("div", { class: "panel-head" }, h("div", null,
        h("h2", { id: "mgr-head" }, "Can the assistant find the right maintenance records?"),
        h("p", null, `Latest test: ${fmtWhen(latest.generated_at)}, ${n} question${n === 1 ? "" : "s"}, measured on the ${MODE_LABEL[mode]} mode that engineers use.`)),
        h("button", { class: "btn no-print", type: "button", onclick: () => window.print() }, "Print or save as PDF")),
      h("p", { class: "summary-headline" }, facts[0]),
      h("div", { class: "kpis" },
        tile({ label: "Right evidence in what it reads", value: pct(r5), chip: status(r5, TARGETS.evidence), change: change("recall_at_5"),
          note: `Share of needed records in the top ${ANSWER_CONTEXT}. Working target ${pct(TARGETS.evidence)}.` }),
        tile({ label: "Answer sentences with a source", value: typeof cites === "number" ? pct(cites) : "—", chip: status(cites, TARGETS.citations), change: typeof cites === "number" ? change("groundedness") : null,
          note: `Shows sources are cited, not that they were checked. Working target ${pct(TARGETS.citations)}.` }),
        tile({ label: "Time to an answer", value: secs === null ? "—" : `${secs.toFixed(1)} s`, chip: status(secs, TARGETS.seconds, false),
          note: `Typical (median) per question. Working target under ${TARGETS.seconds} s.` }),
        tile({ label: "How much to trust these numbers", value: strength.label, chip: stateChip(`${n} question${n === 1 ? "" : "s"}`, strength.sev),
          note: `${coverage}${strength.level === "decision" ? "" : " Not yet enough for a decision."}` })),
      h("div", { class: "summary-charts" },
        h("figure", { class: "summary-fig viz" }, h("figcaption", null, h("strong", null, "Which search method finds the evidence"), h("span", null, "Longer bars are better.")), bars),
        h("figure", { class: "summary-fig viz" }, h("figcaption", null, h("strong", null, "Is it getting better?"), h("span", null, `${MODE_LABEL[mode]}, right evidence in the first ${ANSWER_CONTEXT}, runs measured the same way.`)), trend)),
      h("div", { class: "summary-cols" },
        h("div", null, h("h3", null, "What this means"), h("ul", { class: "summary-list" }, facts.slice(1).map((f) => h("li", null, f)))),
        h("div", null, h("h3", null, "Before relying on it"), h("ul", { class: "summary-list" },
          strength.why.map((w) => h("li", null, w[0].toUpperCase() + w.slice(1) + ".")),
          !incidents.size && !assets.size ? h("li", null, "The labelled records aren't linked to incidents or assets, so how varied the test is can't be checked.")
            : incidents.size < 5 ? h("li", null, `The questions cover ${incidents.size} incident${incidents.size === 1 ? "" : "s"}; a fair test spans many assets and fault types.`) : null,
          h("li", null, "Targets are working targets for this pilot, to be agreed with the plant.")))),
      h("p", { class: "toolbar-note" }, `${latest.question_set ? `Question set ${latest.question_set.name} v${latest.question_set.version} (${latest.question_set.status.replace("_", " ")}${latest.question_set.reviewed_by ? `, reviewed by ${latest.question_set.reviewed_by}` : ""}) · ` : "Ad hoc questions, not a saved set · "}Run ${shortId(latest.run_id || "")} · top ${latest.k} · ${String(latest.embedding_model || "").replace(/\(.*\)$/, "")}${latest.persisted ? " · saved to run history" : " · kept in this browser only"}`)));
}
