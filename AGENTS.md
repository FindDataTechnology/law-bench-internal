# law-bench agent instructions

## Spec-driven workflow (OpenSpec)

This project uses [OpenSpec](https://openspec.dev) (CLI v1.8.0) for change management. Specs live in `openspec/specs/`, active changes in `openspec/changes/`, archived changes in `openspec/archive/`.

When the user asks to build, fix, or change a feature, use the OpenSpec workflow instead of implementing directly:

- New change: `/opsx:propose` (or skill `openspec-propose`) — creates the change and generates proposal/spec/design/tasks artifacts. Planning only; stop after artifacts are done.
- Implement an approved change: `/opsx:apply` (`openspec-apply-change`).
- Update artifacts of an existing change: `/opsx:update` (`openspec-update-change`).
- Explore the spec landscape: `/opsx:explore` (`openspec-explore`).
- Sync specs after archiving: `/opsx:sync` (`openspec-sync-specs`).
- Archive a completed change: `/opsx:archive` (`openspec-archive-change`).

Run `openspec list` / `openspec validate --all` to inspect state before making changes.

## Ops context (avoid stale assumptions)

- The **token118.com domain family and the america box (23.144.68.246) are retired** (2026-09-09). Do not target them in new changes or docs.
- The shared Logto IdP is `https://auth.finddatatech.cloud`; public services live under `*.finddatatech.cloud` on the cheap k3s cluster (runbook: `deploy/cheap-box/README.md`).
- Object storage is **RustFS** (S3-compatible). The app config still uses the `minio_*`/`MINIO_*` env names — treat "MinIO" in older docs/specs as RustFS.
- References to token118/america under `openspec/changes/archive/`, `openspec/specs/` history, and `deploy/america-box/` are immutable historical records — do not "fix" them.
- **Image pipeline (since 2026-09-30):** GitHub Actions builds `law-template` on `github.com/FindDataTechnology/law-bench` and pushes to Tencent TCR personal (`ccr.ccs.tencentyun.com/law-bench/law-template`); the cluster pulls via the `tcr-pull` secret. **Cluster nodes cannot reach github.com** — ArgoCD must keep watching the **Gitee** repo; a deploy = bump the image tag in `deploy/*.yaml` and push to Gitee (push code commits to both remotes). Jenkins→Harbor stays as the dual-track fallback.
