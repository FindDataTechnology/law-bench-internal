"use client";

import { useState } from "react";
import { Chat } from "../components/chat";
import { StatePanel } from "../components/state-panel";
import { MetricsPanel } from "../components/metrics-panel";

export type ChatResult = {
  thread_id: string;
  contract_type: string;
  draft: string;
  slots: string[];
  reviews: any[];
  synthesized_suggestions: any[];
  quiz_items: any[];
  eval_result: any;
  deepeval_scores: any;
  node_timings: Record<string, number>;
  model_calls: any[];
  errors: any[];
  total_duration: number;
};

export default function Home() {
  const [result, setResult] = useState<ChatResult | null>(null);

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b px-6 py-4">
        <h1 className="text-xl font-semibold text-gray-900">
          Contract Review Agent
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          多模型合同评审 · 3个AI评审员并行分析 · 双重评估
        </p>
      </header>

      <main className="flex h-[calc(100vh-88px)]">
        {/* Left column: Chat */}
        <div className="w-[420px] border-r bg-white flex-shrink-0 flex flex-col">
          <Chat onResult={setResult} />
        </div>

        {/* Right column: State & Metrics + Contract Preview */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <StatePanel result={result} />
          <MetricsPanel result={result} />
        </div>
      </main>
    </div>
  );
}
