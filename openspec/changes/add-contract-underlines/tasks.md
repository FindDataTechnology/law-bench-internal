# Tasks: Contract Underlines & Standard Polish

## 1. `_{3,}` → real Word underline — `src/generator/generator.py`

- [ ] 1.1 Add `_UNDERLINE_RE = re.compile(r"_{3,}")` and a `_split_underlines(text) -> list[tuple[str, bool]]` helper that splits plain text into `(chunk, is_blank)` pairs; `is_blank` segments carry the underscore count.
- [ ] 1.2 In `_render_inline`'s plain-text-segment branch, call `_split_underlines`; emit `is_blank` segments as a `run = paragraph.add_run(" " * count); run.font.underline = True` run instead of a text run.
- [ ] 1.3 Confirm slot-name underscores (`{{party_a}}`, `{{sign_date}}`) are untouched — they live in slot segments, not plain text, so `_split_underlines` never sees them.

## 2. `_text_` inline underline span

- [ ] 2.1 Add `_[^_]+_` as a final alternative in `_INLINE_RE` (after slot, `**bold**`, `*italic*`).
- [ ] 2.2 In `_parse_inline`, handle the `_text_` token: `seg = {"text": tok[1:-1], "bold": False, "italic": False, "underline": True, "slot": None}`.
- [ ] 2.3 In `_apply_inline`, add `if seg.get("underline"): run.underline = True`. Add `"underline": False` to the three existing segment constructors so the key always exists.

## 3. `slot_style` parameter (replaces `highlight_slots`)

- [ ] 3.1 Change `create_docx` signature: replace `highlight_slots: bool = True` with `slot_style: str = "highlight"`. Accept `"highlight"` / `"underline"` / `"literal"`; raise `ValueError` for unknown values.
- [ ] 3.2 Thread `slot_style` through `_render_markdown` → `_render_inline` (rename the param everywhere it's threaded). In `_render_inline`'s slot branch:
  - `"highlight"`: emit `{{slot}}` text run + yellow highlight (current behavior).
  - `"literal"`: emit `{{slot}}` text run, no highlight (current `False` behavior).
  - `"underline"`: emit an N-space underlined run (N = `_blank_width(name)`, proportional to slot-name length), no `{{}}` text.
- [ ] 3.3 Add `_blank_width(name: str) -> int` helper: `len(name) * 2` clamped to `[8, 24]` (a 4-char slot → 8-space blank, 6-char → 12, 12-char → 24). `ponytail: fixed multiplier; tune if blanks look too short/long`.
- [ ] 3.4 Migrate the two call sites: `src/contracts/generator.py` (3 calls) and `src/clauses/assemble.py:267,271,277` — `highlight_slots=False` → `slot_style="underline"`.
- [ ] 3.5 Migrate `add_slot` in `generator.py:297`: it uses the yellow highlight directly; leave it as-is (the highlight path is still the default for slot injection) — no `slot_style` needed there.

## 4. Heading + paragraph spacing

- [ ] 4.1 In `_set_heading`, add per-level `space_before`/`space_after`: H1 `Pt(12)`/`Pt(6)`, H2 `Pt(8)`/`Pt(4)`, H3 `Pt(6)`/`Pt(3)`. Drive from a `_HEADING_SPACING = {"Heading 1": (12, 6), ...}` constant.

## 5. Tests — `tests/test_docs_underlines.py` (new) + migrate `test_docs_formatting.py`

- [ ] 5.1 `_{3,}` blank: `create_docx("甲方：____________________", path)` → the blank run has `run.font.underline == True` and no `_` character in any run's text.
- [ ] 5.2 Slot-name underscore preserved: `create_docx("甲方：{{party_a}}", path)` → `find_slots(path) == ["party_a"]` and the slot text is intact (not split by `_split_underlines`).
- [ ] 5.3 `_text_` span: `create_docx("违约金 _万分之五_", path)` → the `万分之五` run is underlined; the surrounding text is not.
- [ ] 5.4 `slot_style="underline"`: `create_docx("甲方：{{甲方名称}}", path, slot_style="underline")` → no `{{` or `}}` in the document text; an underlined run exists; `find_slots` returns `[]` (no token text).
- [ ] 5.5 `slot_style="highlight"` (default): unchanged from old `highlight_slots=True` — yellow highlight present.
- [ ] 5.6 `slot_style="literal"`: `{{slot}}` text present, no highlight — matches old `highlight_slots=False`.
- [ ] 5.7 Heading spacing: `Heading 1/2/3` styles have non-zero `space_before` and `space_after`.
- [ ] 5.8 Migrate the two highlight tests in `test_docs_formatting.py` (`test_highlight_off_removes_highlight_keeps_token`, `test_highlight_on_default`) to `slot_style="literal"` / `slot_style="highlight"`.

## 6. Regression + verify

- [ ] 6.1 Run `uv run pytest tests/test_docs_generator.py tests/test_docs_slots.py tests/test_docs_formatting.py tests/test_docs_underlines.py -q` — all pass.
- [ ] 6.2 Run full suite `uv run pytest -q`; confirm no new failures beyond pre-existing generator-rules debt.
- [ ] 6.3 Spot-check: generate one assembled contract (`construction` or `sale`) as PDF, open the PDF, confirm signature lines are clean continuous underlines, key-term `_text_` spans are underlined, and unfilled slots show as blanks (not `{{}}`).

## 7. Deployment follow-up (post-merge)

- [ ] 7.1 Re-run `generate_all_stored --force` (or `PYTHONPATH=. python3 scripts/generate_all_types_stored.py --force`) against the live cluster to refresh the 724 artifacts with underlines + slot blanks + heading spacing.

## 8. Dual-variant storage (slotted + final) — `src/contracts/artifacts.py` + `src/eval/store.py` + `src/settings.py`

- [ ] 8.1 `src/settings.py`: add `MINIO_ARTIFACTS_SLOTTED_PREFIX = _env("MINIO_ARTIFACTS_SLOTTED_PREFIX", "artifacts-slotted/")` next to `MINIO_ARTIFACTS_PREFIX`.
- [ ] 8.2 `src/eval/store.py`: add `docx_key_slotted TEXT,` / `pdf_key_slotted TEXT,` to `CONTRACT_ARTIFACTS_SCHEMA`; add two `ALTER TABLE IF EXISTS contract_artifacts ADD COLUMN IF NOT EXISTS docx_key_slotted TEXT;` / `... pdf_key_slotted TEXT;` lines to `_ADDITIVE_COLUMNS` (idempotent on existing DBs).
- [ ] 8.3 `src/contracts/artifacts.py`: import `MINIO_ARTIFACTS_SLOTTED_PREFIX`; extend `_object_key(contract_type, artifact_id, ext, *, variant="final")` to pick `MINIO_ARTIFACTS_PREFIX` vs `MINIO_ARTIFACTS_SLOTTED_PREFIX`; extend `_upload(..., *, variant="final")` likewise; teach `_set_key` to write `{fmt}_key_slotted` when `variant=="slotted"`.
- [ ] 8.4 Restructure `generate_stored`: assemble ONCE (→ `body_text` + `slots` + title), then for each requested format render BOTH variants into temp paths — final via `slot_style="underline"`, slotted via `slot_style="highlight"` (+ `docx_to_pdf` when pdf/both) — and upload each under its prefix, setting `{fmt}_key` and `{fmt}_key_slotted`. Preserve content-addressed dedup: on reuse, fill whichever (format, variant) keys are missing; `force` re-uploads both. `ponytail: assembly is the DB-heavy step — assemble once, render twice; never re-assemble per variant`.
- [ ] 8.5 `download(artifact_id, format, *, variant="final", db=None)`: read `{format}_key` (final) or `{format}_key_slotted` (slotted); raise `NotFoundError` (404) if the requested variant's key is null.
- [ ] 8.6 `_download_url(artifact_id, fmt, *, variant="final")`: append `&variant=slotted` only for the slotted variant (omit for `final` so existing final URLs stay byte-for-byte stable).
- [ ] 8.7 Response shapes: `generate_stored` return dict gains `docx_url_slotted`/`pdf_url_slotted`; `generate_all_stored` per-artifact entries gain the same two fields.
- [ ] 8.8 HTTP route (`GET /api/contracts/artifacts/{id}/download`): accept `?variant=final|slotted` (default `final`); pass through to `download`. Add `variant` to the route's OpenAPI params.
- [ ] 8.9 MCP tools: `contract_download` gains a `variant` arg; `contract_generate_stored` returns `docx_url_slotted`/`pdf_url_slotted`.
- [ ] 8.10 Tests (`tests/test_contract_artifact_storage.py`): a `generate_stored` run yields a row with `docx_key` (`artifacts/...`) and `docx_key_slotted` (`artifacts-slotted/...`) both non-null; `download(..., variant="slotted")` streams the slotted docx; `download(..., variant="final")` unchanged; `download(..., variant="slotted")` on a slotted-less row → 404; same-inputs-twice → same id, `reused: true`, no re-upload.
