import { closeDialog, openDialog } from "../components/dialog.js";
import { clearInvalid, formField, markInvalid, memoryForm, showMemory } from "../components/records.js";
import { SOURCE_LABEL, busy, empty, metaPair, notice, num, pageHead, pct, shortId, skeleton, stateChip, toast, typeLabel } from "../components/ui.js";
import { api, showSignIn } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { capable, evalState, go, href, main, navLink, services } from "../lib/state.js";

/* ------------------------------------------------------- investigate */

export async function viewInvestigate(params) {
  const anchor = params.get("anchor") || "";
  const q = params.get("q") || "";
  const svc = services();
  const out = h("div", { class: "stack", "aria-live": "polite" });

  const question = h("textarea", { id: "ask-q", name: "question", rows: 3, required: true, placeholder: "e.g. Why are drill cell DC-3 holes oversize, and what fixed it last time?" }, q);
  const limit = h("select", { id: "ask-limit" }, [3, 5, 8, 10].map((n) => h("option", { value: n, selected: n === 5 }, `${n} records`)));
  const askBtn = h("button", { class: "btn btn-primary", type: "submit" }, "Investigate");
  const anchorNote = h("p", { class: "field-grow toolbar-note" });

  if (anchor) {
    put(anchorNote, "Starting from a record ");
    api(`/memories/${anchor}`).then((r) => {
      put(anchorNote, "Starting from ",
        h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(anchor) }, r.ok ? r.data.title : `record ${shortId(anchor)}`),
        " ", h("a", { href: href("investigate", { q: question.value }) }, "Clear"));
    });
  }

  const form = h("form", { class: "panel", onsubmit: async (e) => {
    e.preventDefault();
    const text = question.value.trim();
    if (!text) { question.setAttribute("aria-invalid", "true"); question.focus(); return; }
    question.removeAttribute("aria-invalid");
    history.replaceState(null, "", href("investigate", { q: text, anchor }));
    busy(askBtn, true);
    put(out, h("div", { class: "panel" }, skeleton()));
    const r = await api("/investigations", { method: "POST", timeout: 60000, body: { question: text, context_limit: Number(limit.value), anchor_memory_id: anchor || null } });
    busy(askBtn, false);
    if (!r.ok) return put(out, notice("crit", "The investigation didn't complete", r.error));
    put(out, ...renderInvestigation(r.data, anchor));
  } },
    h("div", { class: "field" }, h("label", { for: "ask-q" }, "Question"), question),
    h("div", { class: "toolbar" },
      h("div", { class: "field" }, h("label", { for: "ask-limit" }, "Use up to"), limit),
      anchor ? anchorNote : h("span", { class: "field-grow" }),
      askBtn),
  );

  const warnings = [];
  if (!capable("qdrant") && !capable("neo4j")) warnings.push(notice("warn", "Vector and graph search are offline", "Investigations will use keyword matches from PostgreSQL until Qdrant or Neo4j is back.", [navLink("Open System health", "system", {}, "btn")]));
  else if (!capable("neo4j")) warnings.push(notice("warn", "Relationship store is offline", "Investigations use vector matches only; graph links return when Neo4j reconnects."));
  if (svc.llm?.synthetic) warnings.push(notice("info", "Answers come from the deterministic test provider", "It lists the retrieved records with citations and adds no reasoning. Set LLM_PROVIDER=openai and OPENAI_API_KEY for model-written answers."));

  put(main, pageHead("Investigate", "Ask about an asset, symptom or incident. The answer cites canonical records, shows how it was built, and is checked before you record anything."), ...warnings, form, out);
  if (q) form.requestSubmit(); else question.focus();
}

export function renderInvestigation(d, anchor) {
  const parts = [];
  const re = /\[Memory\s+(\d+)\]/g;
  let last = 0;
  let m;
  while ((m = re.exec(d.answer))) {
    parts.push(d.answer.slice(last, m.index));
    const n = Number(m[1]);
    parts.push(n >= 1 && n <= d.evidence.length
      ? h("a", { class: "cite", href: `#ev-${n}`, onclick: (e) => { e.preventDefault(); const el = document.getElementById(`ev-${n}`); el.scrollIntoView({ block: "center" }); el.focus(); } }, `Record ${n}`)
      : h("span", { class: "cite" }, `Record ${n} (not in evidence)`));
    last = m.index + m[0].length;
  }
  parts.push(d.answer.slice(last));

  const critic = d.critic || {};
  const verdict = critic.is_supported ? stateChip("Citations verified", "normal") : stateChip("Not verified", "warn");
  const modeNote = d.retrieval_mode === "keyword_fallback"
    ? notice("warn", "Matched by keywords", "Vector and graph stores returned nothing, so evidence was matched by words in PostgreSQL. Treat the ranking as approximate.")
    : null;
  const canRecord = d.evidence.length > 0;

  const answer = h("section", { class: "panel", "aria-labelledby": "ans-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "ans-title" }, "Answer"), h("span", { class: "page-actions" }, d.is_synthetic_response ? stateChip("Test provider", "info") : h("span", { class: "tag" }, d.model_name), verdict)),
    modeNote,
    h("p", { class: "answer" }, parts),
    !critic.is_supported && critic.notes ? h("p", { class: "toolbar-note" }, `Check: ${critic.notes}`) : null,
    h("div", { class: "page-actions" },
      h("button", { class: "btn btn-primary", type: "button", disabled: !canRecord, onclick: () => findingForm(d, anchor) }, "Record finding"),
      h("button", { class: "btn", type: "button", disabled: !canRecord, onclick: () => {
        evalState.pending = { question: d.question, candidates: d.evidence.map((e) => ({ id: e.memory_id, title: e.title })) };
        go("evaluation");
      } }, "Add to benchmark"),
      navLink("Compare search modes", "search", { q: d.question, mode: "hybrid" }, "btn")),
  );

  const evidence = h("section", { class: "panel", "aria-labelledby": "ev-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "ev-title" }, "Evidence"), h("p", null, `${d.evidence_count} record${d.evidence_count === 1 ? "" : "s"}`)),
    d.evidence.length
      ? h("ol", { class: "evidence" }, d.evidence.map((e, i) => h("li", { id: `ev-${i + 1}`, tabindex: "-1" },
          h("div", { class: "evidence-head" },
            h("span", { class: "evidence-n" }, `Record ${i + 1}`),
            h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(e.memory_id) }, e.title)),
          h("p", null, e.content_preview),
          h("div", { class: "queue-meta" },
            h("span", { class: "tag" }, typeLabel(e.memory_type)),
            h("span", { class: "tag" }, SOURCE_LABEL[e.retrieval_source] || e.retrieval_source),
            metaPair("Asset", e.asset_id), metaPair("Confidence", pct(e.confidence))))))
      : empty("No supporting records", "Nothing in canonical storage matched. Rephrase with an asset name or symptom, or record what's missing.",
          h("button", { class: "btn", type: "button", onclick: () => memoryForm() }, "New record")),
  );

  const stepNames = { retrieval: "Retrieve", graph_reasoning: "Follow graph links", synthesis: "Write answer", critic: "Check citations" };
  const steps = h("section", { class: "panel", "aria-labelledby": "steps-title" },
    h("div", { class: "panel-head" }, h("h2", { id: "steps-title" }, "How this answer was built"), h("p", null, `${num(d.total_latency_ms, 0)} ms in total`)),
    h("ol", { class: "steps" }, d.steps.map((st) => h("li", null,
      h("strong", null, stepNames[st.type] || st.type),
      h("span", null, st.description),
      st.latency_ms ? h("span", { class: "cell-sub" }, `${num(st.latency_ms, 0)} ms`) : null))),
  );

  return [h("div", { class: "grid grid-main" }, h("div", { class: "stack" }, answer, steps), evidence)];
}

/** Turn a confirmed conclusion into a canonical record, linked to its evidence and incident. */
export function findingForm(d, anchor) {
  const typeSelect = h("select", { id: "f-memory_type", name: "memory_type" },
    [["diagnosis", "Diagnosis"], ["recommendation", "Recommendation"], ["observation", "Observation"], ["resolution", "Resolution"]].map(([v, l]) => h("option", { value: v }, l)));
  const evidenceBoxes = h("fieldset", { class: "span-2" }, h("legend", null, "Evidence this finding rests on"),
    h("div", { class: "check-list" }, d.evidence.map((e, i) =>
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "evidence", value: e.memory_id, checked: true }), `Record ${i + 1}: ${e.title}`))));
  const form = h("form", { class: "form-grid", novalidate: true },
    formField("memory_type", "Finding type", typeSelect),
    h("div", { class: "field" }),
    formField("title", "Title", h("input", { type: "text", id: "f-title", maxlength: 200, value: "" }), "State the conclusion, e.g. “Worn spindle bearing caused oversize holes”", true),
    formField("content", "Finding", h("textarea", { id: "f-content", rows: 4 }, d.is_synthetic_response ? "" : d.answer),
      d.is_synthetic_response ? "Write the conclusion in your own words; the test provider only listed records." : "Edit the model's answer into the conclusion you're confirming.", true),
    evidenceBoxes,
    formField("confidence", "Confidence (0–1)", h("input", { type: "number", id: "f-confidence", min: 0, max: 1, step: 0.01, value: 0.7 }), "Findings need 0.6 or more"),
    formField("importance", "Importance (0–1)", h("input", { type: "number", id: "f-importance", min: 0, max: 1, step: 0.01, value: 0.6 }), "Findings need 0.4 or more"),
  );
  const submit = h("button", { class: "btn btn-primary", type: "button" }, "Record finding");
  submit.addEventListener("click", async () => {
    clearInvalid(form);
    const title = form.querySelector("#f-title").value.trim();
    const content = form.querySelector("#f-content").value.trim();
    const evidence = [...form.querySelectorAll("input[name=evidence]:checked")].map((i) => i.value);
    let invalid = null;
    if (!title) invalid = invalid || markInvalid(form, "title", "Required");
    if (!content) invalid = invalid || markInvalid(form, "content", "Required");
    if (invalid) return invalid.focus();
    if (!evidence.length) return toast("Select at least one evidence record", true);
    busy(submit, true);
    const res = await api("/investigations/findings", { method: "POST", body: {
      question: d.question,
      memory_type: form.querySelector("#f-memory_type").value,
      title, content,
      evidence_memory_ids: evidence,
      anchor_memory_id: anchor || d.anchor_memory_id || evidence[0],
      confidence: Number(form.querySelector("#f-confidence").value),
      importance: Number(form.querySelector("#f-importance").value),
      answer_was_synthetic: d.is_synthetic_response,
    } });
    busy(submit, false);
    if (res.status === 401) showSignIn();
    if (!res.ok) return toast(res.error, true);
    closeDialog();
    const rec = res.data;
    toast(rec.incident_id ? `Finding recorded on ${rec.incident_id}` : "Finding recorded");
    if (rec.incident_id) go("incidents", { id: rec.incident_id }); else showMemory(rec.id);
  });
  openDialog("Record finding", h("div", null,
    notice("info", "You are confirming this, not the system", "The finding is saved as a canonical record with its evidence attached. It inherits the asset and incident of the record you started from, or of the top evidence record."),
    form), [h("button", { class: "btn", type: "button", onclick: closeDialog }, "Cancel"), submit]);
}
