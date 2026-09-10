## 1. Implementation

- [x] 1.1 Add `--proxy-headers --forwarded-allow-ips='*'` to the origin uvicorn line in `scripts/docker-entrypoint.sh`.
- [x] 1.2 Add the same flags to the public-app uvicorn line in `scripts/docker-entrypoint.sh`.

## 2. Build & deploy

- [x] 2.1 Push to `main` → CI (`.github/workflows/build-and-push.yml`) builds + pushes image tagged `sha-<short>` to Harbor.
- [x] 2.2 Update both image refs in `deploy/deployment.yaml` to the new `sha-<short>`; commit + push the roll.
- [x] 2.3 `kubectl apply -f deploy/deployment.yaml` on the `law-bench` cluster; wait for rollout.

## 3. Verify (against https://lawbench.token118.com)

- [ ] 3.1 Authenticated fetch of an HTML page: `<link href="...style.css">` and `<script src="...app.js">` resolve to `https://` (no `http://`).
- [ ] 3.2 Browser check after login: pages show CSS styling, not bare HTML.
