"use client";

import { CopilotKit } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { Chat } from "../components/chat";
import { StatePanel } from "../components/state-panel";
import { MetricsPanel } from "../components/metrics-panel";
import { ReviewTriage } from "../components/review-triage";
import { QuizForm } from "../components/quiz-form";
import { ContractPreview } from "../components/contract-preview";

export default function Home() {
  return (
    <CopilotKit runtimeUrl="http://localhost:8000/api/copilotkit" agent="contract-review-agent">
      <div className="min-h-screen bg-gray-50">
        <header className="bg-white border-b px-6 py-4">
          <h1 className="text-xl font-semibold text-gray-900">Contract Review Agent</h1>
          <p className="text-sm text-gray-500 mt-1">
            Multi-model contract review with human-in-the-loop checkpoints
          </p>
        </header>

        <main className="flex h-[calc(100vh-88px)]">
          {/* Left column: Chat */}
          <div className="w-96 border-r bg-white flex-shrink-0">
            <Chat />
          </div>

          {/* Right column: State & Metrics Panels */}
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <StatePanel />
            <MetricsPanel />

            {/* Human checkpoint components (render when graph hits interrupt) */}
            <ReviewTriage />
            <QuizForm />
            <ContractPreview />
          </div>
        </main>
      </div>
    </CopilotKit>
  );
}
