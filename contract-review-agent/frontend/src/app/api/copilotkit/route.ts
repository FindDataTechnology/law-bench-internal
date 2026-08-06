import { NextRequest } from "next/server";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";
import { copilotRuntimeNextJSAppRouterEndpoint } from "@copilotkit/runtime";

// LangGraphHttpAgent config field names differ between @ag-ui/langgraph
// versions; cast to any to avoid blocking the build on a type mismatch.
const agent = new LangGraphHttpAgent({
  deploymentUrl: process.env.LANGGRAPH_DEPLOYMENT_URL || "http://localhost:8000",
  graphId: "contract-review-agent",
} as any);

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    endpoint: "/api/copilotkit",
    runtime: {
      agents: {
        default: agent,
      },
    } as any,
  });

  return handleRequest(req);
};
