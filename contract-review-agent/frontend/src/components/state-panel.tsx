"use client";

import { useAgent } from "@copilotkit/react-core/v2";

const NODE_ORDER = [
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
] as const;

export function StatePanel() {
  const { agent } = useAgent();

  // State may be undefined before the agent starts; guard everything.
  const state = (agent?.state ?? {}) as Record<string, any>;
  const timings = (state.node_timings ?? {}) as Record<string, number>;
  const currentStage = state.current_stage as string | undefined;
  const completedReviews = state.completed_reviews as number | undefined;
  const totalReviews = state.total_reviews as number | undefined;
  const isRunning = agent?.isRunning ?? false;

  return (
    <div className="bg-white rounded-lg shadow p-4">
      <h2 className="text-lg font-semibold mb-3 text-gray-800">进度面板</h2>

      {/* Progress Section */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">节点进度</h3>
        <div className="space-y-1">
          {NODE_ORDER.map((node) => {
            const nodeTimed = timings[node];
            const isCurrent = currentStage === node;
            if (!nodeTimed && !isCurrent) return null;

            const status = nodeTimed ? "completed" : "current";
            return (
              <div
                key={node}
                className={`flex items-center gap-2 px-3 py-1.5 rounded text-sm ${
                  status === "completed"
                    ? "bg-green-50"
                    : "bg-blue-50 border-l-4 border-blue-500"
                }`}
              >
                <span>
                  {status === "completed" ? "✅" : "🚦"}
                </span>
                <span className="flex-1 text-gray-700">{node}</span>
                {nodeTimed !== undefined && (
                  <span className="text-xs text-gray-500">
                    {nodeTimed.toFixed(2)}s
                  </span>
                )}
              </div>
            );
          })}
          {!currentStage && (
            <p className="text-sm text-gray-400 italic">
              等待启动...
            </p>
          )}
        </div>
      </div>

      {/* Review Panel Progress */}
      {(completedReviews !== undefined || totalReviews !== undefined) && (
        <div className="mb-4 pt-3 border-t">
          <h3 className="text-sm font-medium text-gray-700 mb-1">评审进度</h3>
          <p className="text-sm text-gray-600">
            已评审：{completedReviews ?? 0}/{totalReviews ?? 0} 个模型
          </p>
        </div>
      )}

      {/* Current Status */}
      <div className="pt-3 border-t">
        <h3 className="text-sm font-medium text-gray-700 mb-1">当前状态</h3>
        <p className="text-sm text-gray-600">
          {currentStage ? `正在执行：${currentStage}` : "等待中..."}
        </p>
        <p className="text-sm text-gray-500 mt-1">
          Agent 运行状态：{isRunning ? "工作中..." : "就绪"}
        </p>
      </div>
    </div>
  );
}
