# document-generation Delta Spec

## MODIFIED Requirements

### Requirement: DOCX Generation from Markdown Content
The system SHALL provide a `create_docx(content, output_path, *, slots=None, title=None, slot_style="highlight")` function that renders Markdown contract content into a formatted `.docx` file at `output_path` and returns the resolved path. The renderer SHALL map `#`/`##`/`###` to headings, `**bold**` and `*italic*` to styled runs, `_underline_` to underlined runs, `- `/`* ` to bullet lists, `1. ` to numbered lists, `---` to a horizontal rule, and blank-line-separated text to paragraphs. The function SHALL create parent directories that do not exist.

The renderer SHALL convert runs of 3 or more literal underscore characters (`_{3,}`) appearing in plain text into a run of an equal number of spaces with the run's underline font attribute set (`<w:u w:val="single"/>`), instead of emitting the literal underscore glyphs. This conversion SHALL NOT affect underscore characters that are part of a slot name (e.g. the `_` in `{{party_a}}`), a `_underline_` inline span, or isolated single/double underscores.

#### Scenario: Generate a DOCX from Markdown content
- **WHEN** `create_docx("# 服务协议\n\n甲方与乙方就服务事宜达成如下协议。\n\n## 第一条 服务内容\n\n- 甲方提供咨询\n- 乙方支付费用", "output/contract.docx")` is called
- **THEN** a valid `.docx` file exists at `output/contract.docx`
- **THEN** the returned path equals `output/contract.docx`
- **THEN** the document contains a Heading 1 "服务协议", a Heading 2 "第一条 服务内容", a normal paragraph for the preamble, and two bullet-list items

#### Scenario: Missing parent directory is created
- **WHEN** `create_docx("# Title", "output/nested/deep/contract.docx")` is called and `output/nested/deep/` does not exist
- **THEN** the directory is created and the `.docx` file is written successfully

#### Scenario: Optional title becomes the first heading
- **WHEN** `create_docx("正文内容", "output/c.docx", title="合同标题")` is called
- **THEN** the document's first paragraph is a Heading 1 containing "合同标题" followed by the body content

#### Scenario: Literal underscore runs render as a real Word underline
- **WHEN** `create_docx("甲方（签字/盖章）：____________________", "output/c.docx", slot_style="literal")` is called
- **THEN** the generated paragraph contains a run whose formatting carries an underline (`<w:u>`) element
- **THEN** the paragraph text contains no literal `_` underscore characters in the blank portion

#### Scenario: Slot-name underscores are not converted to blanks
- **WHEN** `create_docx("甲方：{{party_a}}", "output/c.docx", slot_style="literal")` is called
- **THEN** the generated document text contains `{{party_a}}` with the `_` preserved
- **THEN** no run in that paragraph carries an underline solely due to the slot-name underscore

#### Scenario: Inline underline span renders as an underlined run
- **WHEN** `create_docx("按照逾期金额的_万分之五_支付违约金", "output/c.docx", slot_style="literal")` is called
- **THEN** the document contains a run whose text is "万分之五" with an underline formatting attribute set
- **THEN** the literal `_` marker characters do not appear in the paragraph text

### Requirement: Slot Highlight Toggle

`create_docx` SHALL accept a `slot_style: str` parameter (default `"highlight"`) controlling how unfilled `{{slot_name}}` tokens render; this parameter supersedes and removes the previous `highlight_slots: bool` parameter (call sites migrate `highlight_slots=False` to `slot_style="underline"`).

- `slot_style="highlight"` — the token SHALL be rendered as a run containing the literal `{{slot_name}}` text with a yellow highlight (existing behavior, fillable via `fill_slots`).
- `slot_style="underline"` — the token SHALL be rendered as a run of spaces with the run's underline attribute set and NO `{{slot_name}}` text emitted; the number of spaces SHALL be derived from the slot name's character width. `find_slots` SHALL NOT discover slots in a `slot_style="underline"` document (no token text is present).
- `slot_style="literal"` — the token SHALL be rendered as the literal `{{slot_name}}` text with no highlight and no underline; `find_slots` SHALL still discover it (legacy `highlight_slots=False` behavior).

#### Scenario: Highlight mode (default) renders a yellow placeholder
- **WHEN** `create_docx("甲方：{{party_a}}", "output/c.docx")` is called (default `slot_style`)
- **THEN** the `{{party_a}}` placeholder run carries a highlight

#### Scenario: Underline mode renders a fill-in blank with no token text
- **WHEN** `create_docx("甲方：{{甲方名称}}", "output/c.docx", slot_style="underline")` is called
- **THEN** the generated document contains a run with an underline formatting attribute where the slot was
- **THEN** the document text contains no `{{` or `}}` characters
- **THEN** `find_slots("output/c.docx")` returns an empty list

#### Scenario: Literal mode renders plain token text, findable
- **WHEN** `create_docx("甲方：{{party_a}}", "output/c.docx", slot_style="literal")` is called
- **THEN** the generated document contains the text `{{party_a}}` in a run with no `w:highlight`
- **THEN** `find_slots("output/c.docx")` returns `["party_a"]`

### Requirement: Chinese Contract Document Style
`create_docx` SHALL apply a Chinese-contract document style to the document it produces: an A4 page with non-default margins, a body (`Normal`) style using a serif CJK font whose `w:eastAsia` attribute is set (not merely the Latin face), a 2-character first-line indent expressed as `w:firstLineChars="200"`, and line spacing greater than the default. The `Heading 1`/`Heading 2`/`Heading 3` styles SHALL be restyled to a black sans-serif CJK font with hierarchical sizes, `Heading 1` centered. The heading styles SHALL carry non-zero `space_before` and `space_after` paragraph spacing so headings are visually separated from surrounding body text.

#### Scenario: Generated document is A4
- **WHEN** `create_docx("正文", "out.docx")` is called
- **THEN** the document's first section has `page_width == Mm(210)` and `page_height == Mm(297)`

#### Scenario: Body font sets the CJK face
- **WHEN** `create_docx("正文", "out.docx")` is called
- **THEN** the `Normal` style's run font has an `w:rFonts` element whose `w:eastAsia` attribute is set (to the configured CJK serif font)

#### Scenario: Body paragraph uses a 2-character first-line indent
- **WHEN** `create_docx("正文", "out.docx")` is called
- **THEN** the body paragraph's `w:ind` carries `w:firstLineChars="200"`

#### Scenario: Heading 1 is a centered black CJK heading with spacing
- **WHEN** `create_docx("# 标题", "out.docx")` is called
- **THEN** the `Heading 1` paragraph's run font is black and its `w:eastAsia` is set to the configured CJK sans-serif font, and the paragraph is centered
- **THEN** the `Heading 1` style has non-zero `space_before` and non-zero `space_after`
