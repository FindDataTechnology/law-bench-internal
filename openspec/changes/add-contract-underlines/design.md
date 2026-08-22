# Design: Contract Underlines & Standard Polish

## Context

`add-contract-docx-formatting` (complete, not yet archived) gave `src/generator/generator.py` the Chinese document style: A4, 宋体 body, 黑体 headings, 2-char indent, signature-as-table. The generated DOCX is *structurally* correct but still *visually* rough. Three concrete uglinesses remain, all in `generator.py`:

```
                                   ┌─ "成品" output (highlight_slots=False) ──┐
templates/*.md ──┐                  │                                          │
clauses/assemble ─┼─▶ create_docx ─┼─▶ ① signature ____ are literal chars    │
contracts/generator┘  generator.py │  ② {{甲方名称}} shows as programmer txt │
                                     │  ③ headings have no breathing room      │
                                     └────────────────────────────────────────┘
```

The user's ask — "按照标准格式，在某些条款加上下划线，美观" — maps to:
- **下划线**: the signature `____` must become *real* Word underlines, and authors need a way to underline key clause terms (违约金比例、金额、期限).
- **标准格式/美观**: unfilled slots should read as fill-in blanks, not `{{slot}}` syntax; headings need air around them.

## The four additions (all local to `generator.py`)

### 1. `_{3,}` → real Word underline (the `____` fix)

Signature lines in `templates/*.md` are written as literal `____________________` (20+ underscore characters). A `_` is a *character*, not Word's underline format — it renders as a row of low, broken marks, not a clean continuous line, and you can't type over it cleanly.

**Approach**: in `_render_inline` (or a pre-split in `_parse_inline`), detect runs of `_{3,}` and emit them as a run of N spaces with `run.font.underline = True`. python-docx writes this as `<w:u w:val="single"/>`; N underlined spaces render as one continuous line of ~N space-widths.

```python
_BLANK_RE = re.compile(r"_{3,}")
# in _parse_inline, before the slot/bold/italic alternation:
# split text on _{3,} runs; each blank run -> {"blank": True, "width": len}
# in _render_inline: a blank segment -> paragraph.add_run(" " * width); run.underline = True
```

This is renderer-only — **no template edit**. The `_{3,}` in `templates/*.md` keeps working as-is, it just renders beautifully now. Blanks inside assembled clause body text get the same treatment for free.

Rejected alternative: tab stops with `WD_TAB_LEADER.LINES` give pixel-precise column widths (the government-document approach) but need per-paragraph tab-stop setup and don't compose with the inline-run model already used for bold/italic/slots. Spaces+underline is one run, fits the existing `_parse_inline` pipeline, and is visually equivalent for signature lines. `ponytail: spaces+underline, not tab leaders; switch to leaders if column alignment ever matters`.

### 2. `_text_` inline underline span (clause emphasis)

The renderer already parses `**bold**` and `*italic*` into styled runs. Add `_text_` → `run.font.underline = True` by the same mechanism, so authors can mark key clause terms:

```
7.1 甲方逾期支付费用的，每逾期一日应当按照逾期金额的 _万分之五_ 向乙方支付违约金。
```

```python
_INLINE_RE = re.compile(
    r"\{\{\s*[\w][\w-]*\s*\}\}"   # slot
    r"|\*\*[^*]+\*\*"            # **bold**
    r"|\*[^*]+\*"               # *italic*
    r"|_[^_]+_"                  # _underline_   ← new
)
# _parse_inline: tok[1:-1] -> {"text": ..., "underline": True}
# _apply_inline: if seg["underline"]: run.underline = True
```

**Disambiguation from `_{3,}`**: `_[^_]+_` requires non-underscore content between the markers, so a signature blank `______` (no content between) is never matched as an underline span. Chinese contract prose contains no `_` other than these two cases, so the two patterns don't collide in this domain.

### 3. Slot 示范文本 mode (`slot_style="underline"`)

The "成品" output (`highlight_slots=False`) renders unfilled slots as literal `{{甲方名称}}` text — programmer syntax, not a legal document. A standard 示范文本 shows fill-in blanks:

```
现在：  发包方（甲方）：{{甲方名称}}，住所：{{甲方联系地址}}     ← ugly syntax tokens
示范：  发包方（甲方）：──────────，住所：──────────────      ← clean fill-in blanks
```

**API**: replace the `highlight_slots: bool` toggle with a `slot_style: str` parameter:

| `slot_style` | unfilled slot renders as | `find_slots`? | use case |
|---|---|---|---|
| `"highlight"` (default) | `{{slot}}` text + yellow highlight | yes | editable template (fill in Word / `fill_slots`) |
| `"underline"` | N-space underlined blank (N from slot name width) | **no** | beautiful terminal 成品 (display / print / download) |
| `"literal"` | `{{slot}}` text, no highlight, no underline | yes | legacy `highlight_slots=False` behavior |

The two call sites (`contracts/generator.py`, `clauses/assemble.py`) currently pass `highlight_slots=False`; they switch to `slot_style="underline"` — that's the beautiful output the user wants.

**The fillability tradeoff (flagged, not blocking)**: `slot_style="underline"` emits *no* `{{slot}}` text, so `find_slots`/`fill_slots` cannot locate or fill those blanks. This is acceptable because the 成品 download is a terminal artifact, not a fillable template — the fillable path keeps `slot_style="highlight"`. If programmatic fill-after-download is ever needed, that's a content-controls/form-fields feature, out of scope here.

Migration: `highlight_slots=True` → `slot_style="highlight"`; `highlight_slots=False` → `slot_style="literal"`. `test_docs_formatting.py`'s two highlight tests move to `slot_style`. The previous change is complete-but-not-archived, so we're editing in-flight work — acceptable, the migration is mechanical.

### 4. Heading + paragraph spacing

Headings currently sit flush against the paragraphs above/below. Add `space_before`/`space_after` on the heading styles in `_set_heading`:

```python
# in _set_heading, per level:
style.paragraph_format.space_before = Pt(before)   # H1:12  H2:8  H3:6
style.paragraph_format.space_after  = Pt(after)    # H1:6   H2:4  H3:3
```

One-liner per heading level; gives the document visual hierarchy/air.

### 5. Dual-variant storage (slotted + final in one row)

The user wants both the fillable template (有槽位, `slot_style="highlight"`) and the finished document (没槽位, `slot_style="underline"`) generated together, each in its own MinIO folder. Content-addressing keys on `body_text`, which is **variant-independent** — clause assembly produces one body; only the render `slot_style` differs — so both variants live in ONE row:

```
                         one assembly  →  body_text + slots + title
                                    │
                   ┌────────────────┴────────────────┐
        slot_style="underline"               slot_style="highlight"
        (final, fill-in blanks)              (slotted, {{slot}} tokens)
                   │                                  │
        upload → artifacts/{type}/{id}.docx   upload → artifacts-slotted/{type}/{id}.docx
                   │                                  │
        docx_key / pdf_key                   docx_key_slotted / pdf_key_slotted
        └────────────────┬───────────────────────────┘
                  ONE contract_artifacts row (keyed by body_hash)
```

Two new nullable columns (`docx_key_slotted`, `pdf_key_slotted`) hold the slotted keys; `docx_key`/`pdf_key` hold the final (unchanged). `ensure_schema` adds them via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (the existing `_ADDITIVE_COLUMNS` idempotent pattern). `_object_key` picks prefix by `variant`; `generate_stored` assembles once then renders both; `download(..., variant="final"|"slotted")` reads the matching column.

**Why one row, not two:** `body_hash` is `UNIQUE` and both variants share the same `body_text`, so two rows would collide on `body_hash` (would need per-variant salt — breaks dedup semantics). One row + four nullable key columns is the minimal additive schema.

**Render cost**: dual render roughly doubles CPU per artifact. Acceptable — generation is a batch/`--force`-driven path, not a per-request hot path, and `create_docx` is fast. `ponytail: assemble once, render twice; assembly is the DB-heavy step, never repeat it per variant`.

**Default surface**: the samples/browse UI and the default download keep serving the final variant (`?variant=final` or absent — existing final URLs stay stable). The slotted variant is opt-in via `?variant=slotted`, for the fill-in-Word / template-preview use case.

## Where the code lives

Rendering additions (§1–4) are all in `src/generator/generator.py`; call-site rename in `src/contracts/generator.py` and `src/clauses/assemble.py`. Dual-variant storage (§5) touches `src/contracts/artifacts.py` (dual render + variant keys + `download` variant), `src/eval/store.py` (two columns), `src/settings.py` (new prefix). Tests in `tests/test_docs_underlines.py` (rendering) and `tests/test_contract_artifact_storage.py` (storage).

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `_{3,}` regex eats a `_text_` span or vice versa | Low | `_{3,}` requires 3+ underscores; `_[^_]+_` requires content between — mutually exclusive. Test both in the same paragraph. |
| `slot_style="underline"` output can't be `fill_slots`-filled | Medium (by design) | Documented; fillable path is `slot_style="highlight"`. Non-goal: content-controls fillability. |
| `highlight_slots` → `slot_style` rename breaks callers/tests | Low | Only 2 internal call sites + 2 tests; mechanical migration in tasks. |
| Underlined-spaces width differs from old `____` width | Low | N spaces ≈ N underscores in width; signature lines stay ~same length. Visual, not structural. |
| Container LibreOffice renders underline-on-spaces differently | Low | `w:u` is core OOXML; LibreOffice supports it. Verify in the PDF spot-check task. |

## Open decisions (flagged, not blocking)

- **Blank width**: fixed N (e.g. 16 spaces) vs. proportional to slot-name length. Recommend proportional (a 4-char slot → 8-space blank, a 6-char slot → 12-space blank) so blanks roughly cover the label they replace. Cheap to tune.
- **Tab leaders over spaces**: if column-aligned signature lines ever look ragged, switch the signature-block blanks to tab-stop + `WD_TAB_LEADER.LINES`. Not needed now.

## Acceptance Criteria

- A signature line `甲方（签字/盖章）：____________________` renders with a real Word underline (`<w:u w:val="single"/>`) on the blank run, not literal `_` characters.
- `_万分之五_` in content renders as an underlined run.
- `create_docx(body, path, slot_style="underline")` renders unfilled `{{甲方名称}}` as an underlined blank with no `{{}}` text in the output.
- `slot_style="highlight"` (default) and `slot_style="literal"` behave as the old `highlight_slots=True/False`.
- Heading styles carry non-zero `space_before`/`space_after`.
- Existing `test_docs_generator.py` + `test_docs_slots.py` pass; `test_docs_formatting.py` migrated and green.
