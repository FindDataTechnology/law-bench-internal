# Design: deploy-bench-public-api-pod

## Context

侦察结论（2026-11-07）：cheap 集群无 `law-bench-public`；`deploy/public/deployment.yaml` 镜像停在退役的 `harbor.local:sha-2e6de71`；`docs/public-api-deploy.md` 的 replica/MinIO 数据链未搭建。`add-bench-chain-website` 已按诚实报因态上产（https://bench.finddatatech.cloud，代理 /api/public/overview → origin 30820 预留、透传 404）。

## Decisions

### D1. 同镜像 + env 选择 app 工厂（沿 spec 既有裁决）
镜像 ccr `law-template:sha-<current>`；`PUBLIC_API=1` 让 `docker-entrypoint.sh` 选 `create_public_app()`。不做独立构建。

### D2. 数据链按 spec 补真 replica，不走「直连 origin 库」捷径
用户 2026-11-07 否决了「DSN 暂直连 origin 同库」的起步形态（B 裁决后又改 A），定：replica 数据链完整搭建。publication 覆盖 spec 点名七表；cheap 集群内新建 Postgres 实例（复用 cheap3 paper-trading-pg 的部署形态），订阅落位后对账。

### D3. 端口：新 NodePort（30620 段按集群空闲实选），不复用 30820
Caddy 侧以 `bench-api.finddatatech.cloud` 反代该端口（DNSPod 加记录 + 雷池并入 site 31 + 20 域证书再加 SAN——沿 bench 站先例全套）；同时把 bench 站的同源代理后端从 origin 30820 切到该端口。

### D4. 上线门四项 + evidence 落档
healthz / 概览真值 / sibling 401 / 429 负例，全过才算完成；样本落 `evidence/`。

### D5. spec 漂移修订随本 change 记录
`public-api-service` spec 的「origin across the border / cross-border」表述基于美国 origin 时代；origin 现居 cheap-8 与 replica 同集群。本 change 的 MODIFIED delta 在 replica 就位时修订该表述（不改变行为需求）。

## Risks / Trade-offs

- origin 主库建 publication 的写放大（新表列入发布）→ 七表都是小表，风险低。
- replica 滞后窗内 key 撤销不即时 → 验钥对账门覆盖。
- 新公开面（NodePort + 新域）→ 限流双层 + key-only 姿态继承 + fail-closed 豁免继承。

## Migration Plan

replica 先行 → secret 注入 → pod 部署 → Caddy/雷池/证书 → 上线门 → bench 站代理切换 → 真值验收解除挂账。

## Open Questions

- replica 实例落位节点（cheap3 docker vs 集群内 PVC pod）——实施时按磁盘余量实选。
