#!/usr/bin/env python3
"""Dataset exporter: bronze guard, tier filtering, schema/rule validation, flywheel gate.

Reads warehouse material from ``data/finetune/warehouse/<table>.jsonl`` (produced
by ``extract_warehouse.py``) and builds the two training datasets:

- **Judge-C quadruples** — from ``eval_criteria_results`` (bronze, machine
  self-eval) and an optional human-annotation file (gold). Machine pass is
  forced to fail (spec scenario 机器自评不产生 pass).
- **Drafter-A pairs** — from ``pipeline_runs`` (silver, 548 warmup) and an
  optional human-verified file (gold). Slot consistency is checked.

Cross-field rules JSON Schema cannot express are enforced here:
- ``verdict=pass`` only when ``provenance.reviewer=human`` (machine → fail).
- ``reasoning.citation`` non-empty.
- bronze material never enters a ground-truth / reward-positive set
  (single-point guard in ``common.assert_not_ground_truth``).
- silver pairs never enter a reward-positive set (same guard, purpose=reward).

Subcommands::

    python scripts/finetune/export_dataset.py judge-c  [--gold PATH]
    python scripts/finetune/export_dataset.py drafter-a [--gold PATH]
    python scripts/finetune/export_dataset.py validate {judge-c|drafter-a} --file PATH
    python scripts/finetune/export_dataset.py gate

``gate`` enforces the flywheel order: Drafter reward/DPO may only start when
the Judge-C gold quadruple dataset exists and is non-empty (spec: 飞轮顺序约束).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from common import (  # noqa: E402
    BronzeGroundTruthError,
    DRAFTER_A_DIR,
    JUDGE_C_DIR,
    WAREHOUSE_DIR,
    assert_not_ground_truth,
    filter_by_tier,
    read_jsonl,
    write_jsonl,
)

QUADRUPLE_SCHEMA = JUDGE_C_DIR / "quadruple.schema.json"
PAIR_SCHEMA = DRAFTER_A_DIR / "pair.schema.json"
JUDGE_C_GOLD = JUDGE_C_DIR / "judge_c_gold.jsonl"
JUDGE_C_BRONZE = JUDGE_C_DIR / "judge_c_bronze.jsonl"
DRAFTER_A_SILVER = DRAFTER_A_DIR / "drafter_a_silver.jsonl"
DRAFTER_A_GOLD = DRAFTER_A_DIR / "drafter_a_gold.jsonl"

# Matches {{slot_name}} placeholders left in a filled body.
_SLOT_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


# ---------------------------------------------------------------------------
# warehouse material loading
# ---------------------------------------------------------------------------

def _load_warehouse_table(table: str) -> list[dict]:
    """Load material records for one warehouse table (flat JSONL, not nested)."""
    return read_jsonl(WAREHOUSE_DIR / f"{table}.jsonl")


def _index_by_id(records: list[dict]) -> dict:
    """Index material records by their ``row_id``."""
    return {r["row_id"]: r for r in records}


def _index_criteria_by_name(records: list[dict]) -> dict:
    """Index criteria material by ``row.name``.

    ``eval_criteria_results.criterion_id`` is TEXT and holds the criterion
    *name* (e.g. 'party_identification'), not the criteria.id bigint. So the
    Judge-C join is on name, not id.
    """
    return {r["row"].get("name"): r for r in records}


# ---------------------------------------------------------------------------
# Judge-C quadruple construction
# ---------------------------------------------------------------------------

def _build_bronze_quadruples() -> list[dict]:
    """Build bronze quadruples from eval_criteria_results (machine self-eval).

    Machine verdict=pass is forced to fail (spec: 机器自评不产生 pass). The
    legal_base comes from the matching criterion's guidance (the human rule).
    """
    eval_results = _load_warehouse_table("eval_criteria_results")
    criteria_by_name = _index_criteria_by_name(_load_warehouse_table("criteria"))
    rubrics_by_id = _index_by_id(_load_warehouse_table("rubrics"))

    quadruples: list[dict] = []
    for er in eval_results:
        row = er["row"]
        # Join on criterion NAME (criterion_id is text, not a bigint id).
        crit = criteria_by_name.get(row.get("criterion_id"))
        if crit is None:
            continue
        crit_row = crit["row"]
        rubric = rubrics_by_id.get(crit_row.get("rubric_id"))
        rubric_context = rubric["row"].get("context", "") if rubric else ""

        machine_verdict = row.get("verdict", "fail")
        # Force machine pass → fail (spec scenario).
        verdict = "fail" if machine_verdict == "pass" else "fail"

        citation = []
        if rubric:
            citation.append(f"rubric:{rubric['row'].get('name')}")
        if crit_row.get("name"):
            citation.append(f"criterion:{crit_row.get('name')}")

        reasoning_text = row.get("reasoning") or crit_row.get("guidance") or ""
        if not reasoning_text:
            reasoning_text = "机器自评未提供理由；降级为 fail。"

        quadruples.append({
            "legal_base": {
                "source": f"rubric:{rubric['row'].get('name')}" if rubric else f"criterion:{crit_row.get('name')}",
                "text": (rubric_context + "\n" + crit_row.get("guidance", "")).strip() or crit_row.get("description", ""),
            },
            "clause_text": {
                "body": row.get("title") or crit_row.get("name") or "",
                "section": f"criterion:{row.get('criterion_id')}",
            },
            "verdict": verdict,
            "reasoning": {
                "justification": reasoning_text,
                "citation": citation or ["machine_self_eval:no_citation"],
            },
            "provenance": {
                "reviewer": "machine_self_eval",
                "annotated_by": "machine_self_eval",
                "id": f"eval_criteria_results:{row.get('id')}",
            },
            "tier": "bronze",
        })
    return quadruples


def _load_gold_quadruples(gold_path: pathlib.Path | None) -> list[dict]:
    """Load human-annotated gold quadruples from an optional file."""
    path = gold_path or JUDGE_C_GOLD
    return read_jsonl(path)


def export_judge_c(gold_path: pathlib.Path | None = None) -> dict:
    """Export Judge-C bronze + gold quadruple datasets."""
    bronze = _build_bronze_quadruples()
    write_jsonl(JUDGE_C_BRONZE, bronze)

    gold = _load_gold_quadruples(gold_path)
    if gold:
        write_jsonl(JUDGE_C_GOLD, gold)

    return {
        "bronze": len(bronze),
        "gold": len(gold),
        "bronze_path": str(JUDGE_C_BRONZE),
        "gold_path": str(JUDGE_C_GOLD),
    }


# ---------------------------------------------------------------------------
# Drafter-A pair construction
# ---------------------------------------------------------------------------

def _fill_values_to_slots(fill_values) -> list[dict]:
    """Convert a pipeline_runs.fill_values jsonb dict to schema-compliant slots[]."""
    if not isinstance(fill_values, dict):
        return []
    return [{"name": str(k), "value": str(v) if v is not None else ""} for k, v in fill_values.items()]


def _check_slot_consistency(body: str, slots: list[dict]) -> tuple[bool, list[str]]:
    """Return (ok, leftover_placeholders). Body must have no unreplaced {{slot}}."""
    leftover = _SLOT_RE.findall(body or "")
    return (len(leftover) == 0, leftover)


def _build_silver_pairs() -> list[dict]:
    """Build silver Drafter-A pairs from pipeline_runs.filled_text."""
    runs = _load_warehouse_table("pipeline_runs")
    pairs: list[dict] = []
    for run in runs:
        row = run["row"]
        body = row.get("filled_text")
        if not body:
            continue  # spec: cover non-null filled_text only
        slots = _fill_values_to_slots(row.get("fill_values"))
        pairs.append({
            "task_desc": row.get("task_desc") or "",
            "slots": slots,
            "body": body,
            "provenance": {
                "annotated_by": "machine_generated",
                "id": f"pipeline_runs:{row.get('id')}",
            },
            "tier": "silver",
        })
    return pairs


def _load_gold_pairs(gold_path: pathlib.Path | None) -> list[dict]:
    path = gold_path or DRAFTER_A_GOLD
    return read_jsonl(path)


def export_drafter_a(gold_path: pathlib.Path | None = None) -> dict:
    """Export Drafter-A silver + gold pair datasets."""
    silver = _build_silver_pairs()
    write_jsonl(DRAFTER_A_SILVER, silver)

    gold = _load_gold_pairs(gold_path)
    if gold:
        write_jsonl(DRAFTER_A_GOLD, gold)

    return {
        "silver": len(silver),
        "gold": len(gold),
        "silver_path": str(DRAFTER_A_SILVER),
        "gold_path": str(DRAFTER_A_GOLD),
    }


# ---------------------------------------------------------------------------
# validation (schema + cross-field rules)
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    pass


def _require(obj: dict, field: str, ctx: str) -> None:
    if field not in obj or obj[field] is None:
        raise ValidationError(f"{ctx}: 缺少必填字段 {field!r}")


def validate_quadruple(q: dict, index: int) -> None:
    """Validate one Judge-C quadruple against schema + annotation rules."""
    ctx = f"quadruple#{index}"
    _require(q, "legal_base", ctx)
    _require(q, "clause_text", ctx)
    _require(q, "verdict", ctx)
    _require(q, "reasoning", ctx)
    _require(q, "provenance", ctx)
    _require(q, "tier", ctx)

    lb = q["legal_base"]
    _require(lb, "source", ctx)
    _require(lb, "text", ctx)
    if not lb["source"] or not lb["text"]:
        raise ValidationError(f"{ctx}: 推理理由缺少法律依据 (legal_base 空)")

    ct = q["clause_text"]
    _require(ct, "body", ctx)
    if not ct["body"]:
        raise ValidationError(f"{ctx}: clause_text.body 为空")

    if q["verdict"] not in ("pass", "fail"):
        raise ValidationError(f"{ctx}: verdict 非 pass/fail")

    rs = q["reasoning"]
    _require(rs, "justification", ctx)
    _require(rs, "citation", ctx)
    if not rs["citation"]:
        raise ValidationError(f"{ctx}: 推理理由缺少法律依据 (citation 空)")

    prov = q["provenance"]
    _require(prov, "reviewer", ctx)
    _require(prov, "annotated_by", ctx)
    if prov["reviewer"] not in ("human", "machine_self_eval"):
        raise ValidationError(f"{ctx}: reviewer 非 human/machine_self_eval")

    # Cross-field rule: verdict=pass only when reviewer=human.
    if q["verdict"] == "pass" and prov["reviewer"] != "human":
        raise ValidationError(
            f"{ctx}: 机器自评不得判 pass (reviewer={prov['reviewer']})"
        )

    if q["tier"] not in ("gold", "bronze"):
        raise ValidationError(f"{ctx}: tier 非 gold/bronze")
    # tier=gold requires human reviewer.
    if q["tier"] == "gold" and prov["reviewer"] != "human":
        raise ValidationError(f"{ctx}: tier=gold 须 reviewer=human")
    # NOTE: the bronze "never ground truth" guard is NOT invoked here —
    # validating a bronze record is not the same as *using* it as ground
    # truth. The guard lives in common.filter_by_tier / assert_not_ground_truth
    # and is tripped by loaders that assemble ground-truth sets.


def validate_pair(p: dict, index: int) -> None:
    """Validate one Drafter-A pair against schema + slot-consistency rule."""
    ctx = f"pair#{index}"
    _require(p, "task_desc", ctx)
    _require(p, "slots", ctx)
    _require(p, "body", ctx)
    _require(p, "provenance", ctx)
    _require(p, "tier", ctx)

    if not p["task_desc"]:
        raise ValidationError(f"{ctx}: task_desc 为空")
    if not isinstance(p["slots"], list):
        raise ValidationError(f"{ctx}: slots 非数组")
    # minItems:0 — zero-slot pairs are valid iff body has no placeholders.
    for s in p["slots"]:
        _require(s, "name", ctx)
        _require(s, "value", ctx)
    if not p["body"]:
        raise ValidationError(f"{ctx}: body 为空")

    ok, leftover = _check_slot_consistency(p["body"], p["slots"])
    if not ok:
        raise ValidationError(f"{ctx}: 正文含未替换占位符 {leftover}")

    prov = p["provenance"]
    _require(prov, "annotated_by", ctx)
    if p["tier"] not in ("gold", "silver"):
        raise ValidationError(f"{ctx}: tier 非 gold/silver")
    if p["tier"] == "gold" and prov.get("annotated_by") != "human":
        raise ValidationError(f"{ctx}: tier=gold 须 annotated_by=human")
    # NOTE: the silver "never reward positive" guard is NOT invoked here —
    # validating a silver pair is not *using* it as a reward sample. The
    # guard lives in common.filter_by_tier / assert_not_ground_truth.


def validate_file(path: pathlib.Path, kind: str) -> int:
    """Validate every record in a dataset file. Returns count of valid records."""
    records = read_jsonl(path)
    validator = validate_quadruple if kind == "judge-c" else validate_pair
    valid = 0
    errors: list[str] = []
    for i, rec in enumerate(records):
        try:
            validator(rec, i)
            valid += 1
        except (ValidationError, BronzeGroundTruthError) as e:
            errors.append(str(e))
    print(f"  {path}: {valid}/{len(records)} valid")
    for e in errors[:10]:
        print(f"    - {e}")
    if len(errors) > 10:
        print(f"    ... ({len(errors) - 10} more)")
    return valid


# ---------------------------------------------------------------------------
# flywheel order gate (D4)
# ---------------------------------------------------------------------------

def flywheel_gate() -> bool:
    """Return True if Judge-C gold quadruple dataset exists and is non-empty."""
    if not JUDGE_C_GOLD.exists():
        print(f"❌ 飞轮闸门未通过: Judge-C gold 数据集不存在 ({JUDGE_C_GOLD})")
        print("   先运行: python scripts/finetune/export_dataset.py judge-c --gold <human_gold.jsonl>")
        return False
    records = read_jsonl(JUDGE_C_GOLD)
    if not records:
        print(f"❌ 飞轮闸门未通过: Judge-C gold 数据集为空 ({JUDGE_C_GOLD})")
        return False
    print(f"✅ 飞轮闸门通过: Judge-C gold 有 {len(records)} 条四元组")
    return True


# ---------------------------------------------------------------------------
# reward-positive loader (§6.4 / §7.2 — silver must never be a reward positive)
# ---------------------------------------------------------------------------

def load_drafter_reward_positive() -> list[dict]:
    """Load Drafter-A pairs eligible as reward-positive samples.

    Gold only. Silver pairs are SFT-warmup-only and MUST NOT enter this set
    (spec §6.4, design D2). The silver exclusion is enforced two ways:
    (1) ``filter_by_tier(floor='gold')`` drops silver by rank, and
    (2) ``assert_not_ground_truth('silver', purpose='reward_positive')`` is
    an explicit trip-wire on any silver record that slipped past the filter.
    """
    pairs = read_jsonl(DRAFTER_A_GOLD) + read_jsonl(DRAFTER_A_SILVER)
    gold = filter_by_tier(pairs, "gold")
    # Belt-and-suspenders: if any silver record reached the gold set, fail loud.
    for p in gold:
        if p.get("tier") == "silver":
            assert_not_ground_truth("silver", purpose="drafter_a_reward_positive")
    return gold


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export & validate finetune datasets.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_jc = sub.add_parser("judge-c", help="export Judge-C quadruples")
    p_jc.add_argument("--gold", type=pathlib.Path, help="human gold quadruple file")

    p_da = sub.add_parser("drafter-a", help="export Drafter-A pairs")
    p_da.add_argument("--gold", type=pathlib.Path, help="human gold pair file")

    p_val = sub.add_parser("validate", help="validate a dataset file")
    p_val.add_argument("kind", choices=["judge-c", "drafter-a"])
    p_val.add_argument("--file", type=pathlib.Path, required=True)

    sub.add_parser("gate", help="check flywheel order gate (Judge-C gold ready?)")

    args = parser.parse_args(argv)

    if args.cmd == "judge-c":
        stats = export_judge_c(getattr(args, "gold", None))
        print(f"Judge-C: bronze={stats['bronze']} -> {stats['bronze_path']}")
        print(f"         gold={stats['gold']} -> {stats['gold_path']}")
        return 0

    if args.cmd == "drafter-a":
        stats = export_drafter_a(getattr(args, "gold", None))
        print(f"Drafter-A: silver={stats['silver']} -> {stats['silver_path']}")
        print(f"           gold={stats['gold']} -> {stats['gold_path']}")
        return 0

    if args.cmd == "validate":
        n = validate_file(args.file, args.kind)
        return 0 if n > 0 else 1

    if args.cmd == "gate":
        return 0 if flywheel_gate() else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
