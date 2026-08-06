"use client";

import { CopilotSidebar } from "@copilotkit/react-ui/v2";

export function Chat() {
  return (
    <CopilotSidebar
      agentId="contract-review-agent"
      defaultOpen={true}
      width={450}
      labels={{
        modalHeaderTitle: "合同评审助手",
        label: "🤖 合同评审",
      }}
      customThemes={{
        mode: "light",
      }}
    />
  );
}
