"use client";

import { CopilotKit } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body style={{ margin: 0, padding: 0 }}>
        <CopilotKit
          runtimeUrl="/api/copilotkit"
          agentId="contract-review-agent"
        >
          {children}
        </CopilotKit>
      </body>
    </html>
  );
}
