"use client";

import type { ChatResult } from "../app/page";

export function MetricsPanel({ result }: { result: ChatResult | null }) {
  if (!result) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <h3 className="text-lg font-semibold mb-3">📊 运行指标</h3>
        <p className="text-sm text-gray-400 italic">等待评审流程启动...</p>
      </div>
    );
  }

  const modelCalls = result.model_calls || [];
  const totalTokens = modelCalls.reduce(
    (sum: number, call: any) => sum + (call.tokens || 0),
    0
  );
  const totalSlots = result.slots?.length || 0;
  const ev = result.eval_result || {};
  const deepeval = result.deepeval_scores || {};

  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-4">
      <h3 className="text-lg font-semibold">📊 运行指标</h3>

      {/* Basic metrics */}
      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-600">总耗时:</span>
          <span className="font-mono">{result.total_duration}s</span>
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
          <span className="text-gray-600">槽位数量:</span>
          <span className="font-mono">{totalSlots}</span>
        </div>
      </div>

      {/* Rubric eval */}
      <div className="pt-3 border-t">
        <h4 className="text-sm font-medium text-gray-700 mb-1">📋 规则评估</h4>
        <p className="text-sm">
          {ev.n_passed || 0}/{ev.n_criteria || 0} 项通过{" "}
          {ev.all_pass ? "✅ 全部通过" : "❌ 未全部通过"}
        </p>
        {ev.summary && (
          <p className="text-xs text-gray-500 mt-1">{ev.summary}</p>
        )}
      </div>

      {/* DeepEval */}
      {Object.keys(deepeval).length > 0 && (
        <div className="pt-3 border-t">
          <h4 className="text-sm font-medium text-gray-700 mb-1">📈 DeepEval 指标</h4>
          <div className="space-y-1">
            {Object.entries(deepeval).map(([k, v]: [string, any]) => (
              <div key={k} className="flex justify-between text-xs">
                <span className="text-gray-600">{k}</span>
                <span className="font-mono">
                  {v?.score !== undefined ? v.score.toFixed(2) : "?"}{" "}
                  {v?.success ? "✓" : "✗"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Contract preview */}
      {result.draft && (
        <div className="pt-3 border-t">
          <h4 className="text-sm font-medium text-gray-700 mb-1">
            📄 合同预览（{result.draft.length} 字符）
          </h4>
          <pre className="text-xs font-mono bg-gray-50 p-3 rounded max-h-60 overflow-y-auto whitespace-pre-wrap">
            {result.draft.slice(0, 1000)}
            {result.draft.length > 1000 && "\n...（截断）"}
          </pre>
        </div>
      )}
    </div>
  );
}
