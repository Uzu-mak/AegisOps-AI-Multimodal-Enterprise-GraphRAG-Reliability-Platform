// Evaluation statistics and checks computed in the browser from per-case
// results the API already returns. Pure functions; no network, no DOM.

/** Small seeded PRNG (mulberry32) so intervals are reproducible run to run. */
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Mean with a 95% percentile-bootstrap interval, resampling the values
 *  (one value per question). Returns null for no data. */
export function bootstrapMean(values, { resamples = 1000, seed = 20261029 } = {}) {
  const xs = values.filter((v) => typeof v === "number" && Number.isFinite(v));
  if (!xs.length) return null;
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  if (xs.length === 1) return { mean, lo: null, hi: null, n: 1 };
  const next = rng(seed);
  const means = new Array(resamples);
  for (let r = 0; r < resamples; r += 1) {
    let sum = 0;
    for (let i = 0; i < xs.length; i += 1) sum += xs[Math.floor(next() * xs.length)];
    means[r] = sum / xs.length;
  }
  means.sort((a, b) => a - b);
  return { mean, lo: means[Math.floor(0.025 * (resamples - 1))], hi: means[Math.ceil(0.975 * (resamples - 1))], n: xs.length };
}

const STOP = new Set(["the", "and", "for", "with", "from", "what", "why", "how", "when", "does", "did", "are", "was", "were", "this", "that", "our", "about", "know", "fix", "fixed", "before", "after", "into", "onto", "its", "has", "have", "had", "can", "not", "but", "you", "your", "they", "them", "then", "than", "there", "which", "who", "will", "would", "should", "could"]);
const words = (s) => new Set(String(s || "").toLowerCase().match(/[a-z0-9][a-z0-9-]{2,}/g)?.filter((w) => !STOP.has(w)) || []);

/** How much of a record's title a question repeats (0..1). A question that
 *  copies the answer's title tests string matching, not retrieval. */
export function titleOverlap(question, title) {
  const t = words(title);
  if (!t.size) return 0;
  const q = words(question);
  let shared = 0;
  for (const w of t) if (q.has(w)) shared += 1;
  return shared / t.size;
}

export const LEAK_THRESHOLD = 0.6;

/** Leakage verdict for a question against the records labelled relevant. */
export function leakage(question, titles) {
  if (/^\s*what do we know about:/i.test(question || "")) return { leaked: true, reason: "The question is the console's generated “What do we know about: …” wording" };
  const worst = Math.max(0, ...titles.map((t) => titleOverlap(question, t)));
  return worst >= LEAK_THRESHOLD
    ? { leaked: true, reason: `The question repeats ${Math.round(worst * 100)}% of a relevant record's title` }
    : { leaked: false, reason: null, overlap: worst };
}

/** Evidence strength from facts the run holds (thresholds from the design doc). */
export function evidenceStrength({ n, semantic, source, leaked = 0, humanApproved = false }) {
  const why = [];
  if (source === "console") why.push("console questions are not reviewed or versioned");
  if (!semantic) why.push("the API used a test embedding, not a semantic one");
  if (n < 10) why.push(`${n} labelled question${n === 1 ? "" : "s"}; at least 10 needed`);
  if (leaked) why.push(`${leaked} question${leaked === 1 ? " repeats" : "s repeat"} a record title`);
  if (why.length) return { level: "exploratory", label: "Exploratory", sev: "warn", why };
  if (n < 30 || !humanApproved) {
    return { level: "indicative", label: "Indicative", sev: "info", why: [n < 30 ? `${n} questions; 30 needed for decision-grade` : "labels are not human-approved"] };
  }
  return { level: "decision", label: "Decision-grade", sev: "normal", why: [`${n} human-approved questions, semantic embedding`] };
}

/** Fisher-Yates shuffle with Math.random: blind presentation of candidates. */
export function shuffled(list) {
  const a = list.slice();
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
