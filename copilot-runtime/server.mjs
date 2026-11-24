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
const READ_GROUPS = new Set([
  "clauses", "rubrics", "prompts", "eval", "law", "search", "tags",
  "metrics", "validations", "contracts", "pipeline",
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

/** 基座 prompt + 当前域/角色片段（agent 实例按 scope 缓存，所以这里是纯函数）。 */
function promptForScope(domain, role) {
  return BASE_PROMPT + domainPrompt(domain, role);
}

// agent 按 (domain, role) 缓存：BuiltInAgent 的 prompt 只能是字符串，而域片段
// 必须随请求变。缓存实例是让「每个作用域一份 prompt」同时成立的最轻做法。
const _agents = new Map();
function agentFor(domain, role) {
  const key = `${domain}\u0000${role}`;
  let made = _agents.get(key);
  if (!made) {
    made = new BuiltInAgent({
      model: provider.chat(MODEL),
      mcpClients: [lawbenchMcp],
      prompt: promptForScope(domain, role),
      maxSteps: 10,
    });
    _agents.set(key, made);
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

const provider = createOpenAI({
  apiKey: process.env.OPENAI_API_KEY,
  baseURL: LLM_BASE_URL,
});

// Register under both ids: "copilotkit" is the classic default the v1 React
// provider sends, "default" is a common fallback. The instances are resolved
// per request by `beforeRequestMiddleware` below — assigning into `agents`
// before each run is the documented-safe way to vary the prompt, because
// BuiltInAgent's `prompt` is a plain string with no per-run hook.
const runtime = new CopilotRuntime({
  agents: {
    copilotkit: agentFor("", ""),
    default: agentFor("", ""),
  },
  beforeRequestMiddleware: ({ request }) => {
    const domain = request.headers.get("x-lawbench-domain") || "";
    const role = request.headers.get("x-lawbench-role") || "";
    setRequestScope(domain, role);
    // Bind this run's agent to the scope. Done here (not via a getter) because
    // `agents` is a plain record the runtime reads at dispatch time.
    const scoped = agentFor(domain, role);
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
