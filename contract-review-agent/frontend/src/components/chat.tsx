"use client";

import { CopilotSidebar } from "@copilotkit/react-core/v2";

export function Chat() {
  return (
    <CopilotSidebar
      defaultOpen={true}
      labels={{
        title: "合同评审助手",
        initial:
          "你好！我可以帮你生成和审查合同。请描述你要生成的合同类型，例如「生成一份农产品买卖合同」。",
        placeholder: "输入消息...",
      }}
    />
  );
}
