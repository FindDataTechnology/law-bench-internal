# Proposal: Contract Underlines & Standard Polish

## Why

Generated contract deliverables are structurally correct but visually rough. Three uglinesses remain in `src/generator/generator.py`, all rendering-level:

1. **填空线是假下划线** — signature lines and date/amount blanks use literal underscore characters (`____`), which render as a row of low, disconnected glyph marks, not the clean continuous line a standard legal document (示范文本) uses.
2. **关键条款无法强调** — the renderer has bold/italic inline spans but no underline span, so authors can't mark key terms (违约金比例、金额、期限) the way Chinese contract prose traditionally does.
3. **成品里槽位是程序员语法** — the "成品" output (`highlight_slots=False`) renders unfilled slots as literal `{{甲方名称}}` text — programmer syntax, not a fill-in blank a finished document shows.
4. **标题没有呼吸** — headings sit flush against surrounding paragraphs; no `space_before`/`space_after`, so the document reads as cramped.

One renderer, one file. Four small additions make every generated contract across all 66 types read as a finished 示范文本.

## What Changes

- **`_{3,}` → real Word underline.** `_render_inline` splits plain-text segments on runs of 3+ underscores; each match becomes a run of spaces (same count) with `run.font.underline = True`. No template edits — the `____` literals already in `templates/*.md` and assembled clause bodies convert at render time.
- **`_text_` inline underline span.** Extend the inline token regex (`_INLINE_RE`) with a `_[^_]+_` alternative, mirroring the existing `**bold**`/`*italic*` mechanism, so authors can underline key clause terms. Mutually exclusive with `_{3,}` (which requires no content between markers).
- **Slot 示范文本 mode via `slot_style`.** Replace the `highlight_slots: bool` toggle with `slot_style: str` taking `"highlight"` (default, yellow `{{slot}}` — fillable), `"underline"` (N-space underlined blank, no `{{}}` text — beautiful terminal 成品), and `"literal"` (legacy `highlight_slots=False`). The two call sites switch from `highlight_slots=False` to `slot_style="underline"`.
- **Heading spacing.** Add `space_before`/`space_after` on the `Heading 1/2/3` styles in `_set_heading` (H1 12/6, H2 8/4, H3 6/3 pt).
- **Dual-variant storage (slotted + final).** The user wants both the fillable template (有槽位, `slot_style="highlight"`) and the finished document (没槽位, `slot_style="underline"`) generated together, each in its own MinIO folder. `generate_stored` assembles the body once, then renders both variants; the final variant uploads under the existing `artifacts/` prefix (unchanged default), the slotted variant under a new `artifacts-slotted/` prefix. One DB row holds four nullable key columns (`docx_key`/`pdf_key` final + `docx_key_slotted`/`pdf_key_slotted` slotted), because `body_hash` is variant-independent. `download` gains a `?variant=final|slotted` param.

## Capabilities

### New Capabilities

_(none)_

### Modified Capabilities

- `document-generation`: the Markdown→DOCX renderer gains (a) a `_{3,}`→underlined-run inline mapping, (b) a `_text_` underline inline span, (c) a `slot_style` parameter replacing `highlight_slots` with three render modes, and (d) heading `space_before`/`space_after`. New scenarios assert the underline run exists, slot-name underscores are untouched, `_text_` renders underlined, `slot_style="underline"` emits blanks with no `{{}}` text, and headings carry non-zero spacing.

## Impact

- **Modified files**: `src/generator/generator.py` (all four additions — new regexes, `_parse_inline`/`_render_inline`/`_apply_inline` extensions, `slot_style` parameter, `_set_heading` spacing); `src/contracts/generator.py` and `src/clauses/assemble.py` (parameter rename `highlight_slots=False` → `slot_style="underline"`).
- **New files**: `tests/test_docs_underlines.py` (asserts underlined blank run, no literal `_`, slot-name underscore preserved, `_text_` span underlined, `slot_style` modes, heading spacing).
- **Unchanged**: the slot model (`find_slots`/`fill_slots`/`add_slot`), the signature-block table logic, the content-addressed storage layer, the MinIO corpus.
- **Dependencies**: none added (python-docx `run.font.underline` and `paragraph_format.space_before/after` are core API).
- **Data / re-generation**: body text does not change, so existing 724 artifacts are not auto-regenerated. Re-running `generate_all_stored --force` at deploy time refreshes them. Deployment follow-up, tracked in tasks.
- **Tests**: new underline test file; `test_docs_formatting.py`'s two highlight tests migrate to `slot_style`; existing `test_docs_generator.py` + `test_docs_slots.py` must still pass.
- **Migration**: `highlight_slots=True` → `slot_style="highlight"`; `highlight_slots=False` → `slot_style="literal"`. The prior `add-contract-docx-formatting` change is complete-but-not-archived, so this edits in-flight work — the migration is mechanical and fully covered in tasks.

## Non-goals

- No tab-stop + `WD_TAB_LEADER.LINES` approach — underlined spaces are simpler, work uniformly in body paragraphs and table cells, and render in both Word and LibreOffice/PDF. Tab leaders are the government-doc standard but add paragraph-level complexity for no visible gain here. `ponytail: spaces+underline; switch to leaders if column alignment ever matters`.
- No content-controls / Word form-field fillability for `slot_style="underline"` output — the 成品 download is a terminal artifact, not a fillable template; the fillable path stays `slot_style="highlight"`.
- No WYSIWYG editor or template `.docx` assets.
