import { dialog } from "../components/dialog.js";
import { render } from "../console.js";
import { s } from "./dom.js";
import { auth, refresh, signIn } from "./auth.js";

export const API = "/api/v1";
/* ------------------------------------------------------------------ API */

export async function api(path, { method = "GET", body, timeout = 20000, params, retried = false } = {}) {
  const url = new URL(API + path, location.origin);
  if (params) for (const [k, v] of Object.entries(params)) if (v !== "" && v !== null && v !== undefined) url.searchParams.set(k, v);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(url, {
      method,
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(sessionStorage.getItem("aegis-token") ? { Authorization: `Bearer ${sessionStorage.getItem("aegis-token")}` } : {}) },
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (res.status === 401) {
      if (auth.mode === "oidc") {
        // The access token expired or was revoked: refresh once, else sign in again.
        if (!retried && await refresh()) return api(path, { method, body, timeout, params, retried: true });
        signIn();
      } else {
        showSignIn();
      }
    }
    if (!res.ok) return { ok: false, status: res.status, data, error: describeError(res.status, data) };
    return { ok: true, status: res.status, data };
  } catch (err) {
    const error = err.name === "AbortError"
      ? `The API took longer than ${Math.round(timeout / 1000)} s to answer ${path}. Check System health for a stalled dependency.`
      : `Can't reach the AegisOps API. Check that the api service is running, then reload.`;
    return { ok: false, status: 0, data: null, error };
  } finally {
    clearTimeout(timer);
  }
}

export function describeError(status, data) {
  const detail = data && typeof data === "object" ? data.detail : data;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).filter((p) => p !== "body").join(".") || "request"}: ${d.msg}`).join("; ");
  }
  if (typeof detail === "string" && detail) return detail;
  if (status === 404) return "That record doesn't exist.";
  if (status >= 500) return `The API returned an error (${status}). Check the api service logs.`;
  return `Request failed (${status}).`;
}

export async function fetchAllMemories(params = {}) {
  const out = [];
  const pageSize = 200;
  for (let offset = 0; ; offset += pageSize) {
    const r = await api("/memories", { params: { ...params, limit: pageSize, offset } });
    if (!r.ok) return { ok: false, error: r.error, items: out };
    const items = r.data?.items || [];
    out.push(...items);
    if (items.length < pageSize) break;
  }
  return { ok: true, items: out };
}

export function showSignIn() {
  if (document.getElementById("api-signin")) return;
  const box = document.createElement("dialog"); box.id = "api-signin";
  const form = document.createElement("form");
  const label = document.createElement("label"); label.textContent = "API access token ";
  const input = document.createElement("input"); input.type = "password"; input.required = true; input.autocomplete = "off";
  const submit = document.createElement("button"); submit.type = "submit"; submit.textContent = "Sign in";
  label.append(input); form.append(label, submit); box.append(form); document.body.append(box);
  form.addEventListener("submit", event => { event.preventDefault(); sessionStorage.setItem("aegis-token", input.value); box.close(); box.remove(); render(); });
  box.showModal(); input.focus();
}
