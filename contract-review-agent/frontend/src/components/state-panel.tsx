"use client";

import type { ChatResult } from "../app/page";

const NODE_ORDER = [
  "generate_v1",
  "review_panel",
  "synthesize",
  "generate_quiz",
  "generate_v2",
  "evaluate",
  "export",
] as const;

export function StatePanel({ result }: { result: ChatResult | null }) {
  if (!result) {
    return (
      <div className="bg-white rounded-lg shadow p-4">
        <h2 className="text-lg font-semibold mb-3 text-gray-800">进度面板</h2>
        <p className="text-sm text-gray-400 italic">
          等待启动...在左侧聊天框输入消息开始。
        </p>
      </div>
    );
  }

  const timings = result.node_timings || {};
  const reviews = result.reviews || [];
  const suggestions = result.synthesized_suggestions || [];
  const slots = result.slots || [];
  const errors = result.errors || [];

  return (
    <div className="bg-white rounded-lg shadow p-4 space-y-4">
      <h2 className="text-lg font-semibold text-gray-800">评审结果</h2>

      {/* Node timings */}
      <div>
        <h3 className="text-sm font-medium text-gray-700 mb-2">⏱ 节点耗时</h3>
        <div className="space-y-1">
          {NODE_ORDER.map((node) => {
            const t = timings[node];
            if (t === undefined) return null;
            return (
              <div
                key={node}
                className="flex items-center gap-2 px-3 py-1 rounded text-sm bg-green-50"
              >
                <span>✅</span>
                <span className="flex-1 text-gray-700">{node}</span>
                <span className="text-xs text-gray-500">{t}s</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Reviews */}
      {reviews.length > 0 && (
        <div className="pt-3 border-t">
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            🔍 评审员反馈（{reviews.length}个模型）
          </h3>
          <div className="space-y-2">
            {reviews.map((r, i) => (
              <div key={i} className="text-sm border rounded p-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-gray-800">{r.name}</span>
                  <span className="text-xs px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">
                    {r.lens}
                  </span>
                  <span className="text-xs text-gray-500">{r.model}</span>
                  {r.error && <span className="text-xs text-red-500">⚠️ 错误</span>}
                </div>
                <p className="text-xs text-gray-600">
                  {r.suggestions?.length || 0} 条建议 · {r.timing}s · {r.tokens || 0} tokens
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Suggestions */}
      {suggestions.length > 0 && (
        <div className="pt-3 border-t">
          <h3 className="text-sm font-medium text-gray-700 mb-2">
            📝 综合建议（{suggestions.length}条）
          </h3>
          <div className="space-y-1">
            {suggestions.slice(0, 8).map((s, i) => (
              <div key={i} className="text-xs border-l-2 pl-2 py-1"
                style={{
                  borderColor: s.severity === "critical" ? "#dc2626" : s.severity === "warning" ? "#f59e0b" : "#9ca3af"
                }}
              >
                <span className="font-medium">[{s.severity}]</span>{" "}
                <span className="text-gray-700">{s.section}</span>:{" "}
                {s.recommendation?.slice(0, 80)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Errors */}
      {errors.length > 0 && (
        <div className="pt-3 border-t">
          <h3 className="text-sm font-medium text-red-600 mb-2">
            ⚠️ 警告（{errors.length}条）
          </h3>
          <div className="space-y-1">
            {errors.slice(0, 5).map((e, i) => (
              <div key={i} className="text-xs text-gray-500">
                [{e.node}] {e.message?.slice(0, 80)}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
