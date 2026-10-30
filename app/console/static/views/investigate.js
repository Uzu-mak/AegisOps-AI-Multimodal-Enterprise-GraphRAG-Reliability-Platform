import { closeDialog, openDialog } from "../components/dialog.js";
import { clearInvalid, formField, markInvalid, memoryForm, showMemory } from "../components/records.js";
import { SOURCE_LABEL, busy, empty, fmtWhen, lifecycleChip, metaPair, notice, num, pageHead, pct, scoreBar, shortId, skeleton, stateChip, toast, typeLabel } from "../components/ui.js";
import { tabs } from "../components/tabs.js";
import { api, fetchAllMemories, showSignIn } from "../lib/api.js";
import { h, icon, put, s } from "../lib/dom.js";
import { capable, evalState, go, href, main, navLink, services, whenOf } from "../lib/state.js";
import { isAdmin } from "../lib/session.js";

/* ------------------------------------------------------- investigate */

// What the search covered. Absence of a record is only evidence of absence
// within these records, so the answer always says what they were.
function searchedLine(sc) {
  if (!sc || !sc.active_records) return null;
  const parts = Object.entries(sc.by_source || {}).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${num(n)} ${k === "work_order" ? "work orders" : k === "investigation" ? "confirmed findings" : `${k.replace(/_/g, " ")} records`}`);
  return h("p", { class: "check-line" },
    `Searched ${num(sc.active_records)} active records (${parts.join(", ")}${sc.sample_records ? `; ${num(sc.sample_records)} are sample data` : ""}). ` +
    "If something isn't found here, it may still have happened: it may simply not be in these records.");
}

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
  if (!isAdmin()) {
    if (!capable("qdrant", "neo4j")) warnings.push(notice("warn", "Investigations are limited right now", "Answers may draw on fewer related records until the service recovers."));
  } else if (!capable("qdrant") && !capable("neo4j")) warnings.push(notice("warn", "Vector and graph search are offline", "Investigations will use keyword matches from PostgreSQL until Qdrant or Neo4j is back.", [navLink("Open System health", "system", {}, "btn")]));
  else if (!capable("neo4j")) warnings.push(notice("warn", "Relationship store is offline", "Investigations use vector matches only; graph links return when Neo4j reconnects."));
  if (isAdmin() && svc.llm?.synthetic) warnings.push(notice("info", "Answers come from the deterministic test provider", "It lists the retrieved records with citations and adds no reasoning. Set LLM_PROVIDER=openai and OPENAI_API_KEY for model-written answers."));

  put(main, pageHead("Investigate", "Ask about an asset, symptom or incident. The answer cites canonical records, shows how it was built, and is checked before you record anything."), ...warnings, form, out);
  if (q) form.requestSubmit(); else question.focus();
}

// Record types that answer an engineer's questions in order: what failed,
// what was done, did it work, how to prevent it. The summary is built only
// from cited records of these types, never from the model's text.
const SLOTS = [
  ["diagnosis", "Root cause"],
  ["maintenance_action", "Corrective action"],
  ["resolution", "Outcome"],
  ["recommendation", "Prevention"],
];
const ROLE = Object.fromEntries(SLOTS);

function citedNumbers(answer, count) {
  const cited = new Set();
  for (const m of String(answer || "").matchAll(/\[Memory\s+(\d+)\]/g)) {
    const n = Number(m[1]);
    if (n >= 1 && n <= count) cited.add(n);
  }
  return cited;
}

function answerParagraphs(text, count, onCite) {
  return String(text || "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean).map((p) => {
    const parts = [];
    const re = /\[Memory\s+(\d+)\]/g;
    let last = 0;
    let m;
    while ((m = re.exec(p))) {
      parts.push(p.slice(last, m.index));
      const n = Number(m[1]);
      parts.push(n >= 1 && n <= count
        ? h("a", { class: "cite", href: `#ev-${n}`, onclick: (e) => { e.preventDefault(); onCite(n); } }, `Record ${n}`)
        : h("span", { class: "cite is-invalid" }, `Record ${n} (not in evidence)`));
      last = m.index + m[0].length;
    }
    parts.push(p.slice(last));
    return h("p", null, parts);
  });
}

export function renderInvestigation(d, anchor) {
  const admin = isAdmin();
  const ev = d.evidence || [];
  const cited = citedNumbers(d.answer, ev.length);
  const critic = d.critic || {};
  const full = new Map(); // memory_id -> canonical record, loaded after render
  let detail = null;
  const focusEvidence = (n) => {
    detail?.select("evidence");
    const el = document.getElementById(`ev-${n}`);
    if (el) { el.scrollIntoView({ block: "center" }); el.focus(); }
  };

  /* Header: where this investigation sits, and what was checked. */
  const crumbs = h("p", { class: "crumbs" }, "Investigation");
  const chips = h("div", { class: "chip-row" },
    critic.is_supported ? stateChip("Citations valid", "normal") : stateChip("Needs review", "warn"),
    d.is_synthetic_response ? stateChip("Test provider", "info") : h("span", { class: "tag" }, d.model_name));
  const header = h("section", { class: "inv-head", "aria-labelledby": "inv-q" },
    crumbs, h("h2", { id: "inv-q", class: "inv-question" }, d.question), chips);

  /* What the cited records say: one slot per record type. */
  const hitsOf = (type) => ev.map((e, i) => ({ e, n: i + 1 })).filter(({ e, n }) => e.memory_type === type && cited.has(n));
  const anySlot = SLOTS.some(([type]) => hitsOf(type).length);
  const evLink = (n) => h("a", { href: `#ev-${n}`, onclick: (x) => { x.preventDefault(); focusEvidence(n); } }, `Record ${n}`);
  const slots = SLOTS.map(([type, role]) => {
    const hits = hitsOf(type);
    if (!hits.length) {
      return h("li", { class: "slot prov is-empty" },
        h("span", { class: "prov-label" }, role),
        h("span", { class: "slot-empty" }, `No ${typeLabel(type).toLowerCase()} record cited`));
    }
    const [{ e, n }] = hits;
    return h("li", { class: "slot prov" },
      h("span", { class: "prov-label" }, `${role} · ${typeLabel(type)} · `, evLink(n), hits.length > 1 ? ` · ${hits.length - 1} more cited` : ""),
      h("span", { class: "slot-value" }, e.title));
  });
  const summary = h("section", { class: "panel", "aria-labelledby": "sum-title" },
    h("div", { class: "panel-head" }, h("div", null,
      h("h2", { id: "sum-title" }, "What the cited records say"),
      h("p", null, "From the records' own types and titles, not from the AI text"))),
    anySlot
      ? h("ol", { class: "slots" }, slots)
      : h("p", { class: "toolbar-note" }, "The answer cites no diagnosis, corrective action, outcome or recommendation record. Read the AI summary and the evidence, and treat any conclusion as unconfirmed."));

  /* Next step: one primary action; confirmed findings on the incident. */
  const canRecord = ev.length > 0;
  const incidentSlot = h("span", { class: "next-slot" });
  const findingsHost = h("div", { class: "findings" }, h("p", { class: "toolbar-note" },
    anchor ? "Checking for findings on this incident" : "Start from a record to see findings already confirmed on its incident."));
  const next = h("section", { class: "panel next-step", "aria-labelledby": "next-title" },
    h("h2", { id: "next-title" }, "Next step"),
    h("div", { class: "next-actions" },
      h("button", { class: "btn btn-primary", type: "button", disabled: !canRecord, onclick: () => findingForm(d, anchor) }, "Record finding"),
      incidentSlot,
      admin ? h("button", { class: "btn", type: "button", disabled: !canRecord, onclick: () => {
        // Hand over the question only; the Evaluation page pools candidates
        // from every retrieval mode so labels aren't limited to what this
        // investigation happened to find.
        evalState.pending = { question: d.question, anchor: anchor || null, evidence: ev.map((e) => e.memory_id) };
        go("evaluation");
      } }, "Add to benchmark") : null,
      admin ? navLink("Compare search modes", "search", { q: d.question, mode: "hybrid" }, "btn") : null),
    h("h3", { class: "findings-title" }, "Confirmed findings"),
    findingsHost);

  /* AI summary: generated text, kept visibly apart from record facts. */
  const keyword = d.retrieval_mode === "keyword_fallback"
    ? notice("warn", "Matched by keywords", admin
      ? "Vector and graph stores returned nothing, so evidence was matched by words in PostgreSQL. Treat the ranking as approximate."
      : "Related records were matched by their words only, so the ranking is approximate.")
    : null;
  const ai = h("section", { class: "panel ai-summary", "aria-labelledby": "ai-title" },
    h("div", { class: "prov prov-ai" },
      h("h2", { id: "ai-title", class: "prov-label" }, d.is_synthetic_response
        ? "Test provider · lists the retrieved records without reasoning"
        : `AI summary · ${d.model_name} · generated text, check it against the records`),
      keyword,
      h("div", { class: "answer" }, answerParagraphs(d.answer, ev.length, focusEvidence)),
      h("p", { class: "check-line" }, critic.is_supported
        ? "Citations valid: every factual sentence cites a retrieved record. This checks the citations, not that the conclusion is physically true; only a confirmed finding does that."
        : `Needs review: ${critic.notes || "the citation check did not pass"}`),
      !critic.is_supported && critic.unsupported_claims?.length
        ? h("ul", { class: "unsupported" }, critic.unsupported_claims.map((c) => h("li", null, `No citation: “${c}”`)))
        : null,
      searchedLine(d.searched),
      critic.weak_citations?.length
        ? h("div", null,
          h("p", { class: "check-line" }, "Check these: the cited record shares few words with the sentence, so it may not support it."),
          h("ul", { class: "unsupported" }, critic.weak_citations.map((c) => h("li", null, `Weak citation: “${c}”`))))
        : null));

  /* Evidence, as cards with their role and provenance. */
  const roleOf = (e, n) => (e.retrieval_source === "anchor" ? "Starting record"
    : cited.has(n) ? ROLE[e.memory_type] || "Cited context" : "Retrieved, not cited");
  const tagHosts = new Map();
  const evidenceList = ev.length
    ? h("ol", { class: "evidence" }, ev.map((e, i) => {
        const n = i + 1;
        const tags = h("div", { class: "queue-meta" },
          h("span", { class: "tag" }, typeLabel(e.memory_type)),
          metaPair("Asset", e.asset_id), metaPair("Confidence", pct(e.confidence)),
          e.trust ? h("span", { class: `tag tag-trust${/sample|cut off|administrative|disputed|superseded/.test(e.trust) ? " is-caution" : ""}`, title: "Where this record came from" }, e.trust) : null,
          admin ? h("span", { class: "tag" }, SOURCE_LABEL[e.retrieval_source] || e.retrieval_source) : null);
        tagHosts.set(e.memory_id, tags);
        return h("li", { id: `ev-${n}`, tabindex: "-1", class: "prov" },
          h("div", { class: "evidence-head" },
            h("span", { class: "evidence-n" }, `Record ${n}`),
            h("span", { class: "evidence-role" }, roleOf(e, n)),
            h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(e.memory_id) }, e.title)),
          h("p", null, e.content_preview),
          tags);
      }))
    : empty("No supporting records", "Nothing in canonical storage matched. Rephrase with an asset name or symptom, or record what's missing.",
        h("button", { class: "btn", type: "button", onclick: () => memoryForm() }, "New record"));

  /* Timeline of the evidence records, once their dates are loaded. */
  const timelineHost = h("div", null, skeleton());
  const drawTimeline = () => {
    const rows = ev.map((e, i) => ({ n: i + 1, r: full.get(e.memory_id) })).filter((x) => x.r)
      .sort((a, b) => String(whenOf(a.r)).localeCompare(String(whenOf(b.r))));
    put(timelineHost, rows.length
      ? h("ol", { class: "timeline" }, rows.map(({ n, r }) => h("li", { class: `is-${r.memory_type}` },
          h("span", { class: "timeline-mark", "aria-hidden": "true" }, icon(r.memory_type === "incident" ? "warn" : r.memory_type === "resolution" ? "ok" : "info")),
          h("p", { class: "timeline-when" }, `${typeLabel(r.memory_type)}, ${fmtWhen(whenOf(r))}, Record ${n}${r.incident_id ? `, ${r.incident_id}` : ""}`),
          h("h3", { class: "timeline-title" }, h("button", { type: "button", onclick: () => showMemory(r.id) }, r.title)))))
      : empty("No dated records", "The evidence records couldn't be loaded."));
  };

  /* Relationships of the starting record (or top evidence), loaded on demand. */
  const relHost = h("div", null, skeleton());
  let relLoaded = false;
  const loadRelationships = async () => {
    if (relLoaded) return;
    relLoaded = true;
    const from = anchor || ev[0]?.memory_id;
    if (!from) return put(relHost, empty("Nothing to relate", "There's no evidence record to start from."));
    const r = await api("/search/graph-related", { method: "POST", body: { memory_id: from, max_hops: 2, limit: 20 } });
    if (!r.ok) return put(relHost, notice("warn", "Relationships are unavailable right now", admin ? r.error : "Try again shortly."));
    const ids = (r.data.related_memory_ids || []).slice(0, 20);
    const recs = await Promise.all(ids.map((id) => (full.has(id) ? { ok: true, data: full.get(id) } : api(`/memories/${id}`))));
    const rows = recs.filter((x) => x.ok).map((x) => x.data);
    put(relHost, rows.length
      ? h("div", { class: "stack" },
          h("ul", { class: "queue" }, rows.map((m) => h("li", null, h("button", { class: "queue-item", type: "button", onclick: () => showMemory(m.id) },
            h("span", { class: "queue-title" }, m.title),
            lifecycleChip(m.status),
            h("span", { class: "queue-meta" }, h("span", { class: "tag" }, typeLabel(m.memory_type)), metaPair("Asset", m.asset_id), metaPair("Incident", m.incident_id)))))),
          h("div", { class: "page-actions" }, navLink("Open in Relationships", "graph", { anchor: from }, "btn")))
      : empty("No linked records", "The starting record shares no asset, incident, line or source with other records yet."));
  };

  /* Diagnostics: how the answer was built. Administrators only. */
  const stepNames = { retrieval: "Retrieve", graph_reasoning: "Follow graph links", synthesis: "Write answer", critic: "Check citations" };
  const diagnostics = h("div", { class: "stack" },
    h("p", { class: "latency" },
      h("span", null, h("strong", null, num(d.total_latency_ms, 0)), "ms total"),
      h("span", null, h("strong", null, num(d.retrieval_latency_ms, 0)), "ms retrieval"),
      h("span", null, h("strong", null, num(d.generation_latency_ms, 0)), "ms answer"),
      h("span", null, `Mode: ${d.retrieval_mode}`)),
    h("ol", { class: "steps" }, (d.steps || []).map((st) => h("li", null,
      h("strong", null, stepNames[st.type] || st.type),
      h("span", null, st.description),
      st.latency_ms ? h("span", { class: "cell-sub" }, `${num(st.latency_ms, 0)} ms`) : null))),
    ev.length ? h("div", { class: "table-wrap" }, h("table", null,
      h("caption", null, "How each evidence record was found"),
      h("thead", null, h("tr", null, ["Record", "Found by", "Similarity", "Cited"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", null, ev.map((e, i) => h("tr", null,
        h("td", null, `Record ${i + 1}: ${e.title}`),
        h("td", null, SOURCE_LABEL[e.retrieval_source] || e.retrieval_source),
        h("td", null, typeof e.semantic_score === "number" ? scoreBar(e.semantic_score) : "—"),
        h("td", null, cited.has(i + 1) ? "Yes" : "No")))))) : null);

  detail = tabs([
    { id: "evidence", label: `Evidence · ${ev.length}`, panel: evidenceList },
    { id: "timeline", label: "Timeline", panel: timelineHost },
    { id: "relationships", label: "Relationships", panel: relHost, onSelect: loadRelationships },
    ...(admin ? [{ id: "diagnostics", label: "Diagnostics", panel: diagnostics }] : []),
  ], "Investigation detail");

  /* Load canonical records for dates, sample flags, findings and context. */
  (async () => {
    const ids = [...new Set([...ev.map((e) => e.memory_id), ...(anchor ? [anchor] : [])])];
    const res = await Promise.all(ids.map((id) => api(`/memories/${id}`)));
    for (const r of res) if (r.ok) full.set(r.data.id, r.data);
    const a = anchor ? full.get(anchor) : null;
    if (a) {
      put(crumbs, "Investigation",
        a.asset_id ? [" / ", navLink(a.asset_id, "memories", { asset: a.asset_id, status: "any" })] : null,
        a.incident_id ? [" / ", navLink(a.incident_id, "incidents", { id: a.incident_id })] : null);
      if (a.incident_id) put(incidentSlot, navLink(`Open incident ${a.incident_id}`, "incidents", { id: a.incident_id }, "btn"));
    }
    if ([...full.values()].some((r) => r.is_synthetic)) chips.append(stateChip("Sample data", "info"));
    for (const e of ev) {
      const r = full.get(e.memory_id);
      const tags = tagHosts.get(e.memory_id);
      if (!r || !tags) continue;
      if (r.is_synthetic) tags.append(h("span", { class: "tag" }, "Sample data"));
      if (r.source_type === "investigation") {
        tags.append(stateChip("Confirmed finding", "normal"));
        tags.closest("li")?.classList.add("prov-confirmed");
      }
    }
    drawTimeline();
    if (!a) {
      if (anchor) put(findingsHost, h("p", { class: "toolbar-note" }, "The starting record couldn't be loaded."));
      return;
    }
    if (!a.incident_id) return put(findingsHost, h("p", { class: "toolbar-note" }, "The starting record has no incident, so there are no incident findings to show."));
    const all = await fetchAllMemories({ status: "active" });
    const found = (all.items || []).filter((m) => m.incident_id === a.incident_id && m.source_type === "investigation");
    put(findingsHost, found.length
      ? h("ul", { class: "findings-list" }, found.map((m) => h("li", { class: "prov prov-confirmed" },
          h("button", { class: "btn btn-quiet", type: "button", onclick: () => showMemory(m.id) }, m.title),
          h("span", { class: "prov-label" }, `${typeLabel(m.memory_type)} · recorded ${fmtWhen(m.created_at)}`))))
      : h("p", { class: "toolbar-note" }, `None on ${a.incident_id} yet. A finding you record appears here.`));
  })();

  return [header, h("div", { class: "grid grid-main" }, summary, next), ai, detail.el];
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
