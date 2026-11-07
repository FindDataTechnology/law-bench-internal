# Tasks: deploy-bench-public-api-pod

## 1. 数据链

- [ ] 1.1 replica 实例就位（cheap 集群内，Postgres 14+，独立 PVC/凭据）
- [ ] 1.2 origin `CREATE PUBLICATION` 覆盖七表（clauses/contract_artifacts/rubrics/criteria/prompts/tag_dims/api_keys）
- [ ] 1.3 replica `CREATE SUBSCRIPTION` + 行数对账（api_keys 承重）+ MinIO artifacts 镜像同步 cron
- [ ] 1.4 `law-bench-public` SecretRef 注入（DSN/`AUTH_SESSION_SECRET`/China MinIO 凭据，独立于 origin）

## 2. 部署

- [ ] 2.1 `deploy/public/deployment.yaml` 现值化：ccr 镜像 tag、`PUBLIC_API=1`/`READONLY_REPLICA=1`/`RATE_LIMIT_ENABLED=1`、无 seed-db/无 PVC
- [ ] 2.2 `deploy/public/service.yaml` 新 NodePort（不复用 30820）
- [ ] 2.3 部署滚成 + healthz 200

## 3. 出口与域名

- [ ] 3.1 DNSPod 加 `bench-api` A 记录 → cheap-1
- [ ] 3.2 雷池 site 31 并入 `bench-api` 域（全字段 PUT + 逐站探活）
- [ ] 3.3 证书 20→21 域重签 → POST 更新 cert 61 → SNI 验收
- [ ] 3.4 Caddy `bench-api` block 反代新 NodePort

## 4. 上线门（evidence 落档）

- [ ] 4.1 healthz 200
- [ ] 4.2 匿名 `GET /api/public/overview` 200，载荷 digest 与分发面发布状态对账
- [ ] 4.3 匿名 sibling 401 + 限流 429 负例
- [ ] 4.4 evidence 样本落 `evidence/`（响应样本 + 负例）
- [ ] 4.5 bench 站同源代理后端切至新端口 → 站点真值验收（水合逐字段一致）
- [ ] 4.6 `openspec validate deploy-bench-public-api-pod --strict` 过绿
