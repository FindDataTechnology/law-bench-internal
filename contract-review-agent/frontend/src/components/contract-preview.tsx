"use client";

import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { useState } from "react";
import { z } from "zod";

export function ContractPreview() {
  const [approved, setApproved] = useState(false);

  useHumanInTheLoop({
    name: "approve_final_contract",
    description: "确认最终合同",
    parameters: z.object({
      draft: z.string(),
      eval_result: z.object({
        score: z.number().optional(),
        n_passed: z.number().optional(),
        n_criteria: z.number().optional(),
        summary: z.string().optional(),
      }).optional(),
      deepeval_scores: z.record(z.any()).optional(),
    }),
    render: ({ respond, status, args }) => {
      if (status !== "executing" || !respond) return null;

      const handleApprove = () => {
        respond({ approval: "approved" });
        setApproved(false);
      };

      const handleRequestChanges = () => {
        respond({ approval: "changes_requested" });
        setApproved(false);
      };

      const evalResult = args.eval_result || {};
      const deepevalScores = args.deepeval_scores || {};
      const nPassed = evalResult.n_passed || 0;
      const nCriteria = evalResult.n_criteria || 0;
      const passRate = nCriteria > 0 ? ((nPassed / nCriteria) * 100).toFixed(0) : 0;

      return (
        <div className="bg-white rounded-lg shadow p-6 max-w-4xl">
          <h3 className="text-xl font-semibold mb-4">📄 最终合同预览</h3>

          {/* Evaluation Summary */}
          <div className="bg-gray-50 rounded-lg p-4 mb-4">
            <h4 className="text-sm font-semibold mb-2">📊 评估结果</h4>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-600">规则评估:</span>
                <span className="ml-2 font-mono">
                  {nPassed}/{nCriteria} ({passRate}%)
                </span>
              </div>
              {evalResult.summary && (
                <div className="col-span-2 text-xs text-gray-600">
                  {evalResult.summary}
                </div>
              )}
            </div>

            {Object.keys(deepevalScores).length > 0 && (
              <div className="mt-3 pt-3 border-t">
                <h5 className="text-xs font-semibold mb-2">Deepeval 指标:</h5>
                <div className="grid grid-cols-3 gap-2 text-xs">
                  {Object.entries(deepevalScores).map(([key, value]) => (
                    <div key={key} className="flex justify-between">
                      <span className="text-gray-600">{key}:</span>
                      <span className="font-mono ml-2">
                        {typeof value === "object" && value !== null
                          ? `${((value as any).score || 0).toFixed(2)}`
                          : typeof value === "number"
                          ? value.toFixed(2)
                          : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Contract Preview */}
          <div className="border rounded-lg p-4 mb-4 max-h-96 overflow-y-auto">
            <pre className="whitespace-pre-wrap text-sm font-mono">
              {args.draft || "（合同内容为空）"}
            </pre>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleApprove}
              className="flex-1 px-6 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
            >
              ✓ 确认通过
            </button>
            <button
              onClick={handleRequestChanges}
              className="flex-1 px-6 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700"
            >
              ✎ 需要修改
            </button>
          </div>
        </div>
      );
    },
  });

  return null;
}
