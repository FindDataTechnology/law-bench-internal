# evaluation-rules Specification

## Purpose
TBD - created by archiving change chinese-contract-drafting-agents. Update Purpose after archive.
## Requirements
### Requirement: Rubric and Criterion Storage
The system SHALL store evaluation rubrics and their criteria in a SQLite database at `db/evaluation_rules.db`. Each rubric SHALL have a name, context, source, source_path, and description. Each criterion SHALL belong to exactly one rubric and SHALL have a name, description, guidance, and ordinal. The combination of rubric and criterion name SHALL be unique.

#### Scenario: Store a harbor rubric with its criteria
- **WHEN** the extraction script runs against harbor's `default-rubric.toml`
- **THEN** a `task_quality` rubric row is stored with `source = harbor:v0.20.0`, `context = check`, and `source_path` pointing at the harbor TOML file
- **AND** each of its 11 criteria is stored with name, description, and guidance

#### Scenario: Query criteria of a rubric
- **WHEN** a caller queries criteria by rubric name
- **THEN** all criteria for that rubric are returned ordered by `ordinal`

### Requirement: Harbor Provenance and Idempotent Extraction
The system SHALL extract harbor's rubrics from the installed harbor package's TOML rubric files and record their provenance (`source`, `source_path`, `context`). Re-running the extraction SHALL be idempotent: it SHALL NOT create duplicate rubrics or criteria, and SHALL NOT modify or delete rows whose `source` is not `harbor`.

#### Scenario: Re-run extraction does not duplicate
- **WHEN** the extraction script is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rows are created

#### Scenario: Local rows are preserved across re-extraction
- **WHEN** a local contract rubric exists (`source = local`) and the extraction script runs
- **THEN** the local rubric and its criteria remain unchanged

#### Scenario: Harbor not installed
- **WHEN** the harbor package cannot be located on disk
- **THEN** the extraction script fails with a clear error message indicating harbor must be installed (`uv tool install harbor`)

### Requirement: Extensibility for Local Rubrics
The schema SHALL support locally-authored rubrics distinct from harbor reference rubrics, identified by `source = local`. Local rubrics SHALL coexist with harbor rubrics in the same tables without conflict.

#### Scenario: Add a local contract rubric
- **WHEN** a local rubric is inserted with `source = local` and `context = contract`
- **THEN** it is stored alongside harbor rubrics
- **AND** it is not affected by subsequent harbor extractions

### Requirement: Per-Class Chinese Contract Rubrics
The system SHALL support an idempotently-seeded set of per-class Chinese contract rubrics - one per 民法典 typical named contract type (买卖合同, 供用电水气热力, 赠与合同, 借款合同, 保证合同, 租赁合同, 融资租赁, 保理合同, 承揽合同, 建设工程, 运输合同, 技术合同, 保管合同, 仓储合同, 委托合同, 物业服务, 行纪合同, 中介合同, 合伙合同). Each SHALL be stored with `source = local` and `context = contract`, named `contract_<type>_v1`, and SHALL consist of the shared base criteria (party identification, governing law, clause completeness, legal citation accuracy) plus 4-6 type-specific Chinese criteria drawn from that type's 民法典 mandatory-clause set. The seeding script (`scripts/seed_contract_rubrics.py`) SHALL be idempotent and SHALL NOT modify or delete any row whose `source` is not `local`.

#### Scenario: Seed the 19 per-class rubrics
- **WHEN** `seed_contract_rubrics.py` runs against a database with only the harbor rubrics and `contract_drafting_v1`
- **THEN** 19 new `contract_<type>_v1` rubrics are inserted with `source = local` and `context = contract`
- **AND** each rubric has the 4 shared base criteria plus its 4-6 type-specific criteria

#### Scenario: Re-seeding per-class rubrics is idempotent
- **WHEN** `seed_contract_rubrics.py` is run a second time
- **THEN** the rubric and criteria row counts are unchanged
- **AND** no duplicate rubric or criterion rows are created

#### Scenario: Per-class rubrics coexist with harbor rubrics
- **WHEN** the 19 per-class local rubrics exist alongside the harbor rubrics
- **THEN** both are stored in the same `rubrics`/`criteria` tables without conflict
- **AND** subsequent harbor re-extraction leaves the per-class local rubrics unchanged

### Requirement: Compare Runs Grouping Table
The system SHALL add a `compare_runs` table to `db/evaluation_rules.db`, created idempotently by `src/eval/store.py::ensure_schema` (alongside `eval_runs` and `eval_criteria_results`). Columns: `id` PK, `label`, `contract_type`, `rubric_name`, `task_desc`, `gen_mode`, `n_drafts`, `created_at`. One `compare_runs` row groups the `eval_runs` rows that belong to a single compare via the `eval_runs.compare_run_id` snapshot column.

#### Scenario: The compare_runs table is created idempotently
- **WHEN** `ensure_schema` runs on a fresh DB
- **THEN** the `compare_runs` table exists with all columns
- **AND** re-running `ensure_schema` leaves it unchanged

### Requirement: Compare-Driven Columns on eval_runs
The system SHALL add nullable, snapshotted columns to `eval_runs`: `compare_run_id` (INTEGER, soft reference to `compare_runs.id`, no FK constraint), `prompt_name` (TEXT), `prompt_type` (TEXT), `variant_label` (TEXT), and `draft_text` (TEXT). Existing standalone (non-compare) runs SHALL continue to work with these columns null. No FK constraint SHALL be introduced, so a run survives deletion of its prompt or compare (snapshot discipline).

#### Scenario: Standalone runs keep working
- **WHEN** `src/eval/run.py` stores a standalone eval run after migration
- **THEN** the run is stored with `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, and `draft_text` all null
- **AND** `--list-runs` output is unchanged

#### Scenario: A compare run records its prompt and draft
- **WHEN** a compare stores an `eval_runs` row
- **THEN** `compare_run_id`, `prompt_name`, `prompt_type`, `variant_label`, and `draft_text` are populated from the prompt and draft used
- **AND** renaming or deleting the prompt afterward does not change the stored row

### Requirement: Idempotent Additive-Column Migration
The system SHALL migrate existing databases to the new schema via a guarded `ALTER TABLE … ADD COLUMN` helper invoked from `ensure_schema`, checking `PRAGMA table_info` before each add. The migration SHALL run on every startup, SHALL be idempotent (a no-op once columns exist), and SHALL NOT touch any existing row's data (new columns default to null).

#### Scenario: An existing DB is migrated on startup
- **WHEN** `ensure_schema` runs against a DB that predates this change
- **THEN** `prompt_type` is added to `prompts`, `compare_runs` is created, and the five new columns are added to `eval_runs`
- **AND** existing `eval_runs` and `prompts` rows have null/blank new columns

#### Scenario: Migration is idempotent
- **WHEN** `ensure_schema` runs a second time
- **THEN** no `ALTER TABLE` is attempted for columns that already exist
- **AND** no error is raised

