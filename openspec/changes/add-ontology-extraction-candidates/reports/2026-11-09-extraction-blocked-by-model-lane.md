# 抽取小样：被模型通道阻断（2026-11-09，镜像 `sha-1498eb6`）

## 结论

抽取功能已实现并上产，但**生产小样跑不通**，原因是评测所用的模型通道订阅过期：

```
POST https://ark.cn-beijing.volces.com/api/plan/v3/chat/completions
  model: openai/deepseek-v4-flash
→ 400 {"error":{"code":"InvalidSubscription",
        "message":"Your account (2100005685) does not have a valid AgentPlan
                   subscription, or your subscription has expired."}}
```

这不是抽取特有的问题：**同一个通道就是评测 judge 用的那条**。当前 `eval_runs`
行数为 0，说明「评测运行」这个区在生产上从未真正跑成过——这条通道一直是空的，
只是没人从这条路径上撞见。

## 已完成并可复核的部分

- 抽取内核 `src/bench/extraction.py`：取样（按源分页、按已订阅范围裁剪）、
  逐字证据闸、词表校验、同批端点闭合、幂等、三处硬上限、批次报告。
- 提案层与收件箱：批次筛选、整批确认/驳回，逐条走内核、部分失败不回滚。
- 测试 +21（抽取 15 / 批次复核 6），全量 1566 passed / 60 skipped。
- 模型调用可注入（`complete_fn`），换通道不需要改一行代码。

## 从 pod 内实测的可达通道

```
reachable: router.finddatatech.cloud:443          (词元 router)
reachable: token.finddatatech.cloud:443           (LLM token 网关)
reachable: sub2api.sub2api.svc.cluster.local:8080 (sub2api)
reachable: ark.cn-beijing.volces.com:443          (订阅已过期)
```

## 需要人定的一件事

1. **续订 Volcengine AgentPlan** —— 不改配置，抽取与评测一起恢复；不动判官口径。
2. **改指 `token.finddatatech.cloud`** —— 需往 `law-bench-judge` 注入该网关 key，
   并确认支持 `deepseek-v4-flash`；新增一处凭据散布，且换模型等于换判官口径。
3. **暂不接** —— 代码留着（生产能力），等评测通道修好再跑。

倾向 1：同一件事修两处，且不动判官口径。
