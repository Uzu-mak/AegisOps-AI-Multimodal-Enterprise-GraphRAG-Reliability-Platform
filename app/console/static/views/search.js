import { showMemory } from "../components/records.js";
import { SOURCE_LABEL, busy, empty, lifecycleChip, notice, num, pageHead, scoreBar, shortId } from "../components/ui.js";
import { api } from "../lib/api.js";
import { h, put, s } from "../lib/dom.js";
import { capable, href, main, navLink, state } from "../lib/state.js";

/* ------------------------------------------------------------ search */

export async function viewSearch(params) {
  const mode = params.get("mode") || "hybrid";
  const out = h("div", { class: "stack", "aria-live": "polite" });
  const query = h("input", { type: "search", id: "s-q", name: "query", value: params.get("q") || "", placeholder: "Describe a symptom, part or fix", required: true });
  const modes = [["semantic", "Meaning"], ["graph", "Relationships"], ["hybrid", "Both"]];
  const seg = h("fieldset", null, h("legend", null, "Match by"),
    h("div", { class: "segmented" }, modes.map(([v, l]) => h("label", null,
      h("input", { type: "radio", name: "mode", value: v, checked: v === mode }), h("span", null, l)))));
  const inactive = h("label", { class: "check" }, h("input", { type: "checkbox", name: "inactive" }), "Include archived and disputed");
  const go2 = h("button", { class: "btn btn-primary", type: "submit" }, "Search");

  const form = h("form", { class: "panel", role: "search", onsubmit: async (e) => {
    e.preventDefault();
    const text = query.value.trim();
    if (!text) return query.focus();
    const m = form.querySelector("input[name=mode]:checked").value;
    history.replaceState(null, "", href("search", { mode: m, q: text }));
    busy(go2, true);
    const r = await api("/search/hybrid", { method: "POST", body: { query: text, mode: m, limit: 20, include_inactive: inactive.querySelector("input").checked } });
    busy(go2, false);
    if (!r.ok) {
      return put(out, notice(r.status === 503 ? "warn" : "crit", r.status === 503 ? "This search mode is offline" : "Search failed", r.error,
        r.status === 503 ? [navLink("Open System health", "system", {}, "btn"), navLink("Find by text in Records", "memories", { q: text }, "btn")] : null));
    }
    const res = r.data.results || [];
    const anchorRow = r.data.anchor_memory_id ? res.find((x) => x.memory_id === r.data.anchor_memory_id) : null;
    put(out,
      h("div", { class: "page-actions" },
        navLink("Investigate this question", "investigate", { q: text }, "btn"),
        r.data.anchor_memory_id ? navLink("Show relationships of the top match", "graph", { anchor: r.data.anchor_memory_id }, "btn") : null),
      res.length
        ? h("div", { class: "table-wrap" }, h("table", null,
            h("caption", null, `${res.length} result${res.length === 1 ? "" : "s"} in ${num(r.data.latency_ms, 0)} ms${r.data.anchor_memory_id && m !== "semantic" ? `. Graph links are relative to ${anchorRow ? `“${anchorRow.title}”` : "the best vector match"}.` : ""}`),
            h("thead", null, h("tr", null, ["Record", "Found by", "Similarity", "Status", "Asset"].map((c) => h("th", { scope: "col" }, c)))),
            h("tbody", null, res.map((x) => {
              const open = () => showMemory(x.memory_id);
              return h("tr", { class: "is-clickable", tabindex: "0", onclick: open, onkeydown: (e) => { if (e.key === "Enter") open(); } },
                h("td", null, h("span", { class: "cell-title" }, x.title || shortId(x.memory_id)), h("span", { class: "cell-sub" }, x.content_preview || "Not found in PostgreSQL")),
                h("td", null, h("span", { class: "tag" }, SOURCE_LABEL[x.retrieval_source] || x.retrieval_source)),
                h("td", null, typeof x.semantic_score === "number" ? scoreBar(x.semantic_score) : "—"),
                h("td", null, x.status ? lifecycleChip(x.status) : "—"),
                h("td", null, x.asset_id || "—"));
            }))))
        : empty("No matches", "Try different words, switch to Both, or include archived records."));
  } },
    h("div", { class: "toolbar" },
      h("div", { class: "field field-grow" }, h("label", { for: "s-q" }, "Search for"), query),
      seg, inactive, go2));

  const notes = [];
  if (!capable("qdrant")) notes.push(notice("warn", "Meaning search is offline", "Qdrant is unavailable. Relationship search also needs it to pick a starting record from your words."));
  if (!capable("neo4j")) notes.push(notice("warn", "Relationship search is offline", "Neo4j is unavailable, so only meaning search can run."));
  const emb = state.health?.embedding_provider;
  if (capable("qdrant") && emb && !emb.semantic) {
    notes.push(emb.name === "HashedTermEmbedding"
      ? notice("info", "Similarity is based on shared words", "The term-hashing embedding ranks records that use the same words as your query. Synonyms won't match until a semantic embedding model is configured.")
      : notice("info", "Similarity scores are test values", "The default test embedding hashes whole texts, so scores don't reflect meaning. Set EMBEDDING_PROVIDER=hashed_terms for word-based ranking, or configure a semantic model."));
  }

  put(main, pageHead("Search", "Find records by meaning, by their links to the best match, or both. These are the same retrieval modes the benchmark measures."), ...notes, form, out);
  if (params.get("q")) form.requestSubmit(); else query.focus();
}
