/* ------------------------------------------------------------------ DOM */

export function h(tag, attrs, ...children) {
  const el = tag === "svg" || attrs?.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false || k === "svg") continue;
      if (k === "class") el.setAttribute("class", v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "html") el.innerHTML = v; // only ever used with static SVG markup
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** replaceChildren that ignores null/false (replaceChildren would print "null"). */
export function put(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

/** append that ignores null/false. */
export function add(el, ...children) {
  el.append(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
  return el;
}

export function s(tag, attrs, ...children) {
  return h(tag, { ...(attrs || {}), svg: true }, ...children);
}

export const ICON = {
  ok: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 8.5 3 3 7-7"/></svg>',
  warn: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2 1.5 14h13zM8 7v3M8 12h.01"/></svg>',
  crit: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="6.5"/><path d="M5.5 5.5l5 5M10.5 5.5l-5 5"/></svg>',
  info: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="6.5"/><path d="M8 7.5V11M8 5h.01"/></svg>',
  off: '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="8" cy="8" r="6.5"/><path d="M5 8h6"/></svg>',
};

export function icon(name) {
  const wrap = document.createElement("span");
  wrap.innerHTML = ICON[name] || ICON.info;
  return wrap.firstChild;
}
