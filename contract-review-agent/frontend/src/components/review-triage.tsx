"use client";

import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { useState } from "react";
import { z } from "zod";

export function ReviewTriage() {
  const [selected, setSelected] = useState<Set<number>>(new Set());

  useHumanInTheLoop({
    name: "triage_reviews",
    description: "审查评审建议并选择要采纳的修改",
    parameters: z.object({
      suggestions: z.array(z.object({
        severity: z.string(),
        section: z.string(),
        recommendation: z.string(),
        reason: z.string(),
        sources: z.array(z.string()).optional(),
      })),
    }),
    render: ({ respond, status, args }) => {
      if (status !== "executing" || !respond) return null;

      const suggestions = args.suggestions || [];

      const handleToggle = (index: number) => {
        const newSelected = new Set(selected);
        if (newSelected.has(index)) {
          newSelected.delete(index);
        } else {
          newSelected.add(index);
        }
        setSelected(newSelected);
      };

      const handleSubmit = () => {
        const accepted = suggestions.filter((_, i) => selected.has(i));
        respond({ accepted });
        setSelected(new Set());
      };

      return (
        <div className="bg-white rounded-lg shadow p-6 max-w-2xl">
          <h3 className="text-xl font-semibold mb-4">🔍 审查评审建议</h3>
          <p className="text-sm text-gray-600 mb-4">
            请审查以下建议，选择要采纳的修改项。
          </p>

          <div className="space-y-3 mb-6">
            {suggestions.map((suggestion, i) => (
              <div
                key={i}
                className={`border rounded-lg p-4 cursor-pointer transition-colors ${
                  selected.has(i)
                    ? "border-blue-500 bg-blue-50"
                    : "border-gray-300 hover:border-gray-400"
                }`}
                onClick={() => handleToggle(i)}
              >
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={selected.has(i)}
                    onChange={() => handleToggle(i)}
                    className="mt-1"
                  />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${
                          suggestion.severity === "critical"
                            ? "bg-red-100 text-red-800"
                            : suggestion.severity === "warning"
                            ? "bg-yellow-100 text-yellow-800"
                            : "bg-gray-100 text-gray-800"
                        }`}
                      >
                        {suggestion.severity}
                      </span>
                      <span className="text-sm font-medium text-gray-700">
                        {suggestion.section}
                      </span>
                    </div>
                    <p className="text-sm text-gray-900 mb-1">
                      {suggestion.recommendation}
                    </p>
                    {suggestion.reason && (
                      <p className="text-xs text-gray-600">
                        原因: {suggestion.reason}
                      </p>
                    )}
                    {suggestion.sources && suggestion.sources.length > 0 && (
                      <p className="text-xs text-gray-500 mt-1">
                        来源: {suggestion.sources.join(", ")}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">
              已选择 {selected.size} / {suggestions.length} 项
            </span>
            <button
              onClick={handleSubmit}
              disabled={selected.size === 0}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              提交选择
            </button>
          </div>
        </div>
      );
    },
  });

  return null;
}
