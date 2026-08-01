# fd-coding-law-bench-mcp

A [FastMCP](https://gofastmcp.com/) server that exposes law-bench's contract
generation, rubric evaluation (incl. rubric/criterion/prompt management, compare
orchestration, run inspection, and law-info/legal-refs reads), and clause RAG
search as MCP tools. It **wraps the existing `src.*` modules in place** - nothing
is relocated or copied.

## Tools

The server advertises 29 tools, wrapping `src.*` in place (nothing relocated).
Tools are grouped into 7 concepts two ways: by concept-first verb names
(`<concept>_<verb>`, so any client's tool picker lists them grouped) and by a
FastMCP `tags={"<concept>"}` kwarg exposed on each tool's `meta.fastmcp.tags`.
The concepts are `contracts`, `rubrics`, `prompts`, `eval`, `search`, `law`,
`tags`. Harbor rubrics are read-only; `ManageError` (`NotFound` / `Conflict` /
`Validation` / `HarborReadOnly`) surfaces as a tool error - only `search_clauses`
degrades (to `[]`) instead of raising.

> **Breaking rename.** All tools were renamed to concept-first verb form (e.g.
> `generate_contract_from_tags` -> `contract_generate`, `rag_search` ->
> `search_clauses`). Old names no longer resolve - update callers. See the
> migration table at the end of this section.

### contracts

| Tool | Wraps | Notes |
|------|-------|-------|
| `contract_generate` | `src.contracts.generate_contract` / `src.clauses.assemble.generate_contract_assembled` | Skeleton 母版 by default; `stance`/`tags` (`stance`/`scenario`) -> assembled base + tagged + custom clauses. `include_current_tags=True` attaches `current_tags` (flat per-type vocab, see below). |
| `contract_evaluate` | `src.eval.scoring.evaluate_contract` | `contract` is a file path **or** inline text; persists unless `no_store=True`. Missing rubric -> tool error. |

### rubrics

| Tool | Wraps | Notes |
|------|-------|-------|
| `rubric_list` | `src.eval.rubric.list_rubrics` / `src.eval.rubric_crud.list_rubrics_with_counts` | `{name, context, source}`; `include_counts=True` adds `id` / `criterion_count` / `is_harbor`. |
| `rubric_get` | `src.eval.rubric_crud.get_rubric_detail` | Rubric detail + ordered criteria. |
| `rubric_create` / `rubric_update` / `rubric_delete` | `src.eval.rubric_crud.*` | Local rubrics only; writing to a harbor rubric -> tool error. |
| `criterion_add` / `criterion_update` / `criterion_delete` / `criterion_reorder` | `src.eval.rubric_crud.*` | Criterion CRUD on local rubrics; `delete` renumbers survivors. |

### prompts

| Tool | Wraps | Notes |
|------|-------|-------|
| `prompt_list` / `prompt_get` | `src.eval.prompt_crud.*` | `list` omits `content`; `get` includes it. |
| `prompt_create` / `prompt_update` / `prompt_delete` | `src.eval.prompt_crud.*` | Always editable (no harbor analog). |

### eval

| Tool | Wraps | Notes |
|------|-------|-------|
| `compare_run` | `src.eval.compare.load_prompts` + `run_compare` | Resolves prompt **names** -> drafts + judges each (drafter-only). Expensive: one LLM call per draft + one judge call per draft. |
| `compare_list` / `compare_get` | `src.eval.store.*` | Recent compares / full grouped result (no `draft_text`). |
| `compare_matrix` | `src.eval.store.get_compare` + `src.eval.compare.build_matrix` | criteria × prompts matrix in one call. |
| `run_list` | `src.eval.store.list_runs` | Recent runs (run-level fields), newest first. |
| `run_get` | `src.eval.store.get_run` | One run's fields + ordered `criteria_results`. Unknown id -> tool error. |
| `run_draft` | `src.eval.store.get_run_draft` | Lazy-fetch a run's `draft_text` (verified against the owning compare). |

### search

| Tool | Wraps | Notes |
|------|-------|-------|
| `search_clauses` | `src.search.query.search` | Ranked `{text, source_path, score}`; `[]` on any backend failure (never raises). |

### law

| Tool | Wraps | Notes |
|------|-------|-------|
| `law_types` / `law_info` | `src.eval.law_info.*` | Per-contract-type 法律法规 surveys; read-only. |
| `law_references` | `src.eval.legal_refs.extract_references` over `src.eval.law_info.all_law_info` | Aggregated, categorized, deduplicated law-reference index. |

### tags

| Tool | Wraps | Notes |
|------|-------|-------|
| `tag_vocab_list` | `src.clauses.tags.tag_vocab_for_type` | Merged flat vocab `{dim: [values]}` for a contract type (universal + type-specific); refreshes `TAG_VOCAB` from `tag_dims` first. Read-only. |
| `tag_validate` | `src.clauses.tags.validate_tags` | Dry-run: returns cleaned dict (unknown keys dropped); invalid controlled value -> tool error. Read-only. |

The `tags` group is read-only in this version. Writable tag-dim management is
not exposed - no persisted tag-dim CRUD exists in `src` yet, and
`register_tag_dim` is in-memory only (invisible to other processes, lost on
restart).

### `include_current_tags` - the "current temporary custom tags"

`current_tags` is the flat per-type vocabulary (`tag_vocab_for_type(contract_type)`)
taken after `load_vocab_from_db()`. It therefore reflects:

- the universal starter set (`stance` / `strength` / `risk` / `mandatory`),
- every dimension persisted in the `tag_dims` table, **and**
- any dimension registered in the server process via `register_tag_dim()` that
  has **not** been persisted to `tag_dims` (the temporary custom tags).

A dimension registered in another process (e.g. the web app) is invisible until
persisted - by definition, "temporary" dims are in-process only.

### Migration: old -> new tool names

| Old name | New name |
|----------|----------|
| `generate_contract_from_tags` | `contract_generate` |
| `evaluate_contract` | `contract_evaluate` |
| `list_rubrics` | `rubric_list` |
| `get_rubric` | `rubric_get` |
| `create_rubric` | `rubric_create` |
| `update_rubric` | `rubric_update` |
| `delete_rubric` | `rubric_delete` |
| `add_criterion` | `criterion_add` |
| `update_criterion` | `criterion_update` |
| `delete_criterion` | `criterion_delete` |
| `reorder_criteria` | `criterion_reorder` |
| `list_prompts` | `prompt_list` |
| `get_prompt` | `prompt_get` |
| `create_prompt` | `prompt_create` |
| `update_prompt` | `prompt_update` |
| `delete_prompt` | `prompt_delete` |
| `run_compare` | `compare_run` |
| `list_compares` | `compare_list` |
| `get_compare` | `compare_get` |
| `get_compare_matrix` | `compare_matrix` |
| `list_runs` | `run_list` |
| `get_run_detail` | `run_get` |
| `get_run_draft` | `run_draft` |
| `rag_search` | `search_clauses` |
| `list_law_info_types` | `law_types` |
| `get_law_info` | `law_info` |
| `extract_legal_references` | `law_references` |

## Requirements

This server runs in the **law-bench shared venv** (it imports `src.*`, which
needs crewai / deepeval / llama-index / psycopg / python-docx already
installed). It also reads law-bench's `.env` (`database_url`, RAG vars,
Ark/OpenRouter keys), so `.env` must be present and the relevant backends
reachable for the eval/RAG tools to do real work.

Only `fastmcp` (+ `python-dotenv`) are declared by this project; the rest are
resolved from the shared environment.

## Install (editable, into the law-bench venv)

```bash
uv pip install -e ./fd-coding-law-bench-mcp
```

## Run

```bash
python -m fd_coding_law_bench_mcp        # stdio server (default)
# or
fastmcp run fd-coding-law-bench-mcp/src/fd_coding_law_bench_mcp/server.py
```

## Wire into a client (Claude Code)

Copy the relevant entry from `mcp-config.example.json` into your project's
`.mcp.json`. Example:

```json
{
  "mcpServers": {
    "law-bench": {
      "command": "uv",
      "args": ["run", "--project", "/Users/chengsishi/law-template", "python", "-m", "fd_coding_law_bench_mcp"]
    }
  }
}
```

> The package's `__init__` puts the law-template repo root on `sys.path` so
> `import src.*` works when launched from an editable install.

## Tests

```bash
uv run pytest fd-coding-law-bench-mcp/tests
```

Tests are hermetic - wrapped `src.*` functions are monkeypatched, so no DB,
LLM, network, or LibreOffice is required. The repo-side `src.eval.store.get_run`
helper is covered by `tests/test_store.py` (real throwaway Postgres).
