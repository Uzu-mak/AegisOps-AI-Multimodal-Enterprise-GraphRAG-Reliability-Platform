import { h, put } from "../lib/dom.js";

/* --------------------------------------------------------------- dialog */

export const dialog = document.getElementById("dialog");
export let dialogReturnFocus = null;

export function openDialog(titleText, body, foot) {
  dialogReturnFocus = document.activeElement;
  const inner = dialog.querySelector(".dialog-inner");
  put(inner, 
    h("div", { class: "dialog-head" },
      h("h2", { id: "dialog-title" }, titleText),
      h("button", { class: "btn btn-quiet dialog-close", type: "button", onclick: closeDialog },
        h("span", { class: "visually-hidden" }, "Close"),
        h("span", { "aria-hidden": "true" }, "✕")),
    ),
    body,
    foot ? h("div", { class: "dialog-foot" }, foot) : null,
  );
  if (!dialog.open) dialog.showModal();
  const first = inner.querySelector("input, select, textarea, [data-autofocus]");
  (first || inner.querySelector(".dialog-close")).focus();
}

export function closeDialog() {
  if (dialog.open) dialog.close();
}
dialog.addEventListener("close", () => {
  if (dialogReturnFocus && document.contains(dialogReturnFocus)) dialogReturnFocus.focus();
});
dialog.addEventListener("click", (e) => { if (e.target === dialog) closeDialog(); });
