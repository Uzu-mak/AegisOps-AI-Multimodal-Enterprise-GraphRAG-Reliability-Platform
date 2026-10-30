// Sign-in for AUTH_MODE=oidc: authorization code flow with PKCE against the
// configured provider (Keycloak by default), done in the browser with no
// library. Tokens live in sessionStorage (this tab only) and are refreshed
// before they expire. In local and token modes this does nothing.

const K = { access: "aegis-token", refresh: "aegis-refresh", exp: "aegis-token-exp", id: "aegis-id-token", verifier: "aegis-pkce", state: "aegis-oidc-state", back: "aegis-return-to" };
const get = (k) => { try { return sessionStorage.getItem(k); } catch { return null; } };
const set = (k, v) => { try { if (v === null || v === undefined) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch {} };

export const auth = { mode: "local", config: null, user: null, error: null };

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (n = 48) => b64url(crypto.getRandomValues(new Uint8Array(n)));
const redirectUri = () => `${location.origin}/console/`;

function store(tokens) {
  set(K.access, tokens.access_token);
  if (tokens.refresh_token) set(K.refresh, tokens.refresh_token);
  if (tokens.id_token) set(K.id, tokens.id_token);
  set(K.exp, String(Date.now() + (tokens.expires_in || 300) * 1000));
  scheduleRefresh();
}

function clear() { for (const k of [K.access, K.refresh, K.exp, K.id]) set(k, null); }

/** Send the browser to the provider's sign-in page. */
export async function signIn() {
  if (auth.mode !== "oidc" || !auth.config) return;
  const verifier = randomString(48);
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const state = randomString(16);
  set(K.verifier, verifier); set(K.state, state); set(K.back, location.hash || "#/overview");
  const q = new URLSearchParams({ client_id: auth.config.client_id, redirect_uri: redirectUri(), response_type: "code", scope: "openid profile email",
    code_challenge: challenge, code_challenge_method: "S256", state });
  location.assign(`${auth.config.authorization_endpoint}?${q}`);
}

export function signOut() {
  const idToken = get(K.id);
  clear();
  if (auth.mode !== "oidc" || !auth.config) return location.reload();
  const q = new URLSearchParams({ client_id: auth.config.client_id, post_logout_redirect_uri: redirectUri(), ...(idToken ? { id_token_hint: idToken } : {}) });
  location.assign(`${auth.config.end_session_endpoint}?${q}`);
}

async function tokenRequest(body) {
  const res = await fetch(auth.config.token_endpoint, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: auth.config.client_id, ...body }) });
  if (!res.ok) throw new Error(`Sign-in failed at the identity provider (${res.status})`);
  return res.json();
}

/** Use the refresh token for a new access token. True on success. */
export async function refresh() {
  const rt = get(K.refresh);
  if (auth.mode !== "oidc" || !rt) return false;
  try { store(await tokenRequest({ grant_type: "refresh_token", refresh_token: rt })); return true; }
  catch { clear(); return false; }
}

let timer = null;
function scheduleRefresh() {
  clearTimeout(timer);
  const ms = Number(get(K.exp) || 0) - Date.now() - 60000;
  if (ms > 0) timer = setTimeout(refresh, ms);
}

async function finishRedirect(params) {
  const err = params.get("error");
  if (err) throw new Error(params.get("error_description") || err);
  if (params.get("state") !== get(K.state)) throw new Error("The sign-in response didn't match this browser tab. Sign in again.");
  store(await tokenRequest({ grant_type: "authorization_code", code: params.get("code"), redirect_uri: redirectUri(), code_verifier: get(K.verifier) || "" }));
  set(K.verifier, null); set(K.state, null);
  const back = get(K.back) || "#/overview";
  set(K.back, null);
  history.replaceState(null, "", `${location.pathname}${back}`);
}

/** Run before the first render: learn the mode, finish a sign-in, load who is signed in.
 *  Returns false when the browser is being sent to the sign-in page. */
export async function initAuth() {
  try {
    const res = await fetch("/api/v1/auth/config");
    auth.config = res.ok ? await res.json() : { mode: "local" };
  } catch { auth.config = { mode: "local" }; }
  auth.mode = auth.config.mode || "local";
  if (auth.mode !== "oidc") return;
  const params = new URLSearchParams(location.search);
  try {
    if (params.has("code") || params.has("error")) await finishRedirect(params);
  } catch (e) {
    auth.error = String(e.message || e);
    history.replaceState(null, "", `${location.pathname}${location.hash}`);
    return;
  }
  if (!get(K.access) || Number(get(K.exp) || 0) < Date.now() + 5000) {
    if (!(await refresh())) { await signIn(); return false; }
  }
  scheduleRefresh();
  try {
    const me = await fetch("/api/v1/auth/me", { headers: { Authorization: `Bearer ${get(K.access)}` } });
    if (me.status === 401) { clear(); await signIn(); return false; }
    auth.user = await me.json();
  } catch {}
  return true;
}

export const signedIn = () => !!(auth.user && auth.user.signed_in);
export const hasRole = (...roles) => auth.mode !== "oidc" || roles.some((r) => (auth.user?.roles || []).includes(r));
export const ROLE_LABEL = { admin: "Administrator", engineer: "Engineer", reviewer: "Reviewer", viewer: "Viewer" };
export function roleSummary() {
  const r = (auth.user?.roles || []).filter((x) => ROLE_LABEL[x]);
  return r.map((x) => ROLE_LABEL[x]).join(", ") || "No role";
}
