import { busy, empty, fmtWhen, notice, num, pageHead, pct, scoreBar, shortId, skeleton, stateChip, toast, typeLabel } from "../components/ui.js";
import { dotWhisker, heatStep, logBars, withTooltip } from "../components/charts.js";
import { tabs } from "../components/tabs.js";
import { managerSummary } from "./evaluation-summary.js";
import { showMemory } from "../components/records.js";
import { bootstrapMean, evidenceStrength, leakage, shuffled } from "../lib/evalmath.js";
import { api, fetchAllMemories } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { evalState, href, main, navLink, saveEvalCases, state } from "../lib/state.js";

// Readout values must fit one line: the time is the value, the day goes in the note.
const runTime = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString(undefined, { timeStyle: "short" }); };
const runDay = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { dateStyle: "medium" }); };

/* -------------------------------------------------------- evaluation */

// Evaluation opens on a reliability overview, not a form. Labelling is an
// assisted review of pooled candidates; the standard profile runs every mode
// at top 10; mode and k overrides, the CLI command and raw downloads sit under
// Advanced. Everything here is exploratory: questions live in this browser
// and aren't reviewed or versioned (see the Evaluation Control Center design).

// Evidence strength inputs from the question set a run measured: only an
// approved (human-reviewed) version lifts the "console questions" limit.
export const setEvidence = (qs) => (qs && qs.status === "approved" ? { source: "reviewed", humanApproved: true } : { source: "console" });
// The question-set version the working list was loaded from, while unedited.
const workingSet = () => (evalState.setRef && !evalState.setRef.modified ? evalState.setRef : null);
const SET_STATUS = { draft: ["Draft", "info"], in_review: ["In review", "warn"], approved: ["Approved", "normal"], retired: ["Retired", "muted"], discarded: ["Discarded", "muted"] };
const NAME_KEY = "aegis-eval-name";
const myName = () => { try { return localStorage.getItem(NAME_KEY) || ""; } catch { return ""; } };
const rememberName = (v) => { try { localStorage.setItem(NAME_KEY, v); } catch {} };

// How the searched vectors were built, as counted in Qdrant at run time.
// More than one format means a rebuild was in progress: not a clean measurement.
const TEXT_FORMAT_LABEL = { plain: "Plain (title and text)", "context-header-1": "With context header", unrecorded: "Not recorded (older index)" };
export function searchText(run) {
  const it = Object.values(run.per_mode || {}).find((p) => p && p.index_text)?.index_text;
  if (!it) return "Not recorded";
  const keys = Object.keys(it);
  return keys.length === 1 ? TEXT_FORMAT_LABEL[keys[0]] || keys[0]
    : `Mixed: ${keys.map((k) => `${num(it[k])} ${(TEXT_FORMAT_LABEL[k] || k).toLowerCase()}`).join(", ")}`;
}

// Absence handling: did Investigation say "the records don't answer this"
// when none do, and avoid saying it when one does? A lexical check on the
// answer (app/evaluation/metrics.py is_abstention), shown with that caveat.
function abstentionPanel(ag) {
  if (!ag || !Array.isArray(ag.abstentions) || !ag.abstentions.length) return null;
  const no = ag.abstentions.filter((a) => a.expects_no_answer);
  const yes = ag.abstentions.filter((a) => !a.expects_no_answer);
  const said = no.filter((a) => a.abstained).length;
  const wrongly = yes.filter((a) => a.abstained).length;
  const missed = no.filter((a) => !a.abstained);
  return h("section", { class: "panel", "aria-labelledby": "ev-abst" },
    h("div", { class: "panel-head" }, h("div", null,
      h("h2", { id: "ev-abst" }, "Does Investigation admit when the records don't answer?"),
      h("p", null, "Checked from the answer's wording, so treat it as a screen, not proof."))),
    h("ul", { class: "summary-list" },
      no.length ? h("li", null, `Said so for ${said} of ${no.length} question${no.length === 1 ? "" : "s"} no record answers.`)
        : h("li", null, "No \u201cno record answers this\u201d questions yet. Add some under Questions and labels to test this."),
      yes.length ? h("li", null, `Wrongly said so for ${wrongly} of ${yes.length} question${yes.length === 1 ? "" : "s"} a record does answer.`) : null,
      ...missed.map((a) => h("li", null, `Answered anyway: \u201c${a.question}\u201d`))));
}

export const MODE_LABEL = { semantic: "Meaning", graph: "Relationships", hybrid: "Both", agentic: "Investigation" };
const STANDARD = { modes: ["semantic", "graph", "hybrid", "agentic"], k: 10 };
const RUN_KEY = "aegis-eval-last-run";
const SECONDS_PER_INVESTIGATION = 3; // measured ~2.7 s per question on 29 Oct 2026

function loadLastRun() {
  try { return JSON.parse(localStorage.getItem(RUN_KEY) || "null"); } catch { return null; }
}
function saveLastRun(run) {
  try { localStorage.setItem(RUN_KEY, JSON.stringify(run)); } catch {}
}

export async function viewEvaluation(params) {
  const head = pageHead("Evaluation", "Is retrieval finding the records a correct answer needs, and how sure can we be?");
  put(main, head, skeleton());
  const all = await fetchAllMemories({ status: "active" });
  const items = all.items || [];
  const byId = new Map(items.map((m) => [m.id, m]));
  const titleOf = (id) => byId.get(id)?.title || `record ${shortId(id)}`;
  // Older saved questions have no leak flag; work it out from their labels.
  const leakedCase = (c) => (typeof c.leaked === "boolean" ? c.leaked : leakage(c.question, c.expected.map(titleOf)).leaked);
  if (!evalState.results) evalState.results = loadLastRun();
  // Saved history (server): the newest saved run wins over this browser's copy.
  let history = { ok: false, runs: [] };
  const loadHistory = async () => {
    const r = await api("/evaluation/history", { params: { limit: 50 } });
    history = { ok: r.ok, runs: r.ok ? r.data.runs || [] : [], error: r.ok ? null : r.error };
    return history;
  };
  await loadHistory();
  const newest = history.runs[0];
  if (newest && (!evalState.results || String(newest.generated_at) > String(evalState.results.generated_at || ""))) {
    const full = await api(`/evaluation/history/${newest.run_id}`);
    if (full.ok) { evalState.results = full.data; saveLastRun(full.data); }
  }

  const results = h("div", { class: "stack", "aria-live": "polite" });
  const overviewHost = h("div", { class: "stack" });
  const questionsHost = h("div", { class: "stack" });
  const failuresHost = h("div", { class: "stack" });
  const runsHost = h("div", { class: "stack" });
  const summaryHost = h("div", { class: "stack" });
  const drawSummary = () => managerSummary(summaryHost, { latest: evalState.results, history: history.runs, items });
  const runDetail = h("div", { class: "stack", "aria-live": "polite" });

  const download = (name, text, type) => {
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
    document.body.append(a); a.click(); a.remove();
  };

  /* ---------------------------------------------------------- running */

  const runEvaluation = async (button, { modes, k }) => {
    if (!evalState.cases.length) return toast("Add at least one labelled question first", true);
    let use = modes;
    const slow = use.includes("agentic") && evalState.cases.length * SECONDS_PER_INVESTIGATION > 100;
    if (slow) use = use.filter((m) => m !== "agentic");
    busy(button, true);
    put(results, h("div", { class: "panel" }, h("p", null, `Running ${evalState.cases.length} question${evalState.cases.length === 1 ? "" : "s"} through ${use.map((m) => MODE_LABEL[m]).join(", ")}`), skeleton()));
    detail.select("overview");
    const r = await api("/evaluation/runs", { method: "POST", timeout: 120000, body: {
      cases: evalState.cases.map((c, i) => ({ case_id: `q-${String(i + 1).padStart(3, "0")}`, question: c.question, expected_memory_ids: c.noAnswer ? [] : c.expected, anchor_memory_id: c.anchor || null, expects_no_answer: !!c.noAnswer })),
      modes: use, k } });
    busy(button, false);
    if (!r.ok) return put(results, notice("crit", "The evaluation didn't run", r.error));
    evalState.results = r.data;
    saveLastRun(r.data);
    drawOverview();
    drawFailures();
    await loadHistory();
    const saved = history.runs.find((x) => x.run_id === r.data.run_id);
    if (saved) { evalState.results.question_set = saved.question_set; saveLastRun(evalState.results); drawOverview(); }
    drawRuns();
    drawSummary();
    if (!r.data.persisted) toast("This run wasn't saved to history (only writers and administrators save runs, or the history store is unavailable).", true);
    if (slow) toast("Investigation mode was left out: this many questions would pass the 2-minute limit. Run it from Advanced with fewer questions.", true);
  };

  /* ------------------------------------------------- latest run (charts) */

  const drawResults = (res = evalState.results, host = results) => {
    if (!res) return put(host);
    const k = res.k;
    const pm = res.per_mode || {};
    const modesRun = res.modes_run || [];
    const questions = [...new Set((res.cases || []).filter((c) => c.labeled !== false).map((c) => c.question))];
    const n = questions.length;
    const semantic = !/fake|hashedterm/i.test(res.embedding_model || "");
    const unavailable = Object.entries(res.unavailable_modes || {});
    const measured = (m, key) => typeof pm[m]?.[key] === "number";
    const best = modesRun.filter((m) => measured(m, "recall_at_k"))
      .sort((a, b) => pm[b].recall_at_k - pm[a].recall_at_k || (pm[b].mrr ?? 0) - (pm[a].mrr ?? 0)).at(0);
    const fastest = modesRun.filter((m) => measured(m, "latency_p50_ms")).sort((a, b) => pm[a].latency_p50_ms - pm[b].latency_p50_ms).at(0);
    // "groundedness" in the API is the share of answer sentences that carry a
    // citation; it is shown as citation coverage, which is what it measures.
    const grounded = pm.agentic?.groundedness;

    const tile = (label, value, note, sev) => h("div", { class: `readout${sev ? ` is-${sev}` : ""}` },
      h("dt", null, label), h("dd", null, value, h("span", { class: "readout-note" }, note)));

    // Per-mode means with 95% bootstrap intervals over questions.
    const perCase = (m, key) => (res.cases || []).filter((c) => c.mode === m && c.labeled !== false && !c.error).map((c) => c[key]);
    const ci = Object.fromEntries(modesRun.map((m) => [m, {
      recall5: bootstrapMean(perCase(m, "recall_at_5")),
      recall: bootstrapMean(perCase(m, "recall_at_k")),
      mrr: bootstrapMean(perCase(m, "mrr")),
    }]));
    const range = (c) => (!c ? "—" : c.lo === null ? `${pct(c.mean)}, no interval` : `${pct(c.mean)} (${pct(c.lo)} to ${pct(c.hi)})`);
    const caseFor = (q) => evalState.cases.find((c) => c.question === q);
    const leakedQs = questions.filter((q) => { const c = caseFor(q); return c ? leakedCase(c) : false; }).length;
    const strength = evidenceStrength({ n, semantic, leaked: leakedQs, ...setEvidence(res.question_set) });

    const metricChart = h("section", { class: "panel viz", "aria-labelledby": "ev-metrics" },
      h("div", { class: "panel-head" }, h("div", null,
        h("h2", { id: "ev-metrics" }, `Recall at ${k}, with how sure we are`),
        h("p", null, `Dot: share of labelled records found in the top ${k}, averaged over questions. Line: 95% interval from resampling the questions; a wide line means too few questions to tell modes apart.`))),
      withTooltip(h("div", { class: "chart-wrap" }, dotWhisker({
        rows: modesRun.map((m) => {
          const c = ci[m].recall;
          return { label: MODE_LABEL[m], mean: c?.mean, lo: c?.lo, hi: c?.hi, cls: m === best ? "is-s1" : "is-quiet",
            text: !c ? "not measured" : c.lo === null ? `${pct(c.mean)}, 1 question` : `${pct(c.mean)}  (${pct(c.lo)}–${pct(c.hi)})` };
        }),
        label: `Recall at ${k} for each retrieval mode with 95% bootstrap intervals`,
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
          h("th", { scope: "row" }, q, caseFor(q) && leakedCase(caseFor(q)) ? h("span", { class: "row-tags" }, h("span", { class: "tag tag-warn" }, "Repeats a record title")) : null),
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
        h("thead", null, h("tr", null, ["Mode", "Recall at 5 (95% interval)", `Recall at ${k} (95% interval)`, `MRR at ${k} (95% interval)`, "Citation coverage", "Latency p50"].map((c, i) => h("th", { scope: "col", class: i ? "num" : null }, c)))),
        h("tbody", null, modesRun.map((m) => {
          const v = pm[m] || {};
          return h("tr", null,
            h("th", { scope: "row" }, MODE_LABEL[m]),
            h("td", { class: "num" }, range(ci[m].recall5)),
            h("td", { class: "num" }, range(ci[m].recall)),
            h("td", { class: "num" }, range(ci[m].mrr)),
            h("td", { class: "num" }, v.groundedness === null || v.groundedness === undefined ? "Not applicable" : pct(v.groundedness)),
            h("td", { class: "num" }, `${num(v.latency_p50_ms, 0)} ms`));
        })))));

    put(host,
      h("div", { class: "run-head" },
        h("h2", null, "Latest run"),
        h("p", { class: "toolbar-note" }, `${fmtWhen(res.generated_at)}, ${res.persisted ? "saved to run history" : "kept in this browser only"}, ${n} question${n === 1 ? "" : "s"}.`)),
      !semantic ? notice("warn", "Vector scores come from a test embedding",
        "The API is running a non-semantic embedding, so Meaning, Relationships and Both rank records by hashed text, not by meaning. Set EMBEDDING_PROVIDER=openai, re-project, and run again before quoting these numbers.",
        [navLink("Open System health", "system", {}, "btn")]) : null,
      // With few records, the top k can hold most of them, so recall at k is
      // close to guaranteed; recall at 5 and MRR still discriminate.
      items.length && k >= items.length / 2 ? notice("warn", `Top ${k} covers ${k} of ${items.length} active records`,
        `Recall at ${k} is nearly guaranteed on a collection this small. Read Recall at 5 and MRR (how high the answer ranks) instead, or import the plant's work-order history for a meaningful test.`,
        [navLink("Import work orders", "import", {}, "btn")]) : null,
      unavailable.length ? notice("warn", "Some modes didn't run", unavailable.map(([m, why]) => `${MODE_LABEL[m]}: ${why}.`).join(" ") + " They are reported as not measured, not as zero.", [navLink("Open System health", "system", {}, "btn")]) : null,
      abstentionPanel(pm.agentic),
      h("dl", { class: "readouts" },
        tile("Evidence strength", strength.label, `${strength.why.join("; ")}. Use for: ${strength.level === "exploratory" ? "debugging only" : strength.level === "indicative" ? "internal comparison" : "gates and reports"}.`, strength.level === "exploratory" ? "warn" : null),
        tile("Labelled questions", num(n), `Scored at top ${k}${n ? `; one question moves recall ${Math.round(100 / n)} points` : ""}`),
        tile(`Recall at ${k}, best mode`, best && ci[best].recall ? pct(ci[best].recall.mean) : "—",
          !best ? "No mode measured" : ci[best].recall?.lo === null ? `${MODE_LABEL[best]}; one question, so no interval` : `${MODE_LABEL[best]}; 95% interval ${pct(ci[best].recall.lo)} to ${pct(ci[best].recall.hi)}`),
        tile("Citation coverage", typeof grounded === "number" ? pct(grounded) : "—", typeof grounded === "number" ? "Investigation answer sentences carrying a citation; not a check that they're true" : "Investigation mode not run"),
        tile("Fastest median", fastest ? `${num(pm[fastest].latency_p50_ms, 0)} ms` : "—", fastest ? MODE_LABEL[fastest] : "No timing measured")),
      h("div", { class: "grid grid-2 viz-grid" }, metricChart, latencyChart),
      heat,
      tables,
      h("details", { class: "panel raw" },
        h("summary", null, "Run details"),
        h("dl", { class: "facts" },
          [["Run", shortId(res.run_id)], ["Started", fmtWhen(res.generated_at)], ["Modes", modesRun.map((m) => MODE_LABEL[m]).join(", ")],
           ["Top k", String(k)], ["Embedding", res.embedding_model], ["Search text", searchText(res)], ["Questions", String(n)]].map(([t, v]) => [h("dt", null, t), h("dd", null, v)])),
        h("div", { class: "page-actions" },
          h("button", { class: "btn", type: "button", onclick: () => download(`aegisops-run-${res.run_id}.json`, JSON.stringify({ cases: evalState.cases, ...res }, null, 2), "application/json") }, "Download run (JSON)"))),
    );
  };


  /* ---------------------------------------------------------- overview */

  const drawOverview = () => {
    const cases = evalState.cases.filter((c) => !c.noAnswer);
    const n = cases.length;
    const leaked = cases.filter(leakedCase).length;
    const emb = state.health?.embedding_provider;
    const semantic = emb ? emb.semantic !== false : true;
    const strength = evidenceStrength({ n, semantic, leaked, ...setEvidence(workingSet()) });
    const records = new Set(cases.flatMap((c) => c.expected)).size;
    const runBtn = h("button", { class: "btn", type: "button", disabled: !n, onclick: (e) => runEvaluation(e.currentTarget, STANDARD) }, "Run standard evaluation");

    let action;
    if (!semantic) {
      action = { title: "Switch to a semantic embedding first", body: `The API is using ${emb?.name || "a test embedding"}, so Meaning, Relationships and Both rank records by hashed text. Set EMBEDDING_PROVIDER=openai in .env, rebuild, and re-project before trusting any score.`, button: navLink("Open System health", "system", {}, "btn btn-primary") };
    } else if (!n) {
      action = { title: "Label your first question", body: "Write a question the way an engineer would ask it, then tick the records a correct answer needs from pooled candidates.", button: h("button", { class: "btn btn-primary", type: "button", onclick: () => detail.select("questions") }, "Add a question") };
    } else if (leaked) {
      action = { title: `Rephrase ${leaked} flagged question${leaked === 1 ? "" : "s"}`, body: "They repeat a relevant record's title, so they test string matching, not retrieval.", button: h("button", { class: "btn btn-primary", type: "button", onclick: () => detail.select("questions") }, "Review questions") };
    } else if (n < 10) {
      action = { title: `Label ${10 - n} more question${10 - n === 1 ? "" : "s"}`, body: "Ten is the minimum for an indicative comparison of modes; thirty human-reviewed questions are needed for a decision.", button: h("button", { class: "btn btn-primary", type: "button", onclick: () => detail.select("questions") }, "Add questions") };
    } else {
      action = { title: "Run the standard evaluation", body: "All four modes at top 10 on your current questions.", button: h("button", { class: "btn btn-primary", type: "button", onclick: (e) => runEvaluation(e.currentTarget, STANDARD) }, "Run standard evaluation") };
    }

    put(overviewHost,
      h("section", { class: `panel readiness is-${strength.level}`, "aria-labelledby": "ready-title" },
        h("div", { class: "readiness-main" },
          h("p", { class: "prov-label" }, "Evidence strength of your current questions"),
          h("h2", { id: "ready-title" }, stateChip(strength.label, strength.sev)),
          h("ul", { class: "readiness-why" }, strength.why.map((w) => h("li", null, w.charAt(0).toUpperCase() + w.slice(1)))),
          h("p", { class: "toolbar-note" }, strength.level === "exploratory" ? "Good for debugging; not for comparing modes or reporting." : strength.level === "indicative" ? "Good for comparing modes internally, with intervals." : "Good for release decisions.")),
        h("div", { class: "readiness-next" },
          h("p", { class: "prov-label" }, "Recommended next action"),
          h("h3", null, action.title),
          h("p", null, action.body),
          h("div", { class: "page-actions" }, action.button, action.button.textContent === "Run standard evaluation" ? null : runBtn),
          h("p", { class: "cell-sub" }, "Standard profile: Meaning, Relationships, Both and Investigation at top 10. Change it under Advanced."))),
      h("dl", { class: "readouts" },
        h("div", { class: "readout" }, h("dt", null, "Labelled questions"), h("dd", null, num(n), h("span", { class: "readout-note" }, "Saved in this browser"))),
        h("div", { class: `readout${leaked ? " is-warn" : ""}` }, h("dt", null, "Flagged questions"), h("dd", null, num(leaked), h("span", { class: "readout-note" }, "Repeat a relevant record's title"))),
        h("div", { class: "readout" }, h("dt", null, "Records used as answers"), h("dd", null, num(records), h("span", { class: "readout-note" }, `Of ${num(items.length)} active records`))),
        h("div", { class: "readout" }, h("dt", null, "Latest run"), h("dd", null, evalState.results ? runTime(evalState.results.generated_at) : "None", h("span", { class: "readout-note" }, evalState.results ? `${runDay(evalState.results.generated_at)}, ${(evalState.results.modes_run || []).length} modes, top ${evalState.results.k}` : "Run to see results")))),
      results);
    if (evalState.results) drawResults();
    else put(results, empty("No evaluation run yet", "Label a few questions, then run the standard evaluation to see recall by mode with intervals."));
  };

  /* ------------------------------------------------ assisted labelling */

  // Candidates are pooled from all three retrieval modes, the starting
  // record's incident and asset, any evidence passed in and three random
  // records, then shuffled and shown without saying which mode found them, so
  // the labels don't inherit the system's blind spots.
  const candidatePicker = ({ question, anchor = null, evidence = [] }) => {
    const list = h("div", { class: "check-list candidate-list" }, skeleton());
    const leakNote = h("div");
    const chosen = new Set();
    const shown = new Set();
    const row = (m) => {
      shown.add(m.id);
      return h("label", { class: "check candidate" },
        h("input", { type: "checkbox", value: m.id, onchange: (e) => { if (e.target.checked) chosen.add(m.id); else chosen.delete(m.id); checkLeak(); } }),
        h("span", null, h("strong", null, m.title), h("span", { class: "cell-sub" }, `${typeLabel(m.memory_type)}${m.asset_id ? ` · ${m.asset_id}` : ""} · ${m.content.length > 150 ? `${m.content.slice(0, 150)}…` : m.content}`)));
    };
    const checkLeak = () => {
      const v = leakage(question, [...chosen].map(titleOf));
      put(leakNote, v.leaked ? notice("warn", "This question gives away its answer", `${v.reason}. Rephrase it the way an engineer would ask; otherwise it is kept but flagged and can't count as evidence.`) : null);
    };
    const searchAll = h("input", { type: "search", "aria-label": "Search all records", placeholder: "Not listed? Search all records by title" });
    const extra = h("div", { class: "check-list" });
    searchAll.addEventListener("input", () => {
      const f = searchAll.value.trim().toLowerCase();
      put(extra, f.length < 3 ? null : items.filter((m) => !shown.has(m.id) && m.title.toLowerCase().includes(f)).slice(0, 8).map(row));
    });
    (async () => {
      const pool = new Set(evidence);
      const modes = await Promise.all(["semantic", "graph", "hybrid"].map((mode) => api("/search/hybrid", { method: "POST", body: { query: question, mode, limit: 10 } })));
      for (const r of modes) if (r.ok) for (const x of r.data.results || []) pool.add(x.memory_id);
      const a = anchor ? byId.get(anchor) : null;
      if (a) for (const m of items) if ((a.incident_id && m.incident_id === a.incident_id) || (a.asset_id && m.asset_id === a.asset_id)) pool.add(m.id);
      for (const m of shuffled(items.filter((m) => !pool.has(m.id))).slice(0, 3)) pool.add(m.id);
      const cands = shuffled([...pool].map((id) => byId.get(id)).filter(Boolean));
      put(list, cands.length ? cands.map(row) : h("p", { class: "toolbar-note" }, "No candidate records found."));
    })();
    return {
      el: h("div", { class: "stack picker" },
        h("p", { class: "toolbar-note" }, "Tick only the records a correct answer must use. Candidates come from every search mode, the same incident and asset, and a few random records, in random order; nothing is ticked for you."),
        list, h("div", { class: "field" }, searchAll), extra, leakNote),
      chosen: () => [...chosen],
    };
  };

  const addCase = ({ question, ids, anchor = null, noAnswer = false }) => {
    const v = noAnswer ? { leaked: false } : leakage(question, ids.map(titleOf));
    evalState.cases.push({ question, expected: noAnswer ? [] : ids, anchor, noAnswer, leaked: v.leaked, label_method: "console", added_at: new Date().toISOString() });
    saveEvalCases();
    toast(noAnswer ? "Question added: no record answers it, so the right answer is to say so" : v.leaked ? "Question added, flagged as repeating a record title" : "Question added");
    drawQuestions();
    drawOverview();
  };

  /* --------------------------------------------------------- questions */

  const drawQuestions = () => {
    const p = evalState.pending;
    let pendingEl = null;
    if (p) {
      const picker = candidatePicker({ question: p.question, anchor: p.anchor, evidence: p.evidence || [] });
      pendingEl = h("section", { class: "panel", "aria-labelledby": "pend-title" },
        h("div", { class: "panel-head" }, h("h2", { id: "pend-title" }, "Label the question from your investigation")),
        h("p", { class: "inv-question" }, `“${p.question}”`),
        picker.el,
        h("div", { class: "page-actions" },
          h("button", { class: "btn btn-primary", type: "button", onclick: () => {
            const ids = picker.chosen();
            if (!ids.length) return toast("Tick at least one record, or discard the question", true);
            evalState.pending = null;
            addCase({ question: p.question, ids, anchor: p.anchor || null });
          } }, "Add labelled question"),
          h("button", { class: "btn", type: "button", onclick: () => {
            if (picker.chosen().length) return toast("Untick the records first: a no-answer question has none", true);
            evalState.pending = null;
            addCase({ question: p.question, ids: [], anchor: p.anchor || null, noAnswer: true });
          } }, "No record answers this"),
          h("button", { class: "btn", type: "button", onclick: () => { evalState.pending = null; drawQuestions(); } }, "Discard")));
    }

    const qInput = h("input", { type: "text", id: "e-q", autocomplete: "off", spellcheck: "true", placeholder: "e.g. Why are panels from the autoclave coming out porous?" });
    const qHint = h("p", { class: "field-hint", "aria-live": "polite" });
    qInput.addEventListener("input", () => {
      const v = /^\s*what do we know about:/i.test(qInput.value) ? leakage(qInput.value, []) : { leaked: false };
      put(qHint, v.leaked ? h("span", { class: "tag tag-warn" }, "This is the console's generated wording; write the question an engineer would ask") : null);
    });
    const pickerHost = h("div");
    let picker = null;
    const findBtn = h("button", { class: "btn btn-primary", type: "button", onclick: () => {
      const question = qInput.value.trim();
      if (!question) { qInput.setAttribute("aria-invalid", "true"); return qInput.focus(); }
      qInput.removeAttribute("aria-invalid");
      picker = candidatePicker({ question });
      put(pickerHost, picker.el, h("div", { class: "page-actions" },
        h("button", { class: "btn btn-primary", type: "button", onclick: () => {
          const ids = picker.chosen();
          if (!ids.length) return toast("Tick at least one record a correct answer needs", true);
          addCase({ question, ids });
        } }, "Add labelled question"),
        h("button", { class: "btn", type: "button", title: "Use this when you checked and no record answers the question. The assistant should then say it can't answer.", onclick: () => {
          if (picker.chosen().length) return toast("Untick the records first: a no-answer question has none", true);
          addCase({ question, ids: [], noAnswer: true });
        } }, "No record answers this"),
        h("button", { class: "btn", type: "button", onclick: () => { put(pickerHost); picker = null; } }, "Cancel")));
    } }, "Find candidate records");

    const list = evalState.cases.length
      ? h("div", { class: "table-wrap" }, h("table", null,
          h("caption", null, `${evalState.cases.length} labelled question${evalState.cases.length === 1 ? "" : "s"}, saved in this browser and not yet reviewed`),
          h("thead", null, h("tr", null, h("th", { scope: "col" }, "Question"), h("th", { scope: "col" }, "Records a correct answer needs"), h("th", { scope: "col" }, h("span", { class: "visually-hidden" }, "Actions")))),
          h("tbody", null, evalState.cases.map((c, i) => h("tr", null,
            h("td", null, c.question,
              leakedCase(c) || c.label_method === "assistant-proposed" ? h("span", { class: "row-tags" },
                leakedCase(c) ? h("span", { class: "tag tag-warn" }, "Repeats a record title") : null,
                c.label_method === "assistant-proposed" ? h("span", { class: "tag tag-trust is-caution", title: "Labels proposed by the assistant. Check them against the records before this set is approved." }, "Proposed labels: check") : null) : null,
              c.note ? h("span", { class: "cell-sub" }, c.note) : null),
            h("td", null, c.noAnswer ? h("span", { class: "cell-sub" }, "None: no record answers this, so the assistant should say so")
              : h("ul", { class: "plain-list" }, c.expected.map((id) => h("li", null, h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(id) }, titleOf(id)))))),
            h("td", { class: "num" }, h("button", { class: "btn btn-quiet", type: "button", onclick: () => { evalState.cases.splice(i, 1); saveEvalCases(); drawQuestions(); drawOverview(); } }, "Remove")))))))
      : empty("No labelled questions yet", "Add one above, or use Add to benchmark from an investigation.");

    const setsHost = h("div", { class: "stack" });
    drawSets(setsHost);

    put(questionsHost,
      pendingEl,
      setsHost,
      h("section", { class: "panel", "aria-labelledby": "add-title" },
        h("div", { class: "panel-head" }, h("div", null, h("h2", { id: "add-title" }, "Add a question"),
          h("p", null, "Ask it the way an engineer would, without copying a record's title. AegisOps then pools candidate records for you to judge."))),
        h("div", { class: "toolbar" }, h("div", { class: "field field-grow" }, h("label", { for: "e-q" }, "Question"), qInput), findBtn),
        qHint, pickerHost),
      list,
      notice("info", "The working list is kept in this browser", "Save it as a question set to version it, share it and have it reviewed. Only an approved set counts as reviewed evidence."));
  };

  /* ------------------------------------------- versioned question sets */

  // Server-side, versioned question sets with a review step. The working list
  // above stays in the browser; saving it creates a draft version, and a run
  // is tied to a set version when its questions and labels match exactly.
  const toServer = (c) => ({ question: c.question, expected_memory_ids: c.noAnswer ? [] : c.expected, anchor_memory_id: c.anchor || null,
    expects_no_answer: !!c.noAnswer, labeling_method: c.label_method || "console", note: c.note || null });
  let confirmLoad = null;
  const loadSet = async (summary) => {
    const unsaved = evalState.cases.length && !workingSet();
    if (unsaved && confirmLoad !== summary.id) {
      confirmLoad = summary.id;
      return toast(`The working list has ${evalState.cases.length} unsaved question${evalState.cases.length === 1 ? "" : "s"}. Save it as a set first, or select Load again to replace it.`, true);
    }
    confirmLoad = null;
    const r = await api(`/evaluation/question-sets/${summary.id}`);
    if (!r.ok) return toast(r.error, true);
    const S = r.data;
    evalState.cases = S.questions.map((q) => ({ question: q.question, expected: q.expected_memory_ids, anchor: q.anchor_memory_id,
      noAnswer: q.expects_no_answer, leaked: q.leaked, label_method: q.labeling_method, note: q.note }));
    evalState.setRef = { id: S.id, name: S.name, version: S.version, status: S.status, hash: S.content_hash, modified: false };
    saveEvalCases({ keepSet: true });
    toast(`Loaded ${S.name} v${S.version} (${SET_STATUS[S.status][0].toLowerCase()})`);
    drawQuestions(); drawOverview();
  };

  const drawSets = async (host) => {
    put(host, h("div", { class: "panel" }, skeleton()));
    const r = await api("/evaluation/question-sets");
    if (!r.ok) return put(host, notice("warn", "Question sets are unavailable", `${r.error}. If the API was just updated, apply the database migration (alembic upgrade head).`));
    const sets = r.data.sets || [];
    const ws = evalState.setRef;
    const nameIn = h("input", { type: "text", id: "qs-name", autocomplete: "off", value: ws?.name || "", placeholder: "e.g. MaintNet engines" });
    const authorIn = h("input", { type: "text", id: "qs-author", autocomplete: "name", value: myName(), placeholder: "Your name" });
    const actionHost = h("div");
    // An unedited copy of a loaded version would only duplicate it.
    const unchanged = !!workingSet();
    const saveBtn = h("button", { class: "btn btn-primary", type: "button", disabled: !evalState.cases.length || unchanged,
      title: unchanged ? "The working list is exactly the loaded version; edit it first to save a new version" : null, onclick: async (e) => {
      const name = nameIn.value.trim(), author = authorIn.value.trim();
      if (!name || !author) return toast("Give the set a name and say who you are", true);
      rememberName(author);
      const draft = sets.find((x) => x.name === name && x.status === "draft");
      busy(e.currentTarget, true);
      const res = draft
        ? await api(`/evaluation/question-sets/${draft.id}/questions`, { method: "PUT", body: { questions: evalState.cases.map(toServer) } })
        : await api("/evaluation/question-sets", { method: "POST", body: { name, author, questions: evalState.cases.map(toServer) } });
      busy(e.currentTarget, false);
      if (!res.ok) return toast(res.error, true);
      evalState.setRef = { id: res.data.id, name: res.data.name, version: res.data.version, status: res.data.status, hash: res.data.content_hash, modified: false };
      saveEvalCases({ keepSet: true });
      toast(draft ? `Updated draft ${name} v${res.data.version}` : `Saved ${name} v${res.data.version} as a draft`);
      drawQuestions(); drawOverview();
    } }, unchanged ? "No changes to save" : "Save working list as a set");

    const review = (S, action) => {
      const who = h("input", { type: "text", autocomplete: "name", value: action === "submit" ? myName() : "", "aria-label": "Your name" });
      const note = h("input", { type: "text", "aria-label": "Note", placeholder: action === "return" ? "What needs changing" : "Optional note" });
      const label = { submit: "Submit for review", approve: "Approve", return: "Return to author", retire: "Retire", discard: "Discard draft" }[action];
      put(actionHost, h("div", { class: "panel review-form" },
        h("p", null, h("strong", null, `${label}: ${S.name} v${S.version}`),
          action === "approve" ? " Approve only after checking every question's labels against the records. You must not be the author." : "",
          action === "approve" && evalState.setRef?.id === S.id && evalState.cases.some((c) => c.label_method === "assistant-proposed")
            ? " Its labels were proposed by the assistant: approving says you checked each one yourself." : ""),
        h("div", { class: "toolbar" },
          h("div", { class: "field" }, h("label", null, "Your name"), who),
          h("div", { class: "field field-grow" }, h("label", null, "Note"), note),
          h("button", { class: "btn btn-primary", type: "button", onclick: async (e) => {
            if (!who.value.trim()) return toast("Say who you are", true);
            busy(e.currentTarget, true);
            const res = await api(`/evaluation/question-sets/${S.id}/${action}`, { method: "POST", body: { by: who.value.trim(), note: note.value.trim() || null } });
            busy(e.currentTarget, false);
            if (!res.ok) return toast(res.error, true);
            if (action === "submit") rememberName(who.value.trim());
            if (evalState.setRef?.id === S.id) { evalState.setRef = { ...evalState.setRef, status: res.data.status }; saveEvalCases({ keepSet: true }); }
            toast(`${S.name} v${S.version} is now ${SET_STATUS[res.data.status][0].toLowerCase()}`);
            drawQuestions(); drawOverview();
          } }, label),
          h("button", { class: "btn", type: "button", onclick: () => put(actionHost) }, "Cancel"))));
    };

    put(host, h("section", { class: "panel", "aria-labelledby": "qs-title" },
      h("div", { class: "panel-head" }, h("div", null,
        h("h2", { id: "qs-title" }, "Question sets"),
        h("p", null, "Versioned and reviewed. Draft → in review → approved; approved versions are frozen, and changes make a new version."))),
      ws ? h("p", { class: "toolbar-note" }, `Working list: ${ws.name} v${ws.version} (${SET_STATUS[ws.status]?.[0].toLowerCase() || ws.status})${ws.modified ? ", edited since loading, so runs won't count as that version" : ""}.`) : null,
      sets.length ? h("div", { class: "table-wrap" }, h("table", null,
        h("thead", null, h("tr", null, ["Set", "Status", "Questions", "Author", "Reviewed by", ""].map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", null, sets.map((S) => h("tr", null,
          h("td", null, h("span", { class: "cell-title" }, `${S.name} v${S.version}`), h("span", { class: "cell-sub" }, `#${S.content_hash.slice(0, 8)}`)),
          h("td", null, stateChip(...(SET_STATUS[S.status] || [S.status, "info"])), S.review_note ? h("span", { class: "cell-sub" }, S.review_note) : null),
          h("td", null, num(S.question_count)),
          h("td", null, S.created_by),
          h("td", null, S.reviewed_by ? `${S.reviewed_by}, ${fmtWhen(S.reviewed_at)}` : "—"),
          h("td", null, h("div", { class: "row-actions" },
            h("button", { class: "btn btn-quiet", type: "button", onclick: () => loadSet(S) }, "Load"),
            S.status === "draft" ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => review(S, "submit") }, "Submit for review") : null,
            S.status === "draft" ? h("button", { class: "btn btn-quiet", type: "button", title: "Set this draft aside. It is kept for the record but never used or credited to a run.", onclick: () => review(S, "discard") }, "Discard") : null,
            S.status === "in_review" ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => review(S, "approve") }, "Approve") : null,
            S.status === "in_review" ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => review(S, "return") }, "Return") : null,
            S.status === "approved" ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => review(S, "retire") }, "Retire") : null))))))) : null,
      actionHost,
      h("div", { class: "toolbar" },
        h("div", { class: "field field-grow" }, h("label", { for: "qs-name" }, "Set name"), nameIn),
        h("div", { class: "field" }, h("label", { for: "qs-author" }, "Your name"), authorIn),
        saveBtn),
      h("p", { class: "toolbar-note" }, "Saving under an existing name updates its draft, or starts the next version after the last one was submitted. Names are recorded as given; user accounts are not set up yet.")));
  };

  /* -------------------------------------------------- failure analysis */

  // Factual diagnosis from this run alone: whether the expected record is
  // still active, and whether another mode found it. Projection checks
  // (is it in Qdrant or Neo4j?) need the server and come later.
  const drawFailures = () => {
    const res = evalState.results;
    if (!res) return put(failuresHost, empty("No run to analyse", "Run an evaluation first; misses appear here with what is known about each."));
    const k = res.k;
    const cases = (res.cases || []).filter((c) => c.labeled !== false);
    // Saved runs carry their own labels; older browser runs fall back to the current questions.
    const expectedOf = (q, row) => row?.expected_memory_ids?.length ? row.expected_memory_ids : evalState.cases.find((c) => c.question === q)?.expected || [];
    const foundBy = (q, id) => cases.filter((c) => c.question === q && (c.retrieved_memory_ids || []).slice(0, k).includes(id)).map((c) => MODE_LABEL[c.mode]);
    const misses = cases.filter((c) => c.error || c.recall_at_k < 1).map((c) => {
      const exp = expectedOf(c.question, c);
      const missing = exp.filter((id) => !(c.retrieved_memory_ids || []).slice(0, k).includes(id));
      let diagnosis;
      if (c.error) diagnosis = ["Run error", c.error];
      else if (missing.some((id) => !byId.has(id))) diagnosis = ["Label is stale", "An expected record is no longer active"];
      else {
        const others = [...new Set(missing.flatMap((id) => foundBy(c.question, id)))];
        diagnosis = others.length ? ["Another mode found it", `Found by ${others.join(", ")}`] : ["No mode found it", `Not in any mode's top ${k}`];
      }
      return { c, missing, diagnosis, first: (c.retrieved_memory_ids || [])[0] };
    });
    const counts = {};
    for (const m of misses) counts[m.diagnosis[0]] = (counts[m.diagnosis[0]] || 0) + 1;
    put(failuresHost,
      h("dl", { class: "readouts" }, ["No mode found it", "Another mode found it", "Label is stale", "Run error"].map((d) =>
        h("div", { class: `readout${counts[d] ? " is-warn" : ""}` }, h("dt", null, d), h("dd", null, num(counts[d] || 0), h("span", { class: "readout-note" }, "question × mode misses"))))),
      misses.length
        ? h("div", { class: "table-wrap" }, h("table", null,
            h("caption", null, `${misses.length} miss${misses.length === 1 ? "" : "es"} in the latest run (top ${k}). Not yet checked: whether the missing record is projected into Qdrant and Neo4j.`),
            h("thead", null, h("tr", null, ["Question", "Mode", "What we know", "Missing record", "Ranked first instead", ""].map((c) => h("th", { scope: "col" }, c)))),
            h("tbody", null, misses.map(({ c, missing, diagnosis, first }) => h("tr", null,
              h("td", null, c.question),
              h("td", null, MODE_LABEL[c.mode]),
              h("td", null, h("strong", null, diagnosis[0]), h("span", { class: "cell-sub" }, diagnosis[1])),
              h("td", null, h("ul", { class: "plain-list" }, missing.map((id) => h("li", null, h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(id) }, titleOf(id)))))),
              h("td", null, first ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(first) }, titleOf(first)) : "Nothing returned"),
              h("td", null, c.mode === "agentic" ? navLink("Investigate", "investigate", { q: c.question }) : navLink("Search", "search", { q: c.question, mode: c.mode })))))))
        : empty("No misses", "Every labelled record was found by every mode in the latest run."));
  };

  /* -------------------------------------------------------------- runs */

  // Saved runs, newest first. A run can be reopened, or compared with the
  // previous run measured the same way (same embedding and top k): runs made
  // differently are never compared directly.
  const bestOf = (run) => {
    const pm = run.per_mode || {};
    const m = (run.modes_run || []).filter((x) => typeof pm[x]?.recall_at_k === "number").sort((a, b) => pm[b].recall_at_k - pm[a].recall_at_k).at(0);
    return m ? { mode: m, recall: pm[m].recall_at_k, mrr: pm[m].mrr } : null;
  };
  // Investigation runs written from a different number of records are not comparable.
  const comparable = (a, b) => a.k === b.k && a.embedding_model === b.embedding_model
    && (a.per_mode?.agentic?.context_limit ?? null) === (b.per_mode?.agentic?.context_limit ?? null);

  const openRun = async (summary) => {
    put(runDetail, h("div", { class: "panel" }, skeleton()));
    const r = await api(`/evaluation/history/${summary.run_id}`);
    if (!r.ok) return put(runDetail, notice("crit", "That run couldn't be loaded", r.error));
    const host = h("div", { class: "stack" });
    put(runDetail, h("div", { class: "page-actions" },
      h("button", { class: "btn", type: "button", onclick: () => { evalState.results = r.data; saveLastRun(r.data); drawOverview(); drawFailures(); detail.select("failures"); } }, "Analyse failures in this run")), host);
    drawResults(r.data, host);
    runDetail.scrollIntoView({ block: "start" });
  };

  const compareRuns = async (newer, older) => {
    put(runDetail, h("div", { class: "panel" }, skeleton()));
    const [a, b] = await Promise.all([api(`/evaluation/history/${newer.run_id}`), api(`/evaluation/history/${older.run_id}`)]);
    if (!a.ok || !b.ok) return put(runDetail, notice("crit", "Couldn't load both runs", (a.ok ? b : a).error));
    const A = a.data, B = b.data, k = A.k;
    const key = (c) => `${c.mode}\u0000${c.question}`;
    const before = new Map(B.cases.filter((c) => c.labeled !== false && !c.error).map((c) => [key(c), c]));
    const pairs = A.cases.filter((c) => c.labeled !== false && !c.error && before.has(key(c))).map((c) => ({ now: c, then: before.get(key(c)) }));
    const modes = (A.modes_run || []).filter((m) => (B.modes_run || []).includes(m));
    const rankOf = (c) => (c.mrr ? Math.round(1 / c.mrr) : null);
    const verdict = (p) => (p.now.recall_at_k > p.then.recall_at_k || (p.now.recall_at_k === p.then.recall_at_k && p.now.mrr > p.then.mrr) ? "better"
      : p.now.recall_at_k < p.then.recall_at_k || (p.now.recall_at_k === p.then.recall_at_k && p.now.mrr < p.then.mrr) ? "worse" : "same");
    const rows = modes.map((m) => {
      const ps = pairs.filter((p) => p.now.mode === m);
      const diff = bootstrapMean(ps.map((p) => p.now.recall_at_k - p.then.recall_at_k));
      const count = (v) => ps.filter((p) => verdict(p) === v).length;
      return { m, n: ps.length, diff, better: count("better"), worse: count("worse"), same: count("same") };
    });
    const signed = (v) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.round(Math.abs(v) * 100)} pts`;
    const changed = pairs.filter((p) => verdict(p) !== "same");
    put(runDetail,
      h("section", { class: "panel", "aria-labelledby": "cmp-runs" },
        h("div", { class: "panel-head" }, h("div", null,
          h("h2", { id: "cmp-runs" }, "What changed between these runs"),
          h("p", null, `${fmtWhen(A.generated_at)} compared with ${fmtWhen(B.generated_at)}. Only questions asked in both runs are compared, question by question.`),
          searchText(A) !== searchText(B) ? h("p", null, h("strong", null, "Search text changed: "), `${searchText(B)} → ${searchText(A)}.`) : null)),
        [A, B].some((x) => searchText(x).startsWith("Mixed")) ? notice("warn", "One run searched a partly rebuilt index", "Vectors from different search-text formats were mixed, so differences can't be put down to either format. Rerun after the rebuild finishes.") : null,
        !pairs.length ? notice("info", "No questions in common", "These runs share no labelled questions, so there is nothing to compare question by question.") : null,
        h("div", { class: "table-wrap" }, h("table", null,
          h("thead", null, h("tr", null, ["Mode", "Questions in both", `Change in recall at ${k} (95% interval)`, "Better", "Worse", "Same"].map((c, i) => h("th", { scope: "col", class: i ? "num" : null }, c)))),
          h("tbody", null, rows.map((r) => h("tr", null,
            h("th", { scope: "row" }, MODE_LABEL[r.m]),
            h("td", { class: "num" }, String(r.n)),
            h("td", { class: "num" }, !r.diff ? "—" : r.diff.lo === null ? `${signed(r.diff.mean)} (1 question)` : `${signed(r.diff.mean)} (${signed(r.diff.lo)} to ${signed(r.diff.hi)})`),
            h("td", { class: "num" }, String(r.better)), h("td", { class: "num" }, String(r.worse)), h("td", { class: "num" }, String(r.same))))))),
        h("p", { class: "toolbar-note" }, "An interval that includes ±0 means the change could be noise at this sample size. Better or worse counts recall first, then how high the first relevant record ranked."),
        changed.length ? h("div", { class: "table-wrap" }, h("table", null,
          h("caption", null, `${changed.length} question × mode result${changed.length === 1 ? "" : "s"} changed`),
          h("thead", null, h("tr", null, ["Question", "Mode", "Then", "Now", ""].map((c) => h("th", { scope: "col" }, c)))),
          h("tbody", null, changed.map((p) => h("tr", null,
            h("td", null, p.now.question), h("td", null, MODE_LABEL[p.now.mode]),
            h("td", null, `${pct(p.then.recall_at_k)}${rankOf(p.then) ? `, first at #${rankOf(p.then)}` : ""}`),
            h("td", null, `${pct(p.now.recall_at_k)}${rankOf(p.now) ? `, first at #${rankOf(p.now)}` : ""}`),
            h("td", null, verdict(p) === "better" ? stateChip("Better", "normal") : stateChip("Worse", "warn"))))))) : null));
    runDetail.scrollIntoView({ block: "start" });
  };

  const drawRuns = () => {
    if (!history.ok) return put(runsHost, notice("warn", "Run history is unavailable", `${history.error || "The history endpoint didn't answer."} If the API was just updated, apply the database migration (alembic upgrade head).`));
    const runs = history.runs;
    if (!runs.length) return put(runsHost, empty("No saved runs yet", "Every evaluation you run from now on is saved here, so you can reopen it and compare it with the next one."), runDetail);
    put(runsHost,
      h("div", { class: "table-wrap" }, h("table", null,
        h("caption", null, `${runs.length} saved run${runs.length === 1 ? "" : "s"}, newest first`),
        h("thead", null, h("tr", null, ["Run", "Questions", "Modes", "Top k", "Embedding", "Search text", "Best recall at k", "Evidence", ""].map((c) => h("th", { scope: "col" }, c)))),
        h("tbody", null, runs.map((run, i) => {
          const best = bestOf(run);
          const strength = evidenceStrength({ n: run.question_count, semantic: !/fake|hashedterm/i.test(run.embedding_model || ""), ...setEvidence(run.question_set) });
          const prev = runs.slice(i + 1).find((o) => comparable(run, o));
          return h("tr", null,
            h("td", null, h("span", { class: "cell-title" }, fmtWhen(run.generated_at)), h("span", { class: "cell-sub" }, `${run.source || "console"}, ${shortId(run.run_id)}`)),
            h("td", null, num(run.question_count)),
            h("td", null, (run.modes_run || []).map((m) => MODE_LABEL[m]).join(", ")),
            h("td", null, String(run.k)),
            h("td", null, String(run.embedding_model || "").replace(/\(.*\)$/, "")),
            h("td", null, searchText(run)),
            h("td", null, best ? `${pct(best.recall)} (${MODE_LABEL[best.mode]})` : "—"),
            h("td", null, stateChip(strength.label, strength.sev)),
            h("td", null, h("div", { class: "row-actions" },
              h("button", { class: "btn btn-quiet", type: "button", onclick: () => openRun(run) }, "Open"),
              prev ? h("button", { class: "btn btn-quiet", type: "button", onclick: () => compareRuns(run, prev) }, "Compare with previous")
                : h("span", { class: "cell-sub", title: "No earlier run with the same embedding and top k" }, "No comparable earlier run"))));
        })))),
      runDetail);
  };

  /* ---------------------------------------------------------- advanced */

  const kSel = h("select", { id: "e-k" }, [5, 10, 20].map((n) => h("option", { value: n, selected: n === 10 }, String(n))));
  const modeBoxes = h("fieldset", null, h("legend", null, "Modes"),
    h("div", { class: "toolbar" }, Object.entries(MODE_LABEL).map(([v, l]) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "emode", value: v, checked: true }), l))));
  const customRun = h("button", { class: "btn", type: "button", onclick: () => {
    const modes = [...modeBoxes.querySelectorAll("input:checked")].map((i) => i.value);
    if (!modes.length) return toast("Choose at least one mode", true);
    runEvaluation(customRun, { modes, k: Number(kSel.value) });
  } }, "Run with these settings");

  const exportJsonl = () => evalState.cases.map((c, i) => JSON.stringify({
    query_id: `q-${String(i + 1).padStart(3, "0")}`, query_text: c.question,
    // Fault family is a reviewer's judgement; the console doesn't guess it.
    fault_family: c.fault_family || "unassigned",
    relevant_memory_ids: c.expected,
    labeling_method: "console",
    notes: `Labelled in the AegisOps console; not yet reviewed${leakedCase(c) ? "; question repeats a record title" : ""}`,
  })).join("\n") + "\n";

  const advanced = h("div", { class: "grid grid-2" },
    h("section", { class: "panel", "aria-labelledby": "adv-run" },
      h("h2", { id: "adv-run" }, "Custom run"),
      h("p", { class: "toolbar-note" }, "Override the standard profile for a one-off check. Results replace the latest run and stay exploratory."),
      modeBoxes,
      h("div", { class: "toolbar" }, h("div", { class: "field" }, h("label", { for: "e-k" }, "Top k"), kSel), customRun)),
    h("section", { class: "panel", "aria-labelledby": "adv-rec" },
      h("h2", { id: "adv-rec" }, "Record a run for a report"),
      h("p", { class: "toolbar-note" }, "The command-line benchmark measures latency properly (warm-up, five repeats) and writes result files with the dataset hash. Export the questions, copy them into the API container, then run:"),
      h("pre", { class: "cmd" }, "docker cp queries.jsonl aegisops-api:/app/evals/queries.jsonl\ndocker compose exec api python -m evals.validate_queries --file evals/queries.jsonl\ndocker compose exec api python -m evals.run_benchmark --queries evals/queries.jsonl --k 10"),
      h("div", { class: "page-actions" },
        h("button", { class: "btn", type: "button", onclick: () => evalState.cases.length ? download("queries.jsonl", exportJsonl(), "application/x-ndjson") : toast("Add a question first", true) }, "Export queries.jsonl"),
        h("button", { class: "btn", type: "button", disabled: !evalState.results, onclick: () => download(`aegisops-run-${evalState.results.run_id}.json`, JSON.stringify({ cases: evalState.cases, ...evalState.results }, null, 2), "application/json") }, "Download latest run (JSON)"))));

  /* ------------------------------------------------------------ layout */

  const detail = tabs([
    { id: "overview", label: "Overview", panel: overviewHost },
    { id: "summary", label: "Summary for managers", panel: summaryHost },
    { id: "runs", label: "Runs", panel: runsHost },
    { id: "questions", label: `Questions and labels`, panel: questionsHost },
    { id: "failures", label: "Failure analysis", panel: failuresHost },
    { id: "advanced", label: "Advanced", panel: advanced },
  ], "Evaluation sections");

  put(main, head, !all.ok ? notice("crit", "Records can't be loaded", all.error) : null, detail.el);
  drawOverview();
  drawQuestions();
  drawFailures();
  drawRuns();
  drawSummary();
  const want = evalState.pending ? "questions" : params?.get?.("tab");
  if (want && ["overview", "summary", "runs", "questions", "failures", "advanced"].includes(want)) detail.select(want);
}
