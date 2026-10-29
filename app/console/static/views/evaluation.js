import { busy, empty, fmtWhen, notice, num, pageHead, pct, scoreBar, shortId, skeleton, toast } from "../components/ui.js";
import { groupedBars, heatStep, legend, logBars, withTooltip } from "../components/charts.js";
import { api, fetchAllMemories } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { evalState, href, main, navLink, saveEvalCases } from "../lib/state.js";

/* -------------------------------------------------------- evaluation */

export const MODE_LABEL = { semantic: "Meaning", graph: "Relationships", hybrid: "Both", agentic: "Investigation" };

export async function viewEvaluation() {
  const head = pageHead("Evaluation", "Measure whether retrieval finds the records a correct answer needs. Runs use the same retrieval and metrics as the recorded CLI benchmark.");
  put(main, head, skeleton());
  const all = await fetchAllMemories({ status: "active" });
  const items = all.items || [];
  const titleOf = (id) => items.find((m) => m.id === id)?.title || `record ${shortId(id)}`;

  const caseList = h("div", { class: "stack" });
  const results = h("div", { class: "stack", "aria-live": "polite" });
  const q = h("input", { type: "text", id: "e-q", placeholder: "e.g. What fixed the oversize holes on drill cell DC-3?" });
  const expected = h("select", { id: "e-exp", multiple: true, size: 6 }, items.map((m) => h("option", { value: m.id }, m.title)));

  const drawCases = () => {
    put(caseList, evalState.cases.length
      ? h("div", { class: "table-wrap" }, h("table", null,
          h("caption", null, `${evalState.cases.length} benchmark question${evalState.cases.length === 1 ? "" : "s"}, saved in this browser`),
          h("thead", null, h("tr", null, h("th", { scope: "col" }, "Question"), h("th", { scope: "col" }, "Records a correct answer must use"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
          h("tbody", null, evalState.cases.map((c, i) => h("tr", null,
            h("td", null, c.question),
            h("td", null, c.expected.map(titleOf).join("; ") || "—"),
            h("td", { class: "num" }, h("button", { class: "btn btn-quiet", type: "button", onclick: () => { evalState.cases.splice(i, 1); saveEvalCases(); drawCases(); } }, "Remove")))))))
      : empty("No benchmark questions", "Add a question and pick the records a good answer must retrieve, or use Add to benchmark from an investigation."));
  };

  const pendingPanel = () => {
    const p = evalState.pending;
    if (!p) return null;
    const boxes = p.candidates.map((c) => h("label", { class: "check" }, h("input", { type: "checkbox", value: c.id }), c.title));
    const panel = h("section", { class: "panel", "aria-labelledby": "pend-title" },
      h("div", { class: "panel-head" }, h("h2", { id: "pend-title" }, "Label a question from your investigation")),
      h("p", { class: "toolbar-note" }, `“${p.question}”. Tick only the records a correct answer must use. These labels are your judgement, so nothing is ticked for you.`),
      h("div", { class: "check-list" }, boxes),
      h("div", { class: "page-actions" },
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          const ids = boxes.map((b) => b.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
          if (!ids.length) return toast("Tick at least one record, or discard the question", true);
          evalState.cases.push({ question: p.question, expected: ids });
          evalState.pending = null; saveEvalCases(); panel.remove(); drawCases();
          toast("Question added to the benchmark");
        } }, "Add labelled question"),
        h("button", { class: "btn", type: "button", onclick: () => { evalState.pending = null; panel.remove(); } }, "Discard")));
    return panel;
  };

  const kSel = h("select", { id: "e-k" }, [5, 10, 20].map((n) => h("option", { value: n, selected: n === 10 }, String(n))));
  const modeBoxes = h("fieldset", null, h("legend", null, "Compare"),
    h("div", { class: "toolbar" }, Object.entries(MODE_LABEL).map(([v, l]) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "emode", value: v, checked: v !== "agentic" }), l))));
  const run = h("button", { class: "btn btn-primary", type: "button" }, "Run benchmark");

  run.addEventListener("click", async () => {
    if (!evalState.cases.length) return toast("Add at least one question first", true);
    const modes = [...modeBoxes.querySelectorAll("input:checked")].map((i) => i.value);
    if (!modes.length) return toast("Choose at least one mode", true);
    busy(run, true);
    put(results, h("div", { class: "panel" }, h("p", null, "Running benchmark"), skeleton()));
    const r = await api("/evaluation/runs", { method: "POST", timeout: 120000, body: {
      cases: evalState.cases.map((c, i) => ({ case_id: `q-${String(i + 1).padStart(3, "0")}`, question: c.question, expected_memory_ids: c.expected })),
      modes, k: Number(kSel.value) } });
    busy(run, false);
    if (!r.ok) return put(results, notice("crit", "The benchmark didn't run", r.error));
    evalState.results = r.data;
    drawResults();
    results.scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });

  const download = (name, text, type) => {
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
    document.body.append(a); a.click(); a.remove();
  };

  const drawResults = () => {
    const res = evalState.results;
    if (!res) return put(results);
    const k = res.k;
    const pm = res.per_mode || {};
    const modesRun = res.modes_run || [];
    const questions = [...new Set((res.cases || []).map((c) => c.question))];
    const n = questions.length;
    const semantic = !/fake|hashedterm/i.test(res.embedding_model || "");
    const unavailable = Object.entries(res.unavailable_modes || {});
    const measured = (m, key) => typeof pm[m]?.[key] === "number";
    const best = modesRun.filter((m) => measured(m, "recall_at_k"))
      .sort((a, b) => pm[b].recall_at_k - pm[a].recall_at_k || (pm[b].mrr ?? 0) - (pm[a].mrr ?? 0)).at(0);
    const fastest = modesRun.filter((m) => measured(m, "latency_p50_ms")).sort((a, b) => pm[a].latency_p50_ms - pm[b].latency_p50_ms).at(0);
    const grounded = pm.agentic?.groundedness;

    const tile = (label, value, note, sev) => h("div", { class: `readout${sev ? ` is-${sev}` : ""}` },
      h("dt", null, label), h("dd", null, value, h("span", { class: "readout-note" }, note)));

    const metricSeries = [
      { key: "recall_at_5", label: "Recall at 5", cls: "is-s1" },
      { key: "recall_at_k", label: `Recall at ${k}`, cls: "is-s2" },
      { key: "mrr", label: `MRR at ${k}`, cls: "is-s3" },
    ];
    const metricChart = h("section", { class: "panel viz", "aria-labelledby": "ev-metrics" },
      h("div", { class: "panel-head" }, h("div", null,
        h("h2", { id: "ev-metrics" }, "Does each mode find the records a correct answer needs?"),
        h("p", null, "Recall: share of the labelled records found in the top results. MRR: how high the first one ranks (100% means first place)."))),
      legend(metricSeries),
      withTooltip(h("div", { class: "chart-wrap" }, groupedBars({
        rows: modesRun.map((m) => ({ label: MODE_LABEL[m], values: Object.fromEntries(metricSeries.map((sr) => [sr.key, pm[m]?.[sr.key] ?? null])) })),
        series: metricSeries,
        format: (v) => `${Math.round(v * 100)}%`,
        label: `Recall at 5, recall at ${k} and MRR at ${k} for each retrieval mode`,
      }))));

    const latencyChart = h("section", { class: "panel viz", "aria-labelledby": "ev-latency" },
      h("div", { class: "panel-head" }, h("div", null,
        h("h2", { id: "ev-latency" }, "How long each mode takes"),
        h("p", null, "Median time per question on this machine. Log scale: each gridline is ten times the last."))),
      withTooltip(h("div", { class: "chart-wrap" }, logBars({
        rows: modesRun.map((m) => ({ label: MODE_LABEL[m], value: pm[m]?.latency_p50_ms, text: measured(m, "latency_p50_ms") ? `${num(pm[m].latency_p50_ms, 0)} ms` : "not measured", cls: m === fastest ? "is-s1" : "is-quiet" })),
        unit: "ms",
        label: "Median latency per retrieval mode, log scale",
      }))));

    const caseOf = (q, m) => (res.cases || []).find((c) => c.question === q && c.mode === m);
    const heat = h("section", { class: "panel viz", "aria-labelledby": "ev-heat" },
      h("div", { class: "panel-head" }, h("div", null,
        h("h2", { id: "ev-heat" }, "Question by question"),
        h("p", null, `Recall at ${k} for each question and mode, with the rank of the first labelled record. Select a cell to open it.`))),
      h("ul", { class: "legend heat-key", "aria-label": "Colour key" },
        [[0, "0%"], [1, "under 50%"], [2, "50 to 99%"], [3, "100%"]].map(([st, l]) => h("li", null, h("span", { class: `sw heat-${st}`, "aria-hidden": "true" }), l))),
      h("div", { class: "table-wrap heat" }, h("table", null,
        h("caption", { class: "visually-hidden" }, `Recall at ${k} by question and mode`),
        h("thead", null, h("tr", null, h("th", { scope: "col" }, "Question"), modesRun.map((m) => h("th", { scope: "col", class: "num" }, MODE_LABEL[m])))),
        h("tbody", null, questions.map((q) => h("tr", null,
          h("th", { scope: "row" }, q),
          modesRun.map((m) => {
            const c = caseOf(q, m);
            if (!c) return h("td", { class: "heat-cell" }, "—");
            const st = c.error ? null : heatStep(c.recall_at_k);
            const rank = c.error ? "error" : c.mrr ? `first at #${Math.round(1 / c.mrr)}` : `not in top ${k}`;
            const to = m === "agentic" ? href("investigate", { q }) : href("search", { q, mode: m });
            return h("td", { class: `heat-cell${st === null ? "" : ` heat-${st}`}` },
              h("a", { href: to, title: `${MODE_LABEL[m]}: ${c.error ? "error" : pct(c.recall_at_k)}, ${rank}` },
                h("span", { class: "heat-value" }, c.error ? "Error" : pct(c.recall_at_k)),
                h("span", { class: "heat-sub" }, rank)));
          }))))))) ;

    const tables = h("details", { class: "panel raw" },
      h("summary", null, "Show the numbers as tables"),
      h("div", { class: "table-wrap" }, h("table", null,
        h("caption", null, `Mean over ${n} labelled question${n === 1 ? "" : "s"}`),
        h("thead", null, h("tr", null, ["Mode", "Recall at 5", `Recall at ${k}`, `MRR at ${k}`, "Cited sentences", "Latency p50"].map((c, i) => h("th", { scope: "col", class: i ? "num" : null }, c)))),
        h("tbody", null, modesRun.map((m) => {
          const v = pm[m] || {};
          return h("tr", null,
            h("th", { scope: "row" }, MODE_LABEL[m]),
            h("td", { class: "num" }, v.recall_at_5 === null || v.recall_at_5 === undefined ? "—" : pct(v.recall_at_5)),
            h("td", { class: "num" }, v.recall_at_k === null || v.recall_at_k === undefined ? "—" : pct(v.recall_at_k)),
            h("td", { class: "num" }, v.mrr === null || v.mrr === undefined ? "—" : pct(v.mrr)),
            h("td", { class: "num" }, v.groundedness === null || v.groundedness === undefined ? "Not applicable" : pct(v.groundedness)),
            h("td", { class: "num" }, `${num(v.latency_p50_ms, 0)} ms`));
        })))));

    put(results,
      h("div", { class: "run-head" },
        h("h2", null, "Latest run"),
        h("p", { class: "toolbar-note" }, `Run ${shortId(res.run_id)}, ${fmtWhen(res.generated_at)}. ${n} labelled question${n === 1 ? "" : "s"}, top ${k}, embedding ${res.embedding_model}.`),
        h("button", { class: "btn", type: "button", onclick: () => download(`aegisops-run-${res.run_id}.json`, JSON.stringify({ cases: evalState.cases, ...res }, null, 2), "application/json") }, "Download run (JSON)")),
      !semantic ? notice("warn", "Vector scores come from a test embedding",
        "The API is running a non-semantic embedding, so Meaning, Relationships and Both rank records by hashed text, not by meaning. Set EMBEDDING_PROVIDER=openai, re-project, and run again before quoting these numbers.",
        [navLink("Open System health", "system", {}, "btn")]) : null,
      unavailable.length ? notice("warn", "Some modes didn't run", unavailable.map(([m, why]) => `${MODE_LABEL[m]}: ${why}.`).join(" ") + " They are reported as not measured, not as zero.", [navLink("Open System health", "system", {}, "btn")]) : null,
      n && n < 20 ? notice("info", `Small sample: ${n} question${n === 1 ? "" : "s"}`,
        `Each question moves recall by about ${Math.round(100 / n)} percentage points. Label more questions before comparing modes or quoting results.`) : null,
      h("dl", { class: "readouts" },
        tile("Labelled questions", num(n), `Scored at top ${k}`),
        tile("Best recall", best ? pct(pm[best].recall_at_k) : "—", best ? `${MODE_LABEL[best]}, recall at ${k}` : "No mode measured"),
        tile("Cited sentences", typeof grounded === "number" ? pct(grounded) : "—", typeof grounded === "number" ? "Investigation answers with a citation per sentence" : "Investigation mode not run"),
        tile("Fastest median", fastest ? `${num(pm[fastest].latency_p50_ms, 0)} ms` : "—", fastest ? MODE_LABEL[fastest] : "No timing measured")),
      h("div", { class: "grid grid-2 viz-grid" }, metricChart, latencyChart),
      heat,
      tables,
    );
  };

  const exportJsonl = () => evalState.cases.map((c, i) => JSON.stringify({
    query_id: `q-${String(i + 1).padStart(3, "0")}`, query_text: c.question,
    fault_family: (items.find((m) => m.id === c.expected[0])?.asset_id || "unassigned"),
    relevant_memory_ids: c.expected, notes: "Labelled in the AegisOps console",
  })).join("\n") + "\n";

  put(main, head,
    notice("info", "Questions are saved in this browser only", "They aren't shared with other people or devices, and clearing site data removes them. Export queries.jsonl to keep them with the project."),
    !all.ok ? notice("crit", "Records can't be loaded", all.error) : null,
    pendingPanel(),
    results,
    h("h2", { class: "section-title" }, "Benchmark questions and run settings"),
    h("div", { class: "grid grid-2" },
      h("form", { class: "panel", onsubmit: (e) => {
        e.preventDefault();
        const question = q.value.trim();
        if (!question) return q.focus();
        const ids = [...expected.selectedOptions].map((o) => o.value);
        if (!ids.length) return toast("Pick at least one record a correct answer must use", true);
        evalState.cases.push({ question, expected: ids });
        saveEvalCases(); q.value = ""; expected.selectedIndex = -1; drawCases(); q.focus();
      } },
        h("h2", null, "Add a question"),
        h("div", { class: "field" }, h("label", { for: "e-q" }, "Question"), q),
        h("div", { class: "field" }, h("label", { for: "e-exp" }, "Records a correct answer must use"), expected, h("small", null, "Hold Ctrl or ⌘ to choose several")),
        h("div", null, h("button", { class: "btn", type: "submit" }, "Add question"))),
      h("div", { class: "panel" },
        h("h2", null, "Run"),
        modeBoxes,
        h("div", { class: "toolbar" }, h("div", { class: "field" }, h("label", { for: "e-k" }, "Top k"), kSel), run),
        h("p", { class: "toolbar-note" }, "To record results for a report, export the questions and run the CLI benchmark against the full stack:"),
        h("pre", { class: "cmd" }, "python -m evals.run_benchmark --queries evals/queries.jsonl --k 10"),
        h("div", { class: "page-actions" },
          h("button", { class: "btn", type: "button", onclick: () => evalState.cases.length ? download("queries.jsonl", exportJsonl(), "application/x-ndjson") : toast("Add a question first", true) }, "Export queries.jsonl"))),
    ),
    h("section", { "aria-label": "Benchmark questions" }, caseList),
  );
  drawCases();
  drawResults();
}
