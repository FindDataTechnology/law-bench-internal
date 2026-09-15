// law-bench admin-assistant CopilotKit runtime.
//
// Sits entirely inside the k3s cluster: the FastAPI /copilotkit proxy (the only
// public path, admin-scope gated) forwards here. Two jobs:
//   1. chat completion via the OpenAI adapter pointed at the GLM/DeepSeek
//      OpenAI-compatible endpoint (OPENAI_BASE_URL + OPENAI_API_KEY);
//   2. MCP tool access to the dedicated law-bench-mcp-assistant instance over
//      streamable HTTP with the shared token (X-API-Key).
//
// Defense in depth: the server-side MCP instance runs with MCP_TOOL_DENYLIST
// (destructive tools never advertised), and this client filters the same names
// again in tools() in case it is ever pointed at an instance without the
// denylist.

import { createServer } from "node:http";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import {
  CopilotRuntime,
  OpenAIAdapter,
  copilotRuntimeNodeHttpEndpoint,
} from "@copilotkit/runtime";
import OpenAI from "openai";

const PORT = Number(process.env.PORT || 3111);
const ENDPOINT = process.env.COPILOT_ENDPOINT || "/copilotkit";
const MODEL = process.env.COPILOT_MODEL || "glm-4.7";
const MCP_URL =
  process.env.COPILOT_MCP_URL ||
  "http://law-bench-mcp-assistant.law-bench.svc.cluster.local/mcp";
const MCP_TOKEN = process.env.COPILOT_MCP_TOKEN || "";
// Same list as the MCP instance's MCP_TOOL_DENYLIST; names here are dropped
// from what the runtime hands the model even if the server did not filter.
const TOOL_DENYLIST = new Set(
  (
    process.env.COPILOT_TOOL_DENYLIST ||
    "clause_delete,rubric_delete,criterion_delete,prompt_delete"
  )
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
);

if (!process.env.OPENAI_API_KEY) {
  console.error("OPENAI_API_KEY is required; refusing to start");
  process.exit(1);
}
if (!MCP_TOKEN) {
  console.error("COPILOT_MCP_TOKEN is required; refusing to start");
  process.exit(1);
}

// ---------------------------------------------------------------------------
// MCP client (one cached connection per endpoint, reconnected on failure)
//
// Implements CopilotKit's MCPClient contract: { tools(): Record<name, tool>;
// close() }. Tool schemas are re-listed on demand; the underlying MCP session
// is kept alive between chat turns to avoid a connect/list/close round trip
// per request.

let mcpClient = null;
let mcpConnectPromise = null;

async function getMcpClient() {
  if (mcpClient) return mcpClient;
  if (!mcpConnectPromise) {
    mcpConnectPromise = (async () => {
      const client = new Client({ name: "lawbench-copilot-runtime", version: "0.1.0" });
      const transport = new StreamableHTTPClientTransport(MCP_URL, {
        requestInit: { headers: { "X-API-Key": MCP_TOKEN } },
      });
      await client.connect(transport);
      return client;
    })();
    try {
      mcpClient = await mcpConnectPromise;
    } catch (err) {
      console.error(`MCP connect to ${MCP_URL} failed:`, err.message);
      throw err;
    } finally {
      mcpConnectPromise = null;
    }
  }
  return mcpConnectPromise;
}

async function createLawbenchMcpClient(/* config: { endpoint, apiKey? } */) {
  // CopilotKit passes the mcpServers entry here; we deliberately ignore it and
  // use the env-pinned URL/token so the runtime cannot be redirected by
  // request data.
  const client = await getMcpClient();
  return {
    async tools() {
      let listed;
      try {
        listed = await client.listTools();
      } catch (err) {
        // Stale session (restart of the MCP pod, idle timeout) — reconnect
        // once and retry before surfacing the error to the chat.
        mcpClient = null;
        const fresh = await getMcpClient();
        listed = await fresh.listTools();
      }
      const tools = {};
      for (const t of listed.tools) {
        if (TOOL_DENYLIST.has(t.name)) continue;
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
}

// ---------------------------------------------------------------------------

const serviceAdapter = new OpenAIAdapter({
  // The openai SDK honors OPENAI_BASE_URL for the GLM/DeepSeek-compatible
  // endpoint; the adapter model must be an identifier that endpoint serves.
  openai: new OpenAI({ apiKey: process.env.OPENAI_API_KEY }),
  model: MODEL,
  keepSystemRole: true,
});

const runtime = new CopilotRuntime({
  mcpServers: [{ endpoint: MCP_URL, apiKey: MCP_TOKEN }],
  createMCPClient: createLawbenchMcpClient,
});

const copilotHandler = copilotRuntimeNodeHttpEndpoint({
  endpoint: ENDPOINT,
  runtime,
  serviceAdapter,
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
