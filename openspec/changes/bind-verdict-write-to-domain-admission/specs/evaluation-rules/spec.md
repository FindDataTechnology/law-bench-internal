# Spec Delta — evaluation-rules

## MODIFIED Requirements

### Requirement: be attributed to the domain that … (#7)

Scoring and run statistics SHALL be attributed to the domain that owns the rubric used.

A verdict SHALL additionally record **which layer the ruler it used belongs to**: the ruling domain's materialized path (`ruling_domain_path`) and, when the ruler is a fork, the parent rubric it derives from (`ruler_derived_from`, nullable).

These two fields SHALL be part of the verdict identity group: present means the whole group is present; their absence SHALL read as "this verdict predates the layer concept or used a ruler with no domain layer", MUST NOT read as "the layer is unknown".

Readers SHALL be able to tell a verdict judged by a platform template standard apart from one judged by a domain's own maintained standard, and MUST NOT have to infer that distinction from `ruler_digest` alone — two different layers can produce the same-looking digest, and a misattributed layer is harder to notice than a missing one.

The layer fields SHALL be validated **only on write**. Re-reading an existing verdict MUST NOT re-validate its ruler's visibility: a historical verdict is a fact, and a standard changed or retired afterwards does not invalidate it.

#### Scenario: split-out behaviour 7

- **WHEN** this behaviour is exercised
- **THEN** the requirement above holds

#### Scenario: Template and fork verdicts are distinguishable

- **WHEN** two verdicts are produced, one judged by a platform template standard and one by a fork owned by the domain
- **THEN** both carry `ruling_domain_path`, the forked one also carries `ruler_derived_from`, and a reader can tell them apart without opening the rubric

#### Scenario: Historical verdicts survive a ruler change

- **WHEN** a domain edits or retires the standard that a past verdict was judged by
- **THEN** reading that past verdict still succeeds unchanged, and no visibility re-check is performed on read
