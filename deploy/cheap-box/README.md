# cheap cluster — law-bench + AI Gateway on finddatatech.cloud

law-bench and a second copy of the mcp-gateway-registry stack now run on the
"cheap" k3s fleet. **The america box (23.144.68.246) is retired (offline since
2026-09-09) — do not access it.** Everything it used to serve has moved to the
cheap cluster. This file is the cheap-side runbook; see
`deploy/america-box/*.md` for the retired original stack and for anything
auth-related that is shared (Logto app registrations, group→scope mapping).

## Public names

| Host | Edge | Backend |
|---|---|---|
| `lawbench.finddatatech.cloud` | cheap1 Caddy | `100.64.0.{8,9,13}:30820` (svc `law-bench`) |
| `lawbench-mcp.finddatatech.cloud` | cheap1 Caddy (900 s timeouts, `flush_interval -1`) | `:30840` (svc `law-bench-mcp`) |
| `mcp.finddatatech.cloud` | cheap1 Caddy | `127.0.0.1:18080` (gateway nginx, same box) |
| `auth.finddatatech.cloud` | chengsi nginx (124.220.7.175, certbot) | `100.64.0.3:3001` (docker fd-logto on xinru) |

`lawbench.*`, `lawbench-mcp.*` and `mcp.*` resolve to **103.236.89.212**;
`auth.finddatatech.cloud` resolves to **124.220.7.175**. DNS records are added by
hand in DNSPod. The token118.com domain family is **retired** (foreign domain,
no longer manageable) — the shared Logto IdP lives at `auth.finddatatech.cloud`.

## Hosts

| Name | Reach | Role |
|---|---|---|
| cheap1 | `root@100.64.0.11` (ssh key from cheap4) | Caddy TLS edge + gateway docker compose at `/opt/mcp-gateway-registry` |
| cheap4 | `root@100.64.0.8` | the only node with a working `kubectl`; law-bench pods are pinned to node `liuliangculkrd838gqz` |

Reach both boxes over Tailscale (`100.64.0.11`, `100.64.0.8`). cheap1's own
`kubectl` is broken (`x509: certificate signed by unknown authority` against
`127.0.0.1:6443`) — do cluster work from cheap4 (or cheap6, the control-plane
node, which also has a working `kubectl`).

Tailscale between these boxes is DERP-relayed at roughly 180 KB/s and nested-ssh
streams truncate past ~10 MB, so large payloads go through the in-cluster
Harbor (`harbor.finddatatech.cloud:8080`, see "Harbor" below) rather than over
the tunnel.

## Harbor (in-cluster, ns `harbor`)

- **URL:** `http://harbor.finddatatech.cloud:8080` — cheap1 Caddy reverse proxy
  → cheap-4 NodePort `30880`. HTTP only (insecure registry).
- **Direct (same tailnet):** `100.64.0.8:30880` (cheap-4, where the pod runs);
  other nodes also expose the NodePort (`100.64.0.{9,13,14,15}`).
- **Registry backend:** RustFS S3 (`100.64.0.11:9000`, bucket `harbor`) — the
  storage is durable now, unlike the earlier `emptyDir` Harbor whose images
  died with the pod. `EXT_ENDPOINT=http://172.16.0.186:30880` (caddy tunnel
  landing) is set in the harbor-core ConfigMap.
- **Helm:** release `harbor`, chart version 2.15.1; values copy at
  `D:\code\tmp-harbor\values-cheap-harbor.yaml`.
- **Admin password** was rotated on 2026-09-08 (the secret's
  `HARBOR_ADMIN_PASSWORD` is only the bootstrap value and is stale) — current
  value lives in the operator's private notes, not in this repo.
- **Robot accounts** (project → members → robots): `cheap-mcp-pull` (pull for
  the `finddata` project — used by `fd-mcp/harbor-finddata-pull` and
  `fd-mcp/harbor-local-pull`) and `robot$pull-deploy` (used by
  `law-craw-web/harbor-pull`). Passwords likewise live in the operator's
  private notes.
- **Public projects** (anonymous pull): `library`, `finddata`, `infra`.
- **Node selector:** all Harbor pods are pinned to
  `kubernetes.io/hostname=liuliangCUlKrd838GQZ` (cheap-4); audit this hostname
  after any rebuild.
- **Image layout:** CI (`build-and-push.yml`) pushes to project `law-bench`
  (`law-bench/law-template:sha-<git>`); the `finddata` project carries the
  fd-* services (`finddata/law-bench`, `finddata/fd-open-data-mcp`, …) pushed
  by hand/deploy scripts.

## Networking constraints (provider layer, not fixable from inside)

cheap1 has no public interface: `ens17 = 172.16.0.123/12`, egress
`103.236.89.212`. Inbound 80/443 depend on a provider-side port forward.

- **The provider swapped the public IP to `103.236.89.212` (~2026-09-04) and the
  swap restored inbound 80/443.** The old `103.236.92.141` went dark on
  ~2026-08-31 17:00 (port forward dead at the provider layer: every host on it
  returned 000 from america/cheap4/china while Caddy answered on loopback and
  iptables was ACCEPT; ACME failed both `http-01` and `tls-alpn-01` with
  connect timeouts). Only the provider could fix it — they fixed it by
  re-IP-ing the box. **Any hard-coded copy of the old IP is now stale**, notably
  the law-bench pod's `hostAliases` pin (see `deploy/deployment.yaml`) and the
  DNSPod A record for `auth.token118.com`, which still pointed at the old IP
  after the swap (verified 2026-09-05 via 223.5.5.5).
- **Outbound UDP/123 is blocked as well**, so `timesyncd` can never converge
  (`System clock synchronized: no` permanently). See "Clock" below.
- `172.16.0.0/12` is *not* routable between cheap1 and cheap4 — use tailscale
  `100.64.0.x` for anything cross-node.

## Caddy on cheap1

`/etc/caddy/Caddyfile`. The packaged unit (2.6.2) has **no `ExecReload`**, so
`systemctl reload caddy` is a no-op:

```sh
caddy validate --config /etc/caddy/Caddyfile
caddy reload   --config /etc/caddy/Caddyfile   # admin API on 127.0.0.1:2019
```

Certificates: `/var/lib/caddy/.local/share/caddy/certificates/acme-v02.api.letsencrypt.org-directory/<host>/`.

The file still carries ~10 blocks for names that resolve to america
(`*.tokenvault.vip`, `file`/`file-console`/`lawbench.token118.com`, and
`mcp.token118.com → 127.0.0.1:18080`). They are dead weight rather than a live
footgun — those names never arrive here — but they should be pruned.

## law-bench on the cheap cluster (ns `law-bench`)

`deploy/deployment.yaml`, `deploy/mcp-deployment.yaml`, `deploy/service.yaml`,
`deploy/pvc.yaml` describe the running state. Two cheap-specific deviations are
baked into those manifests:

- **`nodeSelector: kubernetes.io/hostname: liuliangculkrd838gqz` and no
  `imagePullSecrets`.** Historical reason: the earlier in-cluster Harbor kept
  `registry-data` on an `emptyDir`, so `harbor.local/law-bench/law-template:sha-2c502d7`
  only existed in that node's containerd store. The Harbor has since been rebuilt
  with an S3 backend (see "Harbor" above), but the manifests still pin the node
  and rely on `IfNotPresent` + the locally imported image; switching them to the
  durable registry reference plus a pull secret is still owed.
- **`PYTHONPATH=/opt/mcp/lib/pkgs:/app` plus a read-only hostPath mount** of
  `/opt/lawbench-mcp-pkgs` on the MCP pod. `sha-2c502d7` was built *without* the
  `fd-coding-law-bench-mcp` build context, so `/app/.venv` has no MCP package.
  Instead of rebuilding, the deps were installed on the node:

  ```sh
  uv pip install --target /opt/lawbench-mcp-pkgs /root/fd-coding-law-bench-mcp
  ```

  This is why `fd_coding_law_bench_mcp/__init__.py` guards its
  `parents[3]` repo-root insertion with a length check: a `--target` install is
  shallower than a source checkout and would otherwise `IndexError` on import.
  Rebuilding the image with the MCP context is the clean fix and retires both the
  volume and the env var.

`kubectl set image` is not used here (it was refused as an opaque mutation) —
patch the manifest and `kubectl apply -f`.

## Gateway compose on cheap1

Lift-and-shift of the america compose stack into `/opt/mcp-gateway-registry`
(`docker-compose.prebuilt.yml`), *not* the upstream Helm chart. nginx on
`127.0.0.1:18080`; Caddy fronts it. `openbao` runs in dev mode, so its state is
ephemeral and nothing was migrated. Secrets were regenerated on cheap1 except
`LOGTO_CLIENT_SECRET` and `LOGTO_M2M_CLIENT_SECRET`, which had to be the same
values as america's because both stacks talk to the same Logto apps.

Five things are easy to miss:

1. **`extra_hosts: ["auth.finddatatech.cloud:host-gateway"]`** on both the `registry`
   and `auth-server` services. The IdP is remote (nginx on chengsi → xinru
   docker), so a container resolving `auth.finddatatech.cloud` through the host
   DNS gets the public IP; `host-gateway` (the docker bridge, `192.168.0.1`
   here) reaches the local Caddy, which has the valid cert and proxies on to the
   IdP. `/etc/hosts` on the host itself pins
   `auth.finddatatech.cloud` and `mcp.finddatatech.cloud` to `127.0.0.1` for the
   same reason. Containers do not inherit the host `/etc/hosts`, hence both
   fixes.
2. **`GATEWAY_ADDITIONAL_SERVER_NAMES=mcp.finddatatech.cloud`** — templated into
   `server_name localhost {{ADDITIONAL_SERVER_NAMES}};` at runtime by
   `registry/core/nginx_service.py`.
3. **`SSRF_ALLOWED_CIDRS=100.64.0.8/32`** — required, see below.
4. **`/var/log/containers/ai-registry`** is a host bind mount and the registry
   container runs as uid 1000 (`appuser`); without `chown 1000:1000` +
   `chmod 750` nginx's `-t` fails with `Permission denied`.
5. **The login-bundle hotfix must be re-applied after every container
   recreation** — it patches a file inside the image, not a bind mount:

   ```sh
   docker exec <registry> sed -i 's|`http://localhost:8888`|window.location.origin|g' \
     /app/frontend/build/static/js/index.BpTler7s.js
   ```

   Otherwise the browser posts the login exchange to `localhost:8888`.

   The same bundle also carries a second patch: the login button label is
   `寻数科技账号登录` (source: `frontend/src/pages/Login.tsx`; bundle string
   `children:[\`Continue with \`,e.display_name]` → `children:[\`寻数科技账号登录\`]`).
   Re-apply it together with the hotfix above, and hard-refresh the browser —
   the bundle filename hash does not change when patched in place.

6. **The nginx `logto` OAuth location blocks must be re-applied after every
   container recreation / re-render** — same class of patch (2026-09-10):
   upstream's template ships cognito/entra/okta/github/google/auth0 +
   keycloak/pingfederate blocks but no logto, so `/oauth2/login/logto` used to
   fall through to the SPA. The fix adds
   `location /oauth2/{login,callback}/logto` (mirroring cognito) to the
   generated `/etc/nginx/conf.d/nginx_rev_proxy.conf` **and** to the template
   `/app/docker/nginx_rev_proxy_http_only.conf` (host source:
   `docker/nginx_rev_proxy_http_only.conf`); the `_http_and_https` variant
   already had them. Without the blocks, clicking login never leaves the SPA.

Inside that container the app's interpreter is `/app/.venv/bin/python`; plain
`python3` lacks `httpx` and cannot import `registry.utils.url_guard`.

### SSRF guard: why `SSRF_ALLOWED_CIDRS` and not `SSRF_ALLOWED_HOSTS`

The gateway proxies to the law-bench backend over tailscale at
`http://100.64.0.8:30840/mcp`. `registry/utils/url_guard.py` blocks CGNAT
`100.64.0.0/10` explicitly (RFC 6598 — CPython's `is_private` does not flag it),
so registration failed with `UrlValidationError`. America was never affected
because `23.144.68.246` is public.

The guard has two operator knobs, and **only one of them works for a literal-IP
target**: `validate_url` calls `_is_blocked_ip(hostname, allowlist)` *without*
`trusted_hostname=`, so the `hosts` allowlist is consulted only on the
DNS-resolution path. Setting `SSRF_ALLOWED_HOSTS=100.64.0.8` is inert and still
fails with `targets blocked/private IP 100.64.0.8` (note "targets", not "resolves
to" — that wording distinguishes the two code paths). The working entry is:

```
SSRF_ALLOWED_HOSTS=
SSRF_ALLOWED_CIDRS=100.64.0.8/32
```

A `/32` was chosen over a wider range on purpose: `100.64.0.9` still fails the
check, and the backend stays inside the tailscale tunnel rather than being
exposed publicly. Widening this weakens an SSRF control — get explicit sign-off
first.

## Clock

Logto validates `iat` with **zero leeway**. Because cheap1 cannot NTP-sync
(UDP/123 blocked), a single second of lag makes every token fail with
`The token is not yet valid (iat)` at `providers/logto.py:197`, which surfaces as
`GET /validate 401` and a gateway that appears to have broken auth.

Keep cheap1 a few seconds **ahead** of the issuer by stepping it from the Logto
container's own clock (read via SSH on xinru — the IdP is a docker container
there, not a k8s `idp` namespace anymore):

```sh
T=$(( $(ssh ubuntu@134.175.46.69 'sudo docker exec fd-logto date +%s') + 5 ))
date -s "@$T" && hwclock -w        # on cheap1
```

Stepping it merely level with cheap4 is not enough. A TCP-based sync (an hourly
`htpdate`-style timer parsing an HTTPS `Date:` header) is the durable fix and is
still owed; until it exists, expect the skew — and the 401s — to return.

## Registering law-bench in the cheap gateway

```sh
python scripts/infra/register_mcp_gateway.py register \
    --gateway-url https://mcp.finddatatech.cloud \
    --backend-url http://100.64.0.8:30840/mcp \
    --provider-url https://lawbench.finddatatech.cloud
```

Needs `MCP_HTTP_TOKEN` (k8s secret `law-bench-mcp`), `LOGTO_M2M_APP_ID` /
`LOGTO_M2M_CLIENT_SECRET` (both in `/opt/mcp-gateway-registry/.env` as
`LOGTO_M2M_CLIENT_ID` / `LOGTO_M2M_CLIENT_SECRET`) in the environment, plus the
`SSRF_ALLOWED_CIDRS` entry above on the gateway side. While the edge is down, run
it from cheap1 against `http://mcp.finddatatech.cloud:18080` — the `/etc/hosts`
pin sends that to the local nginx and skips TLS, and nginx's `server_name`
matching ignores the port.

**Prerequisite — M2M group mapping in Mongo (`idp_m2m_clients`).** Logto M2M
access tokens carry **no** `roles`/groups claim (verified 2026-09-09: full JWT
payload has only `jti/sub/iat/exp/client_id/iss/aud`, and even an explicit
`scope=roles` request adds nothing), so the auth-server cannot resolve groups for
the M2M client and every `/api/servers/*` call 403s with "You do not have
permission to register new services". The fix is the same `idp_m2m_clients`
mapping america used (see `deploy/america-box/mcp-gateway-registration.md`):
insert `{client_id: "<m2m-app-id>", groups: ["registry-admins"], enabled: true,
provider: "logto"}` into the `mcp_registry` database (`mcp-mongodb` container,
root user `admin`, password from the auth-server's `DOCUMENTDB_PASSWORD` env).
The auth-server reads the collection per request (`mongodb_groups_enrichment.py`)
— no restart needed. After a gateway database wipe or a new M2M app id, re-insert
this row or the register call fails again.

Verified state (2026-09-09, new IdP `auth.finddatatech.cloud`): register → 201,
catalog entry `/law-bench` `group-restricted` /
`allowed_groups=registry-admins` / `auth_scheme=api_key` (`X-API-Key`) /
`num_tools=52` / `status=active` (no toggle needed).
Fail-closed confirmed: anonymous `POST /law-bench/mcp` → 401, anonymous
`GET /api/servers` → 401, law-bench appears in no anonymous catalog, and direct
(ungatewayed) backend `POST :30840/mcp` → 401. Note: the `scope` claim is not in
the token unless the client_credentials request explicitly passes `scope=…`
(`scope=gateway:access` does land in the JWT) — the register script does not need
it, groups come from `idp_m2m_clients`.

An authenticated MCP session using the **M2M** token still 401s on
`/law-bench/mcp`. That token opens `/api/*` but the proxy path wants user-facing
scopes; startup logs `legacy_scope_missing_tools` for `mcp-registry-admin`,
`mcp-servers-unrestricted/{read,execute}` and `federation-service`. The M2M app's
groups were deliberately **not** escalated. Proof that the proxy hop itself works
comes from the registry's own health check reaching the backend and counting 52
tools.
