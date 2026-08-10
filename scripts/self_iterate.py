#!/usr/bin/env python3
"""V4 self-iteration: evaluate a contract, find unanimous-FAIL topics, generate clauses.

Closed loop per round:
1. Generate contract (balanced stance)
2. Serial multi-judge eval (max_workers=1) to avoid rate-limit noise
3. Collect unanimous-FAIL criteria (conf=1.0) → map to legal_topic
4. For each gap, LLM-generate a custom clause (merging base's rich content)
5. Create + approve the clause (tag_review all dims approved)
6. Re-eval; loop until all-pass or max_rounds

Usage:
    python scripts/self_iterate.py <contract_type> [--max-rounds 5] [--judges ...]
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

import litellm

from src.clauses.assemble import generate_contract_assembled
from src.clauses.store import create_clause, list_clauses
from src.clauses.tag_review import review_tag
from src.eval.rubric import list_rubrics, load_criteria
from src.eval.scoring import evaluate_with_multi_judge

DEFAULT_JUDGES = ["openai/kimi-k3", "openai/glm-5.2", "openai/deepseek-v3"]
GEN_MODEL = os.environ.get("DRAFTER_MODEL", "openai/glm-5.2")


def get_latest_rubric(contract_type: str) -> str:
    rubrics = [r["name"] for r in list_rubrics() if r["name"].startswith(f"contract_{contract_type}_")]
    return max(rubrics) if rubrics else f"contract_{contract_type}_v3"


def generate_clause(contract_type, section, legal_topic, base_body, criteria, model=GEN_MODEL) -> str | None:
    """LLM-generate a custom clause for a missing legal_topic, merging base content."""
    return generate_combined_clause(contract_type, section, legal_topic, "", base_body, criteria, model=model)


def generate_combined_clause(contract_type, section, topics_str, existing_body, base_body, criteria, model=GEN_MODEL) -> str | None:
    """LLM-generate ONE combined clause covering multiple legal_topics for a section.

    Merges existing custom body (if any) + base body so no rich content is lost.
    """
    topics = [t.strip() for t in topics_str.split(",") if t.strip()]
    criteria_ctx = ""
    for t in topics:
        c = next((x for x in criteria if x["id"] == t), None)
        if c:
            guidance = c.get("match_criteria", "") or c.get("guidance", "") or c.get("description", "")
            criteria_ctx += f"- {t}: {guidance}\n"

    prompt = f"""你是中国合同起草专家。需要为{contract_type}合同的"{section}"章节起草一条完整条款，满足以下评审标准：

{criteria_ctx}

【重要——保留现有内容】该章节已有以下条款内容，必须**全部保留并整合**，不得丢失任何法律要点：

=== 现有自定义条款 ===
{existing_body[:1500] if existing_body else "（无）"}

=== 母版基础条款 ===
{base_body[:1500] if base_body else "（无）"}

请输出整合后的完整条款，要求：
1. 满足上述所有评审标准 {topics}
2. 保留现有条款 + 基础条款中的所有实质内容（风险承担、瑕疵担保、检验、违约责任等都要在）
3. 引用相关《民法典》条文
4. 使用{{{{slot}}}}占位符表示空白（如{{{{days}}}}、{{{{location}}}}）
5. 只输出条款正文，不要解释

条款正文："""

    for attempt in range(3):
        try:
            resp = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=int(os.environ.get("GEN_MAX_TOKENS", "800")),
            )
            text = resp.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            return text
        except Exception as e:
            if "RateLimit" in str(e) or "ServiceUnavailable" in str(e):
                time.sleep(15 * (attempt + 1))
                continue
            print(f"  ⚠ Generation error: {e}")
            return None
    return None


def ensure_base_clauses(contract_type: str) -> None:
    """Seed base clauses from contracts.json mother template if missing."""
    from src.clauses.store import _INSERT_COLS, _row, _finalize, _now
    from src.clauses.extract import SECTION_ORDER
    from src.eval.db import connect
    import re
    import json as _json

    base = list_clauses(contract_type, category="base")
    if base:
        return

    CATALOG = {x["key"]: x for x in _json.load(open("src/contracts/data/contracts.json"))}
    if contract_type not in CATALOG:
        print(f"⚠ No mother template for {contract_type}")
        return
    entry = CATALOG[contract_type]
    zh = entry["zh"]
    marker = f"生成母版（{zh}）"
    mother_si = entry.get("slot_instructions") or []

    conn = connect()
    try:
        for p in re.split(r"^## ", entry["body"], flags=re.M):
            if not p.strip():
                continue
            head, _, rest = p.partition("\n")
            sec = head.strip()
            sec = re.sub(r"^第[一二三四五六七八九十百]+条\s*", "", sec)
            sec = re.sub(r"合同$", "", sec).strip()
            if sec == "价款及支付方式":
                sec = "价款及支付"
            if sec == "双方权利义务":
                sec = "权利义务"
            if sec not in SECTION_ORDER:
                print(f"  [skip] {contract_type}: unknown section {head!r} -> {sec!r}")
                continue
            body = rest.strip()
            rec = _finalize({
                "contract_type": contract_type, "section": sec, "body": body,
                "slot_instructions": mother_si, "law_refs": [],
                "source_path": None, "source_doc_title": marker,
                "manual": True, "tags": {"source": "base"}, "tag_review": {},
            }, body)
            conn.execute(
                "INSERT INTO clauses (" + _INSERT_COLS + ") VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                _row(rec, now=_now()),
            )
        conn.commit()
        print(f"✅ Seeded base clauses for {contract_type}")
    finally:
        conn.close()


def iterate(contract_type: str, max_rounds: int = 5, judges: list[str] | None = None) -> dict:
    judges = judges or DEFAULT_JUDGES
    rubric = get_latest_rubric(contract_type)
    criteria = load_criteria(rubric)
    print(f"Contract type: {contract_type}")
    print(f"Rubric: {rubric} ({len(criteria)} criteria)")
    print(f"Judges: {judges}")
    print(f"Max rounds: {max_rounds}")

    ensure_base_clauses(contract_type)

    report = {"type": contract_type, "rounds": []}
    for round_no in range(1, max_rounds + 1):
        print(f"\n{'='*60}\nROUND {round_no}\n{'='*60}")

        # Generate contract
        result = generate_contract_assembled(contract_type=contract_type, stance="balanced", format="markdown")
        body = result.get("body_text", "")
        print(f"Contract: {len(body)} chars")

        # Evaluate (serial)
        eval_result = evaluate_with_multi_judge(
            contract_text=body, rubric_name=rubric, judge_models=judges, max_workers=1,
        )
        n_passed = eval_result["n_passed"]
        n_total = eval_result["n_criteria"]
        print(f"Score: {eval_result['score']}  Passed: {n_passed}/{n_total}")

        round_rec = {"round": round_no, "score": eval_result["score"], "n_passed": n_passed, "n_total": n_total, "generated": []}

        # Show criteria
        fails = []
        for cr in eval_result.get("criteria_results", []):
            mark = "✓" if cr["verdict"] == "pass" else "✗"
            print(f"  {mark} [{cr['verdict']}] conf={cr.get('confidence', 0):.2f} {cr['id']}")
            if cr["verdict"] != "pass" and cr.get("confidence", 0) >= 0.99:
                fails.append(cr)

        if eval_result["all_pass"]:
            print(f"\n🎉 ALL PASS in round {round_no}!")
            report["rounds"].append(round_rec)
            report["all_pass"] = True
            report["final_round"] = round_no
            break

        # Generate clauses for unanimous-fail topics
        if not fails:
            print("\nNo unanimous-FAIL criteria; stopping (remaining fails are judge-split noise)")
            report["rounds"].append(round_rec)
            report["all_pass"] = False
            break

        # Group fails by section to MERGE into existing clauses (avoid override conflicts)
        sections_needing = {}
        for fail in fails:
            topic = fail["id"]
            existing = [c for c in list_clauses(contract_type) if c.get("tags", {}).get("legal_topic") == topic]
            section = existing[0].get("section") if existing else "权利义务"
            sections_needing.setdefault(section, []).append(topic)

        for section, topics in sections_needing.items():
            # Find an existing assembly-ready custom clause in this section to merge into,
            # else fall back to base body for context
            existing_customs = [c for c in list_clauses(contract_type, category="custom")
                                if c.get("section") == section and c.get("tags", {}).get("stance") == "balanced"]
            existing_custom = None
            for c in existing_customs:
                tags = c.get("tags", {})
                review = c.get("tag_review", {})
                if all(review.get(d) == "approved" for d in tags):
                    existing_custom = c
                    break

            base_body = ""
            for c in list_clauses(contract_type, category="base"):
                if c.get("section") == section:
                    base_body = c.get("body", "")
                    break

            # Build merged prompt context: existing custom body (if any) + base body
            merge_ctx = existing_custom["body"] if existing_custom else ""
            print(f"\n  Merging fails for section={section}: topics={topics}")
            if existing_custom:
                print(f"    → will UPDATE existing custom id={existing_custom['id']} (merge, not replace)")
            elif merge_ctx == "" and base_body:
                print(f"    → no custom yet; will create from base context")

            # Generate ONE combined clause covering all topics for this section
            topic_list = ", ".join(topics)
            clause_body = generate_combined_clause(
                contract_type, section, topic_list, merge_ctx, base_body, criteria
            )
            if not clause_body:
                print(f"  ⚠ Generation failed for section {section}")
                continue

            if existing_custom:
                # UPDATE existing custom: merge new topics into it (keep its legal_topic tag,
                # or add the new primary topic). Use update_clause to preserve source.
                from src.clauses.store import update_clause
                new_tags = dict(existing_custom["tags"])
                new_tags["legal_topic"] = topics[0]  # primary topic for this section
                try:
                    update_clause(existing_custom["id"], fields={"body": clause_body, "tags": new_tags})
                    print(f"  ✅ Updated custom id={existing_custom['id']} covering {topic_list}")
                    round_rec["generated"].append({"clause_id": existing_custom["id"], "topic": topic_list, "section": section, "merged": True})
                except Exception as e:
                    print(f"  ⚠ Update error for {existing_custom['id']}: {e}")
            else:
                # Create new clause
                new_clause = {
                    "contract_type": contract_type,
                    "section": section,
                    "body": clause_body,
                    "tags": {"source": "custom", "stance": "balanced", "legal_topic": topics[0]},
                    "tag_review": {},
                    "manual": True,
                }
                try:
                    cid = create_clause(new_clause)
                    for dim in new_clause["tags"]:
                        review_tag(cid, dim, "approved")
                    print(f"  ✅ Created + approved clause id={cid} for {topic_list}")
                    round_rec["generated"].append({"clause_id": cid, "topic": topic_list, "section": section})
                except Exception as e:
                    print(f"  ⚠ Create/approve error for {topic_list}: {e}")

        # Small delay before next round
        time.sleep(2)

    else:
        report["rounds"].append(round_rec)
        report["all_pass"] = eval_result["all_pass"]
        report["final_round"] = max_rounds

    report["rounds"] = report.get("rounds", [])
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("contract_type", help="Contract type to self-iterate (e.g. sale, lease)")
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--judges", nargs="+", default=DEFAULT_JUDGES)
    args = ap.parse_args()

    report = iterate(args.contract_type, max_rounds=args.max_rounds, judges=args.judges)

    # Save report
    out = Path("output/self_iterate") / f"{args.contract_type}_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved: {out}")
    print(f"Final: {report.get('all_pass', False)} ({report.get('final_round', '?')} rounds)")

    return 0 if report.get("all_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
