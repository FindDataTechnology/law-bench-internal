"use client";

import { useAgent } from "@copilotkit/react-core/v2";

export function MetricsPanel() {
  const { agent } = useAgent({ agentId: "contract-review-agent" });

  const modelCalls = agent.state?.model_calls || [];
  const totalTokens = modelCalls.reduce((sum: number, call: any) => sum + (call.tokens || 0), 0);
  const totalCost = modelCalls.reduce((sum: number, call: any) => sum + (call.cost || 0), 0);
  const totalDuration = agent.state?.total_duration || 0;
  const totalSlots = agent.state?.slots?.length || 0;
  const humanFilled = agent.state?.human_filled_slots || 0;

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h3 className="text-lg font-semibold mb-3">📊 运行指标</h3>
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">总耗时:</span>
          <span className="font-mono">{totalDuration.toFixed(2)}s</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">模型调用次数:</span>
          <span className="font-mono">{modelCalls.length}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">总 Token 数:</span>
          <span className="font-mono">{totalTokens.toLocaleString()}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">预估成本:</span>
          <span className="font-mono">¥{totalCost.toFixed(4)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-600">槽位覆盖率:</span>
          <span className="font-mono">
            {humanFilled}/{totalSlots} ({totalSlots > 0 ? ((humanFilled / totalSlots) * 100).toFixed(0) : 0}%)
          </span>
        </div>
      </div>
    </div>
  );
}
