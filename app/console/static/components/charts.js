// Dependency-free SVG charts for the console. Colours come from CSS roles
// (.viz --series-*, --heat-*), validated for colour-vision deficiency in light
// and dark; every mark has a visible value label or a table view, and a
// tooltip on hover and keyboard focus.
import { h, s } from "../lib/dom.js";

/** Attach one shared tooltip to a chart wrapper; marks carry data-tip. */
export function withTooltip(wrap) {
  const tip = h("div", { class: "chart-tip", "aria-hidden": "true", hidden: true });
  wrap.append(tip);
  const show = (el, x, y) => {
    tip.textContent = el.getAttribute("data-tip");
    tip.hidden = false;
    const r = wrap.getBoundingClientRect();
    tip.style.left = `${Math.max(4, Math.min(x - r.left + 12, r.width - tip.offsetWidth - 4))}px`;
    tip.style.top = `${y - r.top + 14}px`;
  };
  wrap.addEventListener("pointermove", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (el && wrap.contains(el)) show(el, e.clientX, e.clientY); else tip.hidden = true;
  });
  wrap.addEventListener("pointerleave", () => { tip.hidden = true; });
  wrap.addEventListener("focusin", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (!el) return;
    const b = el.getBoundingClientRect();
    show(el, b.left + Math.min(b.width, 160), b.top);
  });
  wrap.addEventListener("focusout", () => { tip.hidden = true; });
  return wrap;
}

/** Legend: swatch + text in ink colours, never text in the series colour. */
export function legend(series) {
  return h("ul", { class: "legend" }, series.map((sr) => h("li", null, h("span", { class: `sw ${sr.cls}`, "aria-hidden": "true" }), sr.label)));
}

// Bar with a 4px rounded data end and a square baseline end.
function barPath(x, y, w, ht) {
  if (w <= 0.5) return `M${x} ${y}h1v${ht}h-1Z`;
  const r = Math.min(4, w, ht / 2);
  return `M${x} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + ht - r}Q${x + w} ${y + ht} ${x + w - r} ${y + ht}H${x}Z`;
}

/** Horizontal grouped bars on a 0..1 scale. rows: [{ label, values: { key: number|null } }]. */
export function groupedBars({ rows, series, format, label }) {
  const W = 720, left = 140, right = 64, bar = 16, gap = 2, groupGap = 20, top = 10, axisH = 26;
  const plotW = W - left - right;
  const groupH = series.length * (bar + gap) - gap;
  const H = top + rows.length * (groupH + groupGap) - groupGap + axisH + 6;
  const X = (v) => left + v * plotW;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": label });
  for (const t of [0, 0.25, 0.5, 0.75, 1]) {
    svg.append(s("line", { class: t === 0 ? "chart-base" : "chart-grid", x1: X(t), x2: X(t), y1: top - 4, y2: H - axisH }));
    svg.append(s("text", { class: "chart-tick", x: X(t), y: H - 8, "text-anchor": "middle" }, `${Math.round(t * 100)}%`));
  }
  rows.forEach((row, i) => {
    const y0 = top + i * (groupH + groupGap);
    svg.append(s("text", { class: "chart-label", x: left - 12, y: y0 + groupH / 2 + 4, "text-anchor": "end" }, row.label));
    series.forEach((sr, j) => {
      const v = row.values[sr.key];
      const y = y0 + j * (bar + gap);
      if (v === null || v === undefined) {
        svg.append(s("text", { class: "chart-value is-muted", x: left + 6, y: y + bar - 3 }, `${sr.label}: not measured`));
        return;
      }
      const w = Math.max(0, Math.min(1, v)) * plotW;
      svg.append(s("path", { class: `chart-bar ${sr.cls}`, d: barPath(left, y, w, bar) }));
      svg.append(s("text", { class: "chart-value", x: left + w + 6, y: y + bar - 3 }, format(v)));
      svg.append(s("rect", { class: "chart-hit", x: left, y: y - gap / 2, width: plotW, height: bar + gap, tabindex: "0", "data-tip": `${row.label}, ${sr.label}: ${format(v)}` }));
    });
  });
  return svg;
}

/** Horizontal bars on a log scale, for latencies that span orders of magnitude. */
export function logBars({ rows, unit, label, cls = "is-s1" }) {
  const W = 720, left = 140, right = 84, bar = 18, gap = 12, top = 10, axisH = 26;
  const plotW = W - left - right;
  const vals = rows.map((r) => r.value).filter((v) => typeof v === "number" && v > 0);
  const lo = 1;
  const hi = 10 ** Math.max(1, Math.ceil(Math.log10(Math.max(10, ...vals))));
  const X = (v) => left + (Math.log10(Math.max(v, lo)) / Math.log10(hi)) * plotW;
  const H = top + rows.length * (bar + gap) - gap + axisH + 6;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": label });
  for (let t = lo; t <= hi; t *= 10) {
    svg.append(s("line", { class: t === lo ? "chart-base" : "chart-grid", x1: X(t), x2: X(t), y1: top - 4, y2: H - axisH }));
    svg.append(s("text", { class: "chart-tick", x: X(t), y: H - 8, "text-anchor": "middle" }, t >= 1000 ? `${t / 1000} s` : `${t} ${unit}`));
  }
  rows.forEach((row, i) => {
    const y = top + i * (bar + gap);
    svg.append(s("text", { class: "chart-label", x: left - 12, y: y + bar - 3, "text-anchor": "end" }, row.label));
    if (typeof row.value !== "number") {
      svg.append(s("text", { class: "chart-value is-muted", x: left + 6, y: y + bar - 3 }, "not measured"));
      return;
    }
    const w = X(row.value) - left;
    svg.append(s("path", { class: `chart-bar ${row.cls || cls}`, d: barPath(left, y, w, bar) }));
    svg.append(s("text", { class: "chart-value", x: left + w + 6, y: y + bar - 3 }, row.text));
    svg.append(s("rect", { class: "chart-hit", x: left, y: y - gap / 2, width: plotW, height: bar + gap, tabindex: "0", "data-tip": `${row.label}: ${row.text}` }));
  });
  return svg;
}

/** Sequential step (0-3) for a 0..1 score; 0 is reserved for exactly zero. */
export function heatStep(v) {
  if (typeof v !== "number") return null;
  if (v <= 0) return 0;
  if (v < 0.5) return 1;
  if (v < 1) return 2;
  return 3;
}
