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
process.exit(bad === 0 ? 0 : 1);
