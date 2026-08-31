# mcp.token118.com — AI Gateway & Registry auth posture (Logto)

Changes: `swap-mcp-registry-idp-to-logto` + `repair-shared-logto-instance` (openspec).
The mcp-gateway-registry stack at `/opt/mcp-gateway-registry` (america box,
23.144.68.246) authenticates against the shared Logto instance instead of its private
Keycloak realm.

## PRODUCTION TOPOLOGY (verified 2026-08-30)

- **The production Logto is the china-box k3s pod** (`logto` deployment, namespace
  `idp`, on 124.223.42.3): `auth.token118.com` resolves there, backed by the
  china-local Postgres (`postgres-0`, `postgres.idp.svc.cluster.local:5432/logto`).
  The idp stack was migrated there (~2026-08-29) as k3s workloads.
- **The america box's `/opt/tokenvault-idp` compose stack is a leftover copy** of the
  pre-migration idp stack. It shares the same OIDC key lineage (tokens minted by either
  instance validate against both JWKS), but it serves NO production traffic and its DB
  state diverges from production. Retirement is a follow-up; do not use it for user or
  app management.
- The gateway auth-server's `LOGTO_URL` therefore points at the public production
  endpoint (`https://auth.token118.com`) — the login code exchange must hit the same
  instance that issued the authorization code.
- The china k3s nodes have polluted DNS (`mesh.finddata.cn` wildcard search — same
  issue as `docs/public-api-deploy.md` §4.1). The logto deployment is patched with
  `dnsPolicy: None` + kube-dns-only `dnsConfig`; without it the pod intermittently
  cannot reach its Postgres (`ConnectionError: connection timeout` → 500s on
  discovery/authorize/experience and broken password sign-in). Other `idp` pods
  (newapi, nango, …) likely need the same pin.

## Identity provider

| Item | Value |
|---|---|
| Logto (shared, production) | china box k3s `idp/logto` pod; image `svhd/logto:latest` (running digest `sha256:a9ebd673…34435f2`; a k3s digest-pin attempt was reverted due to ErrImagePull — re-pin via a registry mirror later) |
| Public endpoint | `https://auth.token118.com` (issuer `https://auth.token118.com/oidc`, ES384) |
| Legacy endpoint | `https://logto.tokenvault.vip` has a WRONG public DNS record (124.233.42.3 — a typo of 124.223.42.3); serves 200 via hairpin from the box. Fix DNS when repointing law-bench/NewAPI |
| Web app | `mcpgatewayweb` (Traditional, **first-party** `is_third_party=false`) — redirect `https://mcp.token118.com/oauth2/callback/logto`; scopes `openid offline_access profile email roles` (third-party apps reject profile/email/roles; first-party required for the userinfo to carry username/roles) |
| M2M app | `mcpgatewaym2m` (MachineToMachine) |
| API resource | `https://mcp.token118.com/api` (M2M token `aud`; Logto requires `resource` on client_credentials) |
| Admin authorization | Logto role `registry-admins` (default tenant) → gateway maps `roles` claim (userinfo) to groups → Mongo `mcp_scopes_default.registry-admins` |
| Gateway admin user | `mcpadmin` / `mcpadmin@token118.com` (default tenant, role `registry-admins`); credentials in `/root/.mcp_logto_creds` on the america box (0600) |
| Management API (`m-default`) | RETIRED: rotation attempts (secret column + application_secrets + pod restart) are not honored by the running build (`invalid_client` persists). Use a new first-party M2M app if management automation is needed |
| App credentials | `/root/.mcp_logto_creds` on the america box (0600) |

## Machine-to-machine access (automation)

```sh
curl -u "mcpgatewaym2m:$LOGTO_M2M_CLIENT_SECRET" \
  -d 'grant_type=client_credentials&resource=https%3A%2F%2Fmcp.token118.com%2Fapi' \
  https://auth.token118.com/oidc/token
# → access_token (ES384 JWT, 1h) → Authorization: Bearer <token> on https://mcp.token118.com/api/*
```

## Deployment shape

- auth-server runs the locally built image `mcp-auth-server:logto`
  (`docker/Dockerfile.auth`, commits on `main` in `/opt/mcp-gateway-registry`, branch
  `logto-provider` marks upstream base `d40a5a0`). Patch: `providers/logto.py`,
  factory branch, `oauth2_providers.yml` `logto` entry, `base.py` verifier accepts
  ES384, first-party scopes (`openid offline_access profile email roles`).
- `AUTH_PROVIDER=logto`; `LOGTO_URL`/`LOGTO_EXTERNAL_URL=https://auth.token118.com`
  (production); auth-server service in `docker-compose.prebuilt.yml` carries the env
  allowlist and joins `tokenvault-idp_default` (external network) for the leftover
  local Logto, kept only as fallback.
- Keycloak + keycloak-db are **stopped**; volumes retained until the change is
  archived. Keycloak bootstrap secrets in `.env` are scrubbed to `RETIRED_SEE_…`.

## Rollback

1. `cd /opt/mcp-gateway-registry && cp .env.bak-logto .env && cp docker-compose.prebuilt.yml.bak-logto docker-compose.prebuilt.yml`
2. `docker compose -f docker-compose.prebuilt.yml up -d auth-server keycloak keycloak-db`
   (prebuilt auth-server image tag restored by the yml backup; Keycloak volumes intact)

## Follow-ups (out of scope of these changes)

- Fix the `logto.tokenvault.vip` DNS typo (124.233.42.3 → 124.223.42.3 or retire the
  host), then repoint law-bench and NewAPI OIDC to `auth.token118.com`.
- Retire the america leftover idp compose stack once law-bench/NewAPI are confirmed on
  the china Logto.
- Pin the china k3s logto image by digest via a registry mirror (direct Docker Hub
  pulls fail from china; the `latest` tag is a drift risk).
- Apply the `dnsPolicy: None` pin to the other `idp` pods (newapi, nango, …).
- Optional upstream PR for the Logto provider.
- The registry service container still carries `AUTH_PROVIDER=keycloak` env (unused for
  token validation, which is delegated to auth-server `/validate`); align or clear it on
  the next registry image upgrade.

## Registry usage

The registry's first registered server is law-bench (change
`expose-lawbench-mcp-via-gateway`): see `mcp-gateway-registration.md` for the
deployment, registration, and M2M-scope (`idp_m2m_clients` + the `"logto"`
scope-mapping fix) details.
