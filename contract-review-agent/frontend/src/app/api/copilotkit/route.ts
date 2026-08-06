import { NextRequest } from "next/server";
import { CopilotRuntime, copilotRuntimeNextJSAppRouterEndpoint } from "@copilotkit/runtime";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

// LangGraphHttpAgent config field names differ between @ag-ui/langgraph
// versions; cast to any to avoid blocking the build on a type mismatch.
const agent = new LangGraphHttpAgent({
  deploymentUrl: process.env.LANGGRAPH_DEPLOYMENT_URL || "http://localhost:8000",
  graphId: "contract-review-agent",
} as any);

const serviceAdapter = new (class {
  // Minimal no-op service adapter: the LangGraph agent emits the chat events;
  // CopilotKit just needs an adapter present to satisfy the runtime shape.
})() as any;

const runtime = new CopilotRuntime({
  agents: {
    default: agent,
  },
} as any);

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    endpoint: "/api/copilotkit",
    runtime,
    serviceAdapter,
  } as any);

  return handleRequest(req);
};
