"use client";

import { useAgent } from "@copilotkit/react-core/v2";

export function StatePanel() {
  const { agent } = useAgent();

  return (
    <div className="flex-1 overflow-y-auto p-6 bg-gray-50">
      <h2 className="text-xl font-semibold mb-4 text-gray-800">进度面板</h2>

      {/* Progress Section */}
      <div className="bg-white rounded-lg shadow-sm border p-4 mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-3">节点进度</h3>
        <div className="space-y-2">
          {[
            "generate_v1",
            "review_panel",
            "synthesize",
            "human_triage",
            "generate_quiz",
            "human_quiz",
            "generate_v2",
            "evaluate",
            "human_review",
            "export",
          ].map((node) => {
            const timings = agent.state?.node_timings as Record<string, number> | undefined;
            const currentStage = agent.state?.current_stage as string | undefined;
            const nodeTimed = timings?.[node];

            if (!nodeTimed && currentStage !== node) return null;

            let status: "completed" | "current" | "pending" = "pending";
            if (nodeTimed) {
              status = "completed";
            } else if (currentStage === node) {
              status = "current";
            }

            return (
              <div
                key={node}
                className={`flex items-center gap-2 px-3 py-2 rounded ${
                  status === "completed" ? "bg-green-50" :
                  status === "current" ? "bg-blue-50 border-l-4 border-blue-500" : "bg-gray-50"
                }`}
              >
                <span>{status === "completed" ? "✅" : status === "current" ? "🚦" : "⏳"}</span>
                <span className="text-sm flex-1">{node}</span>
                {nodeTimed && <span className="text-xs text-gray-500">{nodeTimed.toFixed(2)}s</span>}
              </div>
            );
          })}
        </div>
      </div>

      {/* Review Panel Progress */}
      {(agent.state?.completed_reviews || agent.state?.total_reviews) && (
        <div className="bg-white rounded-lg shadow-sm border p-4 mb-4">
          <h3 className="text-sm font-medium text-gray-700 mb-2">评审进度</h3>
          <p className="text-sm">
            已评审：{agent.state?.completed_reviews}/(agent.state?.total_reviews}个模型
          </p>
        </div>
      )}

      {/* Current Status */}
      <div className="bg-white rounded-lg shadow-sm border p-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">当前状态</h3>
        <p className="text-sm text-gray-600">
          {agent.state?.current_stage ? `正在执行：${agent.state.current_stage}` : "等待中..."}
        </p>
        <p className="text-sm text-gray-500 mt-1">
          Agent 运行状态：{agent.isRunning ? "工作中..." : "就绪"}
        </p>
      </div>
    </div>
  );
}
