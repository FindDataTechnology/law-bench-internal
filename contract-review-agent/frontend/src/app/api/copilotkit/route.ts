import { NextRequest } from "next/server";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";
import { copilotRuntimeNextJSAppRouterEndpoint } from "@copilotkit/runtime";

const agent = new LangGraphHttpAgent({
  deploymentUrl: process.env.LANGGRAPH_DEPLOYMENT_URL || "http://localhost:8000",
  graphId: "contract-review-agent",
});

export const POST = async (req: NextRequest) => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    endpoint: "/api/copilotkit",
    runtime: {
      agents: {
        default: agent,
      },
    },
  });

  return handleRequest(req);
};
