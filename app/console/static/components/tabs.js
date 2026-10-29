import { h } from "../lib/dom.js";

/** WAI-ARIA tabs: arrow keys, Home and End move between tabs; only the
 *  selected tab is in the tab order. items: [{ id, label, panel, onSelect }]. */
export function tabs(items, label) {
  const list = h("div", { role: "tablist", class: "tab-list", "aria-label": label });
  const buttons = new Map();
  const panels = new Map();
  const select = (id, focus = false) => {
    for (const [key, btn] of buttons) {
      const on = key === id;
      btn.setAttribute("aria-selected", String(on));
      btn.tabIndex = on ? 0 : -1;
      panels.get(key).hidden = !on;
    }
    items.find((it) => it.id === id)?.onSelect?.();
    if (focus) buttons.get(id).focus();
  };
  const ids = items.map((it) => it.id);
  for (const it of items) {
    const btn = h("button", { role: "tab", type: "button", class: "tab", id: `tab-${it.id}`, "aria-controls": `panel-${it.id}`, onclick: () => select(it.id) }, it.label);
    btn.addEventListener("keydown", (e) => {
      let j = ids.indexOf(it.id);
      if (e.key === "ArrowRight") j = (j + 1) % ids.length;
      else if (e.key === "ArrowLeft") j = (j - 1 + ids.length) % ids.length;
      else if (e.key === "Home") j = 0;
      else if (e.key === "End") j = ids.length - 1;
      else return;
      e.preventDefault();
      select(ids.at(j), true);
    });
    buttons.set(it.id, btn);
    list.append(btn);
    panels.set(it.id, h("div", { role: "tabpanel", class: "tab-panel", id: `panel-${it.id}`, "aria-labelledby": `tab-${it.id}`, tabindex: "0" }, it.panel));
  }
  select(ids[0]);
  return { el: h("section", { class: "tabs" }, list, ...panels.values()), select };
}
