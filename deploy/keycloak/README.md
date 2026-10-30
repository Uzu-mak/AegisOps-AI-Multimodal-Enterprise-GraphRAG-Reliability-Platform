# Keycloak realm for AegisOps sign-in

`aegisops-realm.json` is imported the first time the `keycloak` service starts (`COMPOSE_PROFILES=auth`).
It defines:

- **Roles:** `viewer`, `engineer`, `reviewer`, `admin` (see `app/core/oidc.py` for what each allows).
- **Client:** `aegisops-console`, a public client using the authorization-code flow with PKCE (S256).
  It redirects back to `http://localhost:8000/console/`, and the token's audience includes the client.
- **Starter users:** `jeremiah` (engineer and admin), `bismark` (reviewer), `plant.viewer` (viewer).
  Each one starts with the temporary password `ChangeMe-2026!` and must set a new one at first sign-in.

These users are for local development and demos only.

**Editing the realm.** The import runs only when the realm doesn't exist yet. To start over, run
`docker compose --profile auth down` and delete the `aegisops_keycloak_data` volume.
That also deletes any password changes.

**Keycloak admin console.** Open http://localhost:8080/admin and sign in with `KEYCLOAK_ADMIN` and
`KEYCLOAK_ADMIN_PASSWORD` from `.env`. The defaults are in `docker-compose.yml`; change them before
running anywhere other than your own machine.

**Using a different provider** (Entra ID, Okta, Clerk). Set these in `.env`:

- `OIDC_ISSUER`
- `OIDC_CLIENT_ID`
- `OIDC_JWKS_URL`
- `OIDC_ROLES_CLAIM`
- if the provider's paths differ from Keycloak's: `OIDC_AUTHORIZATION_ENDPOINT`, `OIDC_TOKEN_ENDPOINT`,
  `OIDC_END_SESSION_ENDPOINT`

No code changes are needed.
