# Spec Delta

## MODIFIED Requirements

### Requirement: MCP Server Process

The system SHALL provide a FastMCP server project at `fd-coding-law-bench-mcp/` (importable as `fd_coding_law_bench_mcp`) that serves **知验台 (the knowledge-verification platform)**, not any single business line. Its tool face SHALL be organised by **domain** as the first dimension; legal contract drafting/evaluation SHALL be one installable pack rather than the server's organising unit.

The server SHALL expose three tool groups:

- **域面 (`domain_*` / `unit_*` / `ruler_*`)** — the platform's own model (`knowledge_units` / `domains` / `domain_proposals` / `authoring_*`), read-only.
- **资产面 (`prompt_*` / `eval_*` / `compare_*`)** — evaluation assets, carrying a `domain` dimension.
- **pack 面 (`legal_pack_*`)** — the legal line's tools (`contract_*` / `law_*` / `clause_*` / `search_clauses`), behaviour unchanged, grouping renamed.

#### Scenario: Server starts and registers its tools
- **WHEN** the server is launched with `python -m fd_coding_law_bench_mcp`
- **THEN** a FastMCP stdio server starts, and its advertised tools include at least one tool from each of the three groups

#### Scenario: Server is wired into a client config
- **WHEN** an `.mcp.json` entry points a client at `python -m fd_coding_law_bench_mcp`
- **THEN** the client can invoke each advertised tool and receive a structured response

#### Scenario: 组织维度是域不是合同类型
- **WHEN** a caller enumerates the server's organising dimension
- **THEN** the dimension is `domain`; `contract_type` survives only inside the legal pack as that pack's own concept

### Requirement: be runnable via `python -m fd_coding_law_bench_mcp` … (#1)

The server SHALL be runnable via `python -m fd_coding_law_bench_mcp` and via `fastmcp run`, SHALL communicate over stdio by default, SHALL import the existing `src.*` modules in place without relocating or copying them, and SHALL additionally import the platform's kernel modules (`src.bench.*`) which serve the domain face.

#### Scenario: split-out behaviour 1
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

### Requirement: be registered with a FastMCP `tags={"<concept>"}` … (#2)

Each advertised tool SHALL be registered with a FastMCP `tags={"<concept>"}` kwarg assigning it to exactly one concept group (see the Concept Grouping requirement). Concept groups SHALL name platform concepts (`domain`, `units`, `rulers`, `prompts`, `eval`, `metrics`) or, for pack tools, the pack they belong to (`legal`).

#### Scenario: split-out behaviour 2
- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

## ADDED Requirements

### Requirement: 法律工具降为 pack 面

The seventeen legal/contract tools that previously formed the server's main body SHALL keep their behaviour unchanged and SHALL be grouped and named as the legal pack's tools. They MUST NOT be presented as the server's general capabilities.

#### Scenario: 那十七个工具是哪些

- **WHEN** a reader asks which tools count as the legal pack
- **THEN** the list is `contract_generate`, `contract_generate_stored`, `contract_generate_batch`, `contract_download`, `contract_content`, `contract_evaluate`, `contract_type_catalog`, `type_metadata`, `law_types`, `law_info`, `law_references`, `clause_list`, `clause_get`, `clause_update`, `clause_delete`, `clause_review`, `search_clauses`

#### Scenario: 法律工具仍在，但归类不同
- **WHEN** a caller enumerates the legal line's tools
- **THEN** they are grouped under the legal pack and described as capabilities the legal pack installs, not as what the server is for

#### Scenario: 行为不变
- **WHEN** a previously documented legal tool is invoked with the same arguments
- **THEN** it returns the same shaped result as before the regrouping

### Requirement: 合同线停用不改其数据

The legal line's stored data (the `clauses` table, contract artifacts, historical eval runs) SHALL be preserved as-is. This change MUST NOT delete or migrate it, and MUST NOT merge it with the platform's knowledge units.

#### Scenario: 历史产物保留
- **WHEN** the regrouping ships
- **THEN** existing `clauses` rows, contract artifacts and historical eval runs remain queryable through the legal pack's tools