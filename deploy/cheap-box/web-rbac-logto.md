# Web RBAC for law-bench — Logto permission model + rollout runbook

The workbench gates **login admission** and **per-route mutations** on the
**permission scopes** issued by the shared Logto IdP
(`https://auth.finddatatech.cloud`). This file is the operational companion to
the code change `add-web-rbac-and-login-ui`; the authorization model itself
lives in `src/web/auth/scopes.py` and
`openspec/changes/add-web-rbac-and-login-ui/design.md`.

The app uses Logto's **idiomatic permission model**:

- A **Logto API Resource** with a stable *indicator* (the audience). The app
  requests it as the OAuth `resource=` parameter.
- **Permission scopes** defined on that resource — the app's authorization
  vocabulary: `content:read`, `content:write`, `admin`.
- **Roles** in Logto are only **named bundles of permissions**. The app never
  reads role names; it reads the **`scope` claim of the access token**, which
  Logto populates with the union of the permissions the user's roles grant.

So changing what a role can do is a **Logto Console edit with no redeploy**, and
the app keeps **no role→scope table** of its own.

**The app is fail-closed.** A login whose access token carries no admitted scope
gets a `403` (`login_denied.html`) and no session cookie; a route whose required
scope the token lacks gets `403`. Do the Logto work below **before** flipping
`AUTH_ADMISSION_MODE` to `enforce`.

> **ID token vs access token.** The authorization-code flow always validates the
> **id_token** for *identity* (sub/name/email). API-resource permission scopes
> are **not** on the id_token — they ride on the **access token** minted for the
> requested `resource`. `/auth/callback` therefore validates both and reads the
> `scope` claim from the access token.

## Scope vocabulary and role bundles

| Permission scope (on the API Resource) | What it unlocks |
|---|---|
| `content:read` | read routes (list rubrics, view a draft, …) |
| `content:write` | content mutations: create/update/delete rubrics, prompts, clauses; generation kicks |
| `admin` | destructive / configuration routes (hard deletes, harbor extract, key management) |

`admin` is normalized in-app to also carry the `"*"` wildcard, so one `admin`
grant satisfies every scope check — including routes that start requiring a new
scope later.

| Logto role (convention) | 中文 | Permissions attached |
|---|---|---|
| `lawbench-admin` | 管理员 | `content:read`, `content:write`, `admin` |
| `lawbench-editor` | 业务编辑 | `content:read`, `content:write` |
| `lawbench-viewer` | 只读 | `content:read` |

> The role **names** are a convention for operators reading the Logto Console.
> The app maps nothing by role name — only the resulting permission scopes
> matter. A user with none of these permissions is denied at `/auth/callback`.

## 1. Logto tenant prerequisite

1. **Register the API Resource.**
   Logto Console → *API Resources* → create a resource with the indicator
   exactly matching `LOGTO_API_RESOURCE` (default
   `https://lawbench.finddatatech.cloud/api`). The indicator is the access
   token's `aud`, so it must match the env value byte-for-byte.
2. **Define the permission scopes** on that resource: `content:read`,
   `content:write`, `admin` (name only; a description is optional).
3. **Create the three roles** (*Roles*) named `lawbench-admin`,
   `lawbench-editor`, `lawbench-viewer`, and attach the permissions from the
   table above (Roles → *Permissions* → select the API Resource → pick scopes).
4. **Assign roles to users.** For each 业务人员 / operator, add the appropriate
   role. At least one human must hold `lawbench-admin` before you enforce.
5. **Configure the app** (step 2 below) with the resource indicator, then
   **verify**: log in and decode the returned **access token** (browser dev
   tools, or `jwt.io`) — confirm a `scope` claim listing the expected
   permission names. `/auth/callback` also logs the granted scopes — see step 2
   of the runbook.

> Reference: [Logto — RBAC](https://docs.logto.io/docs/recipes/rbac/) and
> [Protect your API](https://docs.logto.io/docs/recipes/protect-your-api/).

## 2. Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `LOGTO_API_RESOURCE` | (empty) | API Resource indicator (audience). Empty ⇒ no `resource=` requested; access-token `aud` falls back to the client id and **nobody is admitted**. |
| `LOGTO_SCOPES` | `openid profile email content:read content:write admin` | OIDC + API scopes requested at `/authorize`. |
| `AUTH_ADMITTED_SCOPES` | `content:read,content:write,admin` | Scopes that qualify an identity for a session (comma-separated). |
| `AUTH_ADMISSION_MODE` | `enforce` | `enforce` applies the gate; `warn` logs granted scopes and admits. |

The **API-key channel is exempt** from the admission gate: keys are
admin-provisioned with explicit scopes, so automation keeps working across the
cutover.

## 3. Rollout runbook

Cutover order matters — `enforce` before the tenant is ready locks every human
out. The app's default is `enforce`, so the deploy **must** override it to
`warn` for the first step.

A change is not done when the image is up — it is done when the deployed
instance passes the smoke test below. **Local `pytest` green is necessary but
not sufficient**: the local suite runs entirely against fakes, so it proves the
logic, not the deployment. Same rule for any change: `scripts/smoke_prod.sh`
must be green against prod before it counts as complete.

1. **Deploy in `warn`.**
   ```sh
   # patch deploy/deployment.yaml env, then:
   kubectl apply -f deploy/deployment.yaml
   ```
   Set `AUTH_ADMISSION_MODE=warn`, `LOGTO_API_RESOURCE=<indicator>`, and leave
   `LOGTO_SCOPES` at its default (which already requests the API scopes).
2. **Smoke the deployment.** This mechanically proves the RBAC wiring is live —
   that the running image actually requests `resource=<indicator>` and the API
   scopes, not just that the tenant has them:
   ```sh
   scripts/smoke_prod.sh
   # or against any base URL / with an expected indicator:
   SMOKE_EXPECT_RESOURCE=https://lawbench.finddatatech.cloud/api \
     scripts/smoke_prod.sh https://lawbench.finddatatech.cloud
   ```
   Before this change is deployed the run reports
   `scope missing: content:read content:write admin (got: openid profile email)`
   and `missing resource=` — that is the *old* image still serving. Both lines
   must go green here before you proceed. (The smoke asserts the authorize
   URL's wiring; it needs no credentials, so per-identity behavior is checked by
   the manual walkthrough in step 5.)
3. **Verify scopes in logs.** Log in once per role; the callback logs
   `admission gate (warn): sub=… scopes=…`. Confirm each user's granted scopes
   match the intended role bundle. Empty/short scopes here means step 1.1–1.3
   (resource / permissions / role attachments) is not satisfied — fix before
   proceeding.
4. **Bootstrap an admin.** Confirm at least one user holds `admin` and can log
   in. Existing pre-cutover sessions carry no scopes and will be denied after
   enforcement — users simply re-login.
5. **Enforce.**
   ```sh
   # set AUTH_ADMISSION_MODE=enforce (or remove the override — enforce is default)
   kubectl apply -f deploy/deployment.yaml
   ```
   Then re-run `scripts/smoke_prod.sh` (still green) and walk through per
   identity: an admitted user logs in and lands on `/`; a scope-less user gets
   the `403` 无权访问 page; a `content:read`-only user is refused a mutation
   (e.g. `PATCH` a rubric → `403`). This manual pass is the last gate before the
   change is complete.

## 4. Rollback

Flip back and redeploy — this is a config-only change, no schema or data
migration:

```sh
# AUTH_ADMISSION_MODE=warn
kubectl apply -f deploy/deployment.yaml
```

`warn` admits everyone again (logging scopes), so a mis-configured resource no
longer blocks login. Reverting the image also works but is slower.
