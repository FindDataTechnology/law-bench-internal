// 角色过滤表自检（node copilot-runtime/test/role-filter.test.mjs）。
//
// 判据必须与 0.1 的副作用表一致：annotator 拿不到任何写类工具，expert 拿不到
// 重跑流水线，lead 也拿不到删除。这层逻辑在 CopilotKit 里，本地没有 node_modules
// 跑不起来，所以把判定单独抄成纯函数比照——它对应 server.mjs 里的 allowedFor。
// 不依赖 CopilotKit（那要 node_modules），只把过滤逻辑抄一份对照。
const READ_GROUPS = new Set(["clauses","rubrics","prompts","eval","law","search","tags","metrics","validations","contracts","pipeline"]);
const WRITE_TOOLS = new Set(["agent_run_store","compare_run","contract_evaluate","contract_generate","contract_generate_batch","contract_generate_stored","run_draft","self_heal_pipeline_run","auto_reject_pipeline_run","tag_iteration_apply","clause_update","clause_review","prompt_create","prompt_update","rubric_create","rubric_update","criterion_add","criterion_update","criterion_reorder"]);
const LEAD_TOOLS = new Set(["self_heal_pipeline_run","auto_reject_pipeline_run","tag_iteration_apply"]);
const DENY = new Set(["clause_delete","rubric_delete","criterion_delete","prompt_delete"]);
const RANK = { annotator:0, expert:1, lead:2 };
function allowed(role, name, groups) {
  if (DENY.has(name)) return false;
  const r = RANK[role] ?? -1; if (r < 0) return false;
  if (LEAD_TOOLS.has(name) && r < RANK.lead) return false;
  if (WRITE_TOOLS.has(name) && r < RANK.expert) return false;
  if (groups.length && !groups.some(g => READ_GROUPS.has(g))) return false;
  return true;
}
const cases = [
  ["annotator","clause_list",["clauses"],true],
  ["annotator","clause_update",["clauses"],false],
  ["annotator","clause_delete",["clauses"],false],
  ["expert","clause_update",["clauses"],true],
  ["expert","self_heal_pipeline_run",["pipeline"],false],
  ["lead","self_heal_pipeline_run",["pipeline"],true],
  ["lead","clause_delete",["clauses"],false],
  ["annotator","pipeline_list",["pipeline"],true],
  ["expert","contract_generate",["contracts"],true],
  ["annotator","contract_generate",["contracts"],false],
  ["","clause_list",["clauses"],false],
];
let bad = 0;
for (const [role,name,groups,want] of cases) {
  const got = allowed(role,name,groups);
  if (got !== want) { console.log(`FAIL ${role}/${name}: want ${want} got ${got}`); bad++; }
}
console.log(bad === 0 ? `ok ${cases.length} cases` : `${bad} failures`);

// ---------------------------------------------------------------------------
// 提示词契约（tasks 3.5 的后半）：助手必须被明确告知「超角色要说明、删除不可用、
// 只在本域工作」，且域简报是独立可省略的一段。
//
// 只在源码上断言，不启动服务：提示词是 agent 实例构造时拼进去的字符串，跑起来
// 也看不到最终形态；而这几句是产品约束，丢了就是「助手越权说话」。
// ---------------------------------------------------------------------------
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "server.mjs"), "utf8");

const promptChecks = [
  ["域名/角色片段由函数生成", /function domainPrompt\(/],
  ["声明只在本域工作", /只在本域范围内回答/],
  ["声明删除对所有角色不可用", /删除类操作对任何角色都不可用/],
  ["声明超角色要说清谁来操作", /超出你的角色/],
  ["本域现状是独立一段", /\[本域现状\]/],
  ["简报为空时不注入", /brief \? `\\n\\n\[本域现状\]/],
];

let promptBad = 0;
for (const [name, re] of promptChecks) {
  if (!re.test(src)) {
    console.log(`FAIL prompt: ${name}`);
    promptBad++;
  }
}
if (promptBad) {
  console.log(`${promptBad} prompt assertion(s) failed`);
  process.exit(1);
}
console.log(`ok ${promptChecks.length} prompt checks`);

if (bad + promptBad > 0) process.exit(1);
console.log(`ok ${cases.length} role cases, ${promptChecks.length} prompt checks`);


// ---------------------------------------------------------------------------
// 组名迁移（change domain-first-mcp）：法律四组并成 legal，平台新增
// domain/units/rulers。旧组名若还留在白名单里，工具已经不再挂那些 tag，
// 白名单就成了「看起来在收窄、实际什么都没过滤」的假闸。
// ---------------------------------------------------------------------------
const STALE_GROUPS = ["contracts", "law", "clauses", "search"];
const staleFound = STALE_GROUPS.filter((g) =>
  new RegExp(`"${g}"\\s*,`).test(src.slice(src.indexOf("const READ_GROUPS"), src.indexOf("const WRITE_TOOLS")))
);
if (staleFound.length) {
  console.log(`FAIL: 旧组名仍在 READ_GROUPS 里：${staleFound.join(", ")}`);
  promptBad++;
}

const REQUIRED_GROUPS = ["domain", "units", "rulers", "legal"];
const missingGroups = REQUIRED_GROUPS.filter((g) => !src.includes(`"${g}"`));
if (missingGroups.length) {
  console.log(`FAIL: 新组名缺失：${missingGroups.join(", ")}`);
  promptBad++;
}
