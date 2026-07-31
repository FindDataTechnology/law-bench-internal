# fd-coding-law-bench-mcp

A [FastMCP](https://gofastmcp.com/) server that exposes law-bench's contract
generation, rubric evaluation, and clause RAG search as MCP tools. It **wraps
the existing `src.*` modules in place** — nothing is relocated or copied.

## Tools

| Tool | Wraps | Notes |
|------|-------|-------|
| `generate_contract_from_tags` | `src.contracts.generate_contract` / `src.clauses.assemble.generate_contract_assembled` | Renders the skeleton 母版 by default; when `stance` and/or `tags` (`stance`/`region`) are given, assembles base + tagged + custom clauses with that filter. `include_current_tags=True` attaches `current_tags` — the **live** custom-tag vocabulary (starter set + `tag_dims` rows + any dims registered in-process via `register_tag_dim`). |
| `evaluate_contract` | `src.eval.scoring.evaluate_contract` | `contract` is a file path **or** inline text. Persists the run unless `no_store=True`. Missing rubric → tool error. |
| `list_rubrics` | `src.eval.rubric.list_rubrics` | `{name, context, source}`. |
| `list_runs` | `src.eval.store.list_runs` | Recent runs, newest first. |
| `rag_search` | `src.search.query.search` | Ranked `{text, source_path, score}`; returns `[]` on any backend failure (never raises). |

### `include_current_tags` — the "current temporary custom tags"

`current_tags` is a snapshot of `src.clauses.tags.TAG_VOCAB` after
`load_vocab_from_db()`. It therefore reflects:

- the universal starter set (`stance` / `strength` / `risk` / `mandatory`),
- every dimension persisted in the `tag_dims` table, **and**
- any dimension registered in the server process via `register_tag_dim()` that
  has **not** been persisted to `tag_dims` (the temporary custom tags).

A dimension registered in another process (e.g. the web app) is invisible until
persisted — by definition, "temporary" dims are in-process only.

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

Tests are hermetic — wrapped `src.*` functions are monkeypatched, so no DB,
LLM, network, or LibreOffice is required.
