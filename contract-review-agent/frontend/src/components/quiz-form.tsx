"use client";

import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import { useState } from "react";
import { z } from "zod";

export function QuizForm() {
  const [values, setValues] = useState<Record<string, string>>({});

  useHumanInTheLoop({
    name: "fill_contract_slots",
    description: "填写合同槽位信息",
    parameters: z.object({
      quiz_items: z.array(z.object({
        slot: z.string(),
        question: z.string(),
        required: z.boolean(),
        label: z.string().optional(),
        description: z.string().optional(),
        example: z.string().optional(),
      })),
      total_slots: z.number(),
    }),
    render: ({ respond, status, args }) => {
      if (status !== "executing" || !respond) return null;

      const quizItems = args.quiz_items || [];
      const allFilled = quizItems.every(
        (item) => values[item.slot]?.trim()
      );

      const handleChange = (slot: string, value: string) => {
        setValues({ ...values, [slot]: value });
      };

      const handleSubmit = () => {
        respond(values);
        setValues({});
      };

      return (
        <div className="bg-white rounded-lg shadow p-6 max-w-2xl">
          <h3 className="text-xl font-semibold mb-4">📝 填写合同信息</h3>
          <p className="text-sm text-gray-600 mb-4">
            请填写以下所有必填字段以生成最终合同。
          </p>

          <div className="space-y-4 mb-6">
            {quizItems.map((item, i) => (
              <div key={i} className="border rounded-lg p-4">
                <label className="block text-sm font-medium text-gray-900 mb-2">
                  {item.question}
                  {item.required && <span className="text-red-500 ml-1">*</span>}
                </label>
                {item.description && (
                  <p className="text-xs text-gray-600 mb-2">
                    {item.description}
                  </p>
                )}
                <input
                  type="text"
                  value={values[item.slot] || ""}
                  onChange={(e) => handleChange(item.slot, e.target.value)}
                  placeholder={item.example || `请输入${item.label || item.slot}`}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                  required={item.required}
                />
                {item.example && (
                  <p className="text-xs text-gray-500 mt-1">
                    示例: {item.example}
                  </p>
                )}
              </div>
            ))}
          </div>

          <div className="flex justify-between items-center">
            <span className="text-sm text-gray-600">
              已填写 {Object.values(values).filter(v => v?.trim()).length} / {quizItems.length} 项
            </span>
            <button
              onClick={handleSubmit}
              disabled={!allFilled}
              className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
            >
              提交所有答案
            </button>
          </div>
        </div>
      );
    },
  });

  return null;
}
