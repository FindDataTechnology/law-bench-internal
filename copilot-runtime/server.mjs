// law-bench admin-assistant CopilotKit runtime.
//
// Sits entirely inside the k3s cluster: the FastAPI /copilotkit proxy (the only
// public path, admin-scope gated) forwards here. The node-http endpoint speaks
// CopilotKit's single-route JSON protocol (POST {method, params, body}; the
// chat method is "agent/run" streaming AG-UI events over SSE), routed to a
// registered BuiltInAgent:
//   - model via @ai-sdk/openai pointed at the GLM/DeepSeek OpenAI-compatible
//     endpoint (OPENAI_BASE_URL + OPENAI_API_KEY from the copilot-runtime
//     secret);
//   - tools from the dedicated law-bench-mcp-assistant instance over
//     streamable HTTP with the shared token (X-API-Key).
//
// Defense in depth: the server-side MCP instance runs with MCP_TOOL_DENYLIST
// (destructive tools never advertised), and this client filters the same names
// again in tools() in case it is ever pointed at an instance without the
// denylist.

import { createServer } from "node:http";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { createOpenAI } from "@ai-sdk/openai";
import { BuiltInAgent, CopilotRuntime } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";

const PORT = Number(process.env.PORT || 3111);
const ENDPOINT = process.env.COPILOT_ENDPOINT || "/copilotkit";
// LLM defaults: the shared token-vault gateway (OpenRouter-compatible API —
// sk-or keys, "vendor/model" ids, plain OpenAI chat-completions protocol).
const LLM_BASE_URL = process.env.OPENAI_BASE_URL || "https://token.finddatatech.cloud/v1";
const MODEL = process.env.COPILOT_MODEL || "deepseek/deepseek-v4.1-flash";
const MCP_URL =
  process.env.COPILOT_MCP_URL ||
  "http://law-bench-mcp-assistant.law-bench.svc.cluster.local/mcp";
const MCP_TOKEN = process.env.COPILOT_MCP_TOKEN || "";
// Same list as the MCP instance's MCP_TOOL_DENYLIST; names here are dropped
// from what the agent hands the model even if the server did not filter.
// 角色 → 可用工具组。分组取自 MCP 的 tags（0.1 取证），**不是**按工具名猜。
// 组内读写混杂的例外单独列在 ROLE_TOOL_EXCEPTIONS 里——取证实测：
// compare_run / contract_generate* / self_heal_pipeline_run /
// auto_reject_pipeline_run / tag_iteration_apply 全部落库，而 pipeline 组里
// pipeline_list/pipeline_get 只读、另两个是重写操作。
// 组名随 change domain-first-mcp 变更：法律线的 contracts/law/clauses/search
// 四组合并成 `legal`；平台自己的模型是新增的 `domain`/`units`/`rulers`。
// 旧组名保留在 READ_GROUPS 里**没有意义且危险**——工具已不挂那些 tag，
// 留着只会让「改名了但白名单还是旧的」这种错静默通过。
const READ_GROUPS = new Set([
  "domain", "units", "rulers",                                  // 平台主干
  "rubrics", "prompts", "eval", "tags", "metrics", "validations",
  "pipeline", "legal",                                          // 资产面 + 法律 pack
]);

// 写/落库类工具（annotator 不可用）。取自 0.1 的副作用表。
const WRITE_TOOLS = new Set([
  "agent_run_store",
  "compare_run",
  "contract_evaluate",
  "contract_generate", "contract_generate_batch", "contract_generate_stored",
  "run_draft",
  "self_heal_pipeline_run", "auto_reject_pipeline_run",
  "tag_iteration_apply",
  "clause_update", "clause_review",
  "prompt_create", "prompt_update",
  "rubric_create", "rubric_update",
  "criterion_add", "criterion_update", "criterion_reorder",
]);

// lead 才有的（发布/升格/重跑流水线）
const LEAD_TOOLS = new Set([
  "self_heal_pipeline_run", "auto_reject_pipeline_run", "tag_iteration_apply",
]);

const ROLE_RANK = { annotator: 0, expert: 1, lead: 2 };

const TOOL_DENYLIST = new Set(
  (
    process.env.COPILOT_TOOL_DENYLIST ||
    "clause_delete,rubric_delete,criterion_delete,prompt_delete"
  )
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
);

const ROLE_LABEL = { annotator: "只读", expert: "可写", lead: "负责人" };

/** 域片段：模型要知道「我在哪个域、我是什么角色、这个域现在该做什么」。 */
function domainPrompt(domain, role) {
  if (!domain) return "";
  const label = ROLE_LABEL[role] || role || "未知";
  return (
    `\n\n[当前上下文] 你正在「${domain}」这个域里工作，你的角色是 ${role}（${label}）。` +
    "只在本域范围内回答；用户问其它域的内容时，如实说明你只在本域工作。" +
    "如果用户要求的操作超出你的角色，说明需要谁来操作，不要假装完成。" +
    "删除类操作对任何角色都不可用，请让用户到对应页面操作。"
  );
}

// 基座不含域片段：域是**每请求**的，常量在模块加载时求值会永远拿到空域。
const BASE_PROMPT =
  "You are the law-bench workbench assistant." +
  "Use the available tools to answer questions about contracts, rubrics, " +
  "prompts, evaluations and clauses: search clauses, generate contracts, " +
  "evaluate drafts, inspect runs and law references. Deletion tools are " +
  "not available by design — if asked to delete something, explain that " +
  "deletion must be done from the regular workbench pages. Reply in the " +
  "language the user writes in (usually Chinese).";

/** 本次请求的完整指令 = 基座 + 当前域/角色。 */
function promptForCurrentRequest() {
  return BASE_PROMPT + domainPrompt(_currentScope.domain, _currentScope.role);
}

if (!process.env.OPENAI_API_KEY) {
  console.error("OPENAI_API_KEY is required; refusing to start");
  process.exit(1);
}
if (!MCP_TOKEN) {
  console.error("COPILOT_MCP_TOKEN is required; refusing to start");
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Lazy MCP client (user-managed): connects on first tools() call and
// reconnects once on a stale session. CopilotKit's BuiltInAgent accepts it
// via mcpClients and deliberately does not close user-managed clients.

let mcpClient = null;

async function getMcpClient() {
  if (mcpClient) return mcpClient;
  const client = new Client({ name: "lawbench-copilot-runtime", version: "0.1.0" });
  const transport = new StreamableHTTPClientTransport(MCP_URL, {
    requestInit: { headers: { "X-API-Key": MCP_TOKEN } },
  });
  await client.connect(transport);
  mcpClient = client;
  return client;
}

/** 这个角色能不能用这个工具。组必须可读，且写类/负责人类工具按角色收窄。 */
function allowedFor(role, toolName, groups) {
  if (TOOL_DENYLIST.has(toolName)) return false;
  const rank = ROLE_RANK[role] ?? -1;
  if (rank < 0) return false;                        // 未知角色 = 不给任何工具
  if (LEAD_TOOLS.has(toolName) && rank < ROLE_RANK.lead) return false;
  if (WRITE_TOOLS.has(toolName) && rank < ROLE_RANK.expert) return false;
  if (groups.length && !groups.some((g) => READ_GROUPS.has(g))) return false;
  return true;
}

// 当前请求的域与角色。代理已验证并注入（X-Lawbench-Domain / -Role），
// runtime 只消费、不重新判定成员资格——判定只有一处，在工作台侧。
let _currentScope = { domain: "", role: "" };
function setRequestScope(domain, role) { _currentScope = { domain, role }; }

/** 基座 prompt + 当前域/角色片段 + 代理给的事实简报（纯函数，按 scope 缓存）。 */
function promptForScope(domain, role, brief) {
  return BASE_PROMPT + domainPrompt(domain, role) + (brief ? `\n\n[本域现状] ${brief}` : "");
}

// agent 按 (domain, role) 缓存：BuiltInAgent 的 prompt 只能是字符串，而域片段
// 必须随请求变。缓存实例是让「每个作用域一份 prompt」同时成立的最轻做法。
// 简报每次都不同（下一动作会变），所以缓存键包含它——否则助手会一直复述
// 打开浮岛那一刻的旧现状。
// 缓存策略：LRU，不是「满了全清」。
//
// 原实现超过上限就 `_agents.clear()`，而键里含简报——简报随「下一动作」变化，
// 命中率极低，于是每 32 次请求就把整个缓存倒空一次，下一轮全部重建。
// 改为 LRU 后，最久未用的那一个被淘汰，热作用域（同一个人在同一域连续提问）
// 的实例留住。上限也放宽：一个实例就是一层包装对象，32 太小。
const _agents = new Map();
const _AGENT_CACHE_MAX = 128;
function agentFor(domain, role, brief) {
  // 键里用简报的长度+头尾做指纹，而不是整段中文：键更短，且 Map 比较的是字符串。
  const fingerprint = brief ? `${brief.length}:${brief.slice(0, 24)}:${brief.slice(-24)}` : "";
  const key = `${domain}\u0000${role}\u0000${fingerprint}`;
  const hit = _agents.get(key);
  if (hit) {
    // 触碰一下：Map 的插入顺序即 LRU 顺序，重插把这项移到队尾。
    _agents.delete(key);
    _agents.set(key, hit);
    return hit;
  }
  const made = new BuiltInAgent({
    model: provider.chat(MODEL),
    mcpClients: [lawbenchMcp],
    prompt: promptForScope(domain, role, brief),
    maxSteps: 10,
  });
  _agents.set(key, made);
  while (_agents.size > _AGENT_CACHE_MAX) {
    // 淘汰最久未用的一个（Map 迭代顺序 = 插入顺序）。
    const oldest = _agents.keys().next().value;
    _agents.delete(oldest);
  }
  return made;
}

const lawbenchMcp = {
  async tools() {
    let client;
    try {
      client = await getMcpClient();
    } catch (err) {
      console.error(`MCP connect to ${MCP_URL} failed:`, err.message);
      throw err;
    }
    let listed;
    try {
      listed = await client.listTools();
    } catch (err) {
      // Stale session (restart of the MCP pod, idle timeout) — drop the
      // cached client and reconnect once before surfacing the error.
      mcpClient = null;
      client = await getMcpClient();
      listed = await client.listTools();
    }
    const { role } = _currentScope;
    const tools = {};
    for (const t of listed.tools) {
      const groups = t.meta?.fastmcp?.tags || [];
      if (!allowedFor(role, t.name, groups)) continue;
      const inputSchema = t.inputSchema || {};
      tools[t.name] = {
        description: t.description,
        schema: {
          parameters: {
            properties: inputSchema.properties || {},
            required: inputSchema.required || [],
          },
        },
        execute: async (params) => {
          const result = await client.callTool({ name: t.name, arguments: params || {} });
          // Flatten MCP content blocks to text so the model sees strings.
          if (Array.isArray(result?.content)) {
            return result.content
              .map((block) =>
                block.type === "text" ? block.text : JSON.stringify(block),
              )
              .join("\n");
          }
          return result;
        },
      };
    }
    return tools;
  },
};

// ---------------------------------------------------------------------------

// LLM 上游的错误观测。AI SDK 只报 "Failed to process error response"，把真正的
// 状态码、content-type 和响应体丢掉 —— 2026-11-24 一次偶发 403 就是靠这层才定性
// 成「中间层掐断连接」而不是「请求形状有问题」（见 change
// scope-assistant-to-domain 的 tasks §8.8）。
//
// 只在非 2xx 时打一行，不碰成功路径，所以它作为长期观测留在代码里，不是一次性
// 调试代码。
const _origFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const res = await _origFetch(input, init);
  const url = typeof input === "string" ? input : (input && input.url) || "";
  if (!res.ok && url.includes("/chat/completions")) {
    let body = "";
    try {
      body = (await res.clone().text()).slice(0, 400);
    } catch (e) {
      body = `<unreadable: ${e.message}>`;
    }
    const sent = init && init.headers ? Object.keys(init.headers) : [];
    console.error(
      `[llm] ${res.status} ${url} ct=${res.headers.get("content-type")} ` +
        `sent=${JSON.stringify(sent)} body=${body}`,
    );
  }
  return res;
};

const provider = createOpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: LLM_BASE_URL,
});

// Register under both ids: "copilotkit" is the classic default the v1 React
// provider sends, "default" is a common fallback. The instances are resolved
// per request by `beforeRequestMiddleware` below — assigning into `agents`
// before each run is the documented-safe way to vary the prompt, because
// BuiltInAgent's `prompt` is a plain string with no per-run hook.
// 每轮的开始时间。request 对象本身当键即可——它在这两个中间件之间是同一个。
const _turnStartedAt = new WeakMap();

/** 调 MCP 的 assistant_usage_record 落一行。失败只记日志，不影响对话。 */
async function recordUsage({ domain, actor, role, tokens_in, tokens_out, elapsed_ms, outcome }) {
  const client = await getMcpClient();
  await client.callTool({
    name: "assistant_usage_record",
    arguments: {
      domain, actor,
      role: role || null,
      model: MODEL,
      tokens_in: tokens_in ?? null,
      tokens_out: tokens_out ?? null,
      elapsed_ms: elapsed_ms ?? null,
      outcome: outcome || "ok",
    },
  });
}

const runtime = new CopilotRuntime({
  agents: {
    copilotkit: agentFor("", "", ""),
    default: agentFor("", "", ""),
  },
  // 用量上报（2026-11-25）：助手此前完全没有计量，域成员放开后 token 从 0 变正。
  // 记在请求进入时打点，响应时调 MCP 的 assistant_usage_record 落一行。
  // 只有域与身份都在时才记——缺一个就是「不知道该记到谁名下」，那不是记录。
  //
  // **token 数是 NULL**：这个中间件只拿得到 request/response，拿不到模型用量。
  // 表允许 NULL 正是为此——「这一轮跑了但没计数」和「这一轮花了 0」是两件事。
  // 要真拿到 token 需要走 factory 模式自建 runner，那是另一个改动。
  afterRequestMiddleware: ({ request, response }) => {
    const domain = request.headers.get("x-lawbench-domain") || "";
    const actor = request.headers.get("x-lawbench-actor") || "";
    if (!domain || !actor) return response;
    const started = _turnStartedAt.get(request);
    _turnStartedAt.delete(request);
    const elapsed = started ? Date.now() - started : null;
    const outcome = response && response.ok ? "ok" : "error";
    recordUsage({ domain, actor, elapsed_ms: elapsed, outcome }).catch((err) =>
      console.error("[usage] record failed:", err.message),
    );
    return response;
  },
  beforeRequestMiddleware: ({ request }) => {
    const domain = request.headers.get("x-lawbench-domain") || "";
    const role = request.headers.get("x-lawbench-role") || "";
    _turnStartedAt.set(request, Date.now());
    let brief = "";
    const raw = request.headers.get("x-lawbench-context") || "";
    if (raw) {
      try { brief = Buffer.from(raw, "base64").toString("utf8"); } catch { brief = ""; }
    }
    setRequestScope(domain, role);
    // Bind this run's agent to the scope. Done here (not via a getter) because
    // `agents` is a plain record the runtime reads at dispatch time.
    const scoped = agentFor(domain, role, brief);
    runtime.agents.copilotkit = scoped;
    runtime.agents.default = scoped;
    return request;
  },
});

// Node listener: basePath strips /copilotkit; single-route mode serves the
// JSON envelope ({method, params, body} posted at the base) that the island's
// v1 React provider speaks (multi-route mode would 404 it with
// single_route_envelope_against_multi_route_runtime).
const copilotHandler = createCopilotNodeListener({
  runtime,
  basePath: ENDPOINT,
  mode: "single-route",
});

createServer((req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
    return;
  }
  Promise.resolve(copilotHandler(req, res)).catch((err) => {
    console.error("copilot handler error:", err);
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "text/plain" });
    }
    res.end("copilot runtime error");
  });
}).listen(PORT, () => {
  console.log(`copilot runtime listening on :${PORT}${ENDPOINT} (model ${MODEL}, mcp ${MCP_URL})`);
});
