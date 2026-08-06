"use client";

import { useState } from "react";

type Message = {
  role: "user" | "assistant";
  content: string;
};

type ChatResult = {
  thread_id: string;
  contract_type: string;
  draft: string;
  slots: string[];
  reviews: any[];
  synthesized_suggestions: any[];
  eval_result: any;
  deepeval_scores: any;
  node_timings: Record<string, number>;
  model_calls: any[];
  errors: any[];
  total_duration: number;
};

export function Chat({ onResult }: { onResult: (r: ChatResult) => void }) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "你好！我可以帮你生成和审查合同。请描述你要生成的合同，例如「生成一份农产品买卖合同」。",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const send = async () => {
    if (!input.trim() || loading) return;
    const userMsg = input.trim();
    setMessages((m) => [...m, { role: "user", content: userMsg }]);
    setInput("");
    setLoading(true);
    onResult(null as any);

    try {
      const backendUrl =
        process.env.NEXT_PUBLIC_BACKEND_URL || "http://23.144.68.246:30831";
      const res = await fetch(`${backendUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMsg,
          contract_type: "sale",
          scenario: "农产品买卖",
        }),
      });
      const data: ChatResult = await res.json();
      onResult(data);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: formatResult(data),
        },
      ]);
    } catch (e: any) {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: `❌ 出错：${e.message}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`text-sm rounded-lg p-3 ${
              m.role === "user"
                ? "bg-blue-600 text-white ml-8"
                : "bg-gray-100 text-gray-800 mr-8"
            }`}
          >
            <div className="whitespace-pre-wrap">{m.content}</div>
          </div>
        ))}
        {loading && (
          <div className="text-sm text-gray-500 italic p-3">
            ⏳ 正在运行评审流程（3个模型并行评审 + 评估，约2-3分钟）...
          </div>
        )}
      </div>
      <div className="border-t p-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          placeholder="输入消息，例如：生成一份农产品买卖合同"
          disabled={loading}
          className="flex-1 px-3 py-2 border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700 disabled:bg-gray-300"
        >
          发送
        </button>
      </div>
    </div>
  );
}

function formatResult(data: ChatResult): string {
  const ev = data.eval_result || {};
  const reviews = data.reviews || [];
  const suggestions = data.synthesized_suggestions || [];
  const deepeval = data.deepeval_scores || {};
  const errors = data.errors || [];

  let out = `✅ 评审流程完成（耗时 ${data.total_duration}s）\n\n`;
  out += `📊 评估结果：${ev.n_passed || 0}/${ev.n_criteria || 0} 项通过\n`;
  if (ev.summary) out += `${ev.summary}\n`;

  if (reviews.length > 0) {
    out += `\n🔍 评审员反馈（${reviews.length}个模型）：\n`;
    reviews.forEach((r, i) => {
      const suggCount = r.suggestions?.length || 0;
      out += `  ${i + 1}. ${r.name} (${r.lens}): ${suggCount} 条建议`;
      if (r.error) out += ` [错误: ${r.error.slice(0, 50)}]`;
      out += "\n";
    });
  }

  if (suggestions.length > 0) {
    out += `\n📝 综合建议（${suggestions.length}条）：\n`;
    suggestions.slice(0, 5).forEach((s) => {
      out += `  • [${s.severity}] ${s.section}: ${s.recommendation?.slice(0, 60)}\n`;
    });
  }

  if (Object.keys(deepeval).length > 0) {
    out += `\n📈 DeepEval 指标：\n`;
    Object.entries(deepeval).forEach(([k, v]: [string, any]) => {
      if (v && typeof v === "object") {
        out += `  ${k}: ${v.score ?? "?"} ${v.success ? "✓" : "✗"}\n`;
      }
    });
  }

  if (errors.length > 0) {
    out += `\n⚠️ 警告（${errors.length}条）：\n`;
    errors.slice(0, 3).forEach((e) => {
      out += `  [${e.node}] ${e.message?.slice(0, 60)}\n`;
    });
  }

  out += `\n📄 合同已生成（${data.draft.length} 字符）。完整内容见右侧面板。`;
  return out;
}
