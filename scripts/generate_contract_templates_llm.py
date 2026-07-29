#!/usr/bin/env python3
"""Generate type-specific contract template bodies via the doubao LLM, informed
by each contract type's Doubao+DeepSeek 法律法规 answers, and refresh
``src/contracts/data/contracts.json``.

For each contract class the script:
1. reads the bundled 法律法规 answers (``src/eval/seed/law_info/{deepseek,doubao}/<key>.md``);
2. prompts the DRAFTER LLM (doubao via Ark, OpenAI-compatible) to draft a
   specific contract body containing exactly the 12 ``{{slot}}`` placeholders;
3. normalizes the output (strip unknown tokens, append any missing required
   slots) so slot/instruction consistency holds;
4. caches the body to ``src/contracts/data/_llm_bodies/<key>.md`` (re-run with
   ``--force`` to regenerate).

The slot-instruction manifest is unchanged. On LLM failure the existing
(skeleton) body is kept, so the run is non-destructive.

Usage::

    uv run python scripts/generate_contract_templates_llm.py [--force] [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
# Avoid litellm's remote model-cost-map fetch (network-dependent); local fallback.
os.environ.setdefault("LITELLM_MODEL_COST_MAP_URL", "")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.contracts.slots import REQUIRED_SLOTS, default_slot_instructions  # noqa: E402
from src.contracts.templates import normalize_body  # noqa: E402

LAW_INFO_DIR = REPO_ROOT / "src" / "eval" / "seed" / "law_info"
TYPES_PATH = LAW_INFO_DIR / "contract_types.json"
REGISTRY_PATH = REPO_ROOT / "src" / "contracts" / "data" / "contracts.json"
BODIES_DIR = REPO_ROOT / "src" / "contracts" / "data" / "_llm_bodies"
_SOURCES = ("doubao", "deepseek")


def _read_law_context(key: str) -> str:
    parts = []
    for source in _SOURCES:
        p = LAW_INFO_DIR / source / f"{key}.md"
        if p.is_file():
            parts.append(f"### 来源：{source}\n\n{p.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)


def _build_prompt(zh: str, law_context: str) -> str:
    slots = "、".join("{{" + s + "}}" for s in REQUIRED_SLOTS)
    return (
        f"你是资深中国法律合同起草人。请依据下方《{zh}》相关法律法规，起草一份具体、完整、"
        f"可实际使用的{zh}正文（简体中文，Markdown 格式）。\n\n"
        "要求：\n"
        "1. 必须包含且仅包含以下占位符（原样保留双花括号，不得改名、不得增删）：\n"
        f"   {slots}\n"
        "2. 结构：当事人（甲方：{{party_a}}、乙方：{{party_b}}）、鉴于（引用相关法律法规）、"
        "合同标的、价款及支付、履行期限、双方权利义务（针对本类合同的具体义务，不要泛泛而谈）、"
        "违约责任、争议解决、附则、签署信息（含{{sign_date}}、{{sign_location}}）。\n"
        "3. 章节使用二级标题（##），不要输出一级标题（#），不要输出任何解释、前言或代码块标记。\n"
        "4. 条款内容要结合所依据的法律法规，体现该类合同的特点。\n\n"
        f"相关法律法规：\n\n{law_context}"
    )


def _call_llm(prompt: str) -> str:
    import litellm

    model = os.environ.get("DRAFTER_MODEL")
    if not model:
        raise RuntimeError("DRAFTER_MODEL is not set")
    resp = litellm.completion(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=float(os.environ.get("DRAFTER_TEMPERATURE", "0.3")),
        max_tokens=int(os.environ.get("DRAFTER_MAX_TOKENS", "4096")),
    )
    return resp.choices[0].message.content or ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate type-specific contract template bodies via the doubao LLM.",
    )
    parser.add_argument("--force", action="store_true", help="re-generate even if a cached body exists")
    parser.add_argument("--limit", type=int, default=None, help="only generate the first N types (debug)")
    args = parser.parse_args()

    types = json.loads(TYPES_PATH.read_text(encoding="utf-8"))
    targets = types[: args.limit] if args.limit else types

    BODIES_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict[str, dict] = {}
    if REGISTRY_PATH.is_file():
        for e in json.loads(REGISTRY_PATH.read_text(encoding="utf-8")):
            existing[e["key"]] = e

    bodies: dict[str, str] = {}
    ok = cached = failed = 0
    for t in targets:
        key, zh = t["key"], t["zh"]
        cache = BODIES_DIR / f"{key}.md"
        if cache.is_file() and not args.force:
            bodies[key] = cache.read_text(encoding="utf-8")
            cached += 1
            print(f"[cached] {key}")
            continue
        try:
            raw = _call_llm(_build_prompt(zh, _read_law_context(key)))
        except Exception as exc:  # noqa: BLE001 - report and fall back
            print(f"[fail] {key}: {exc}", file=sys.stderr)
            failed += 1
            if key in existing:
                bodies[key] = existing[key]["body"]
            continue
        body = normalize_body(raw, list(REQUIRED_SLOTS))
        cache.write_text(body, encoding="utf-8")
        bodies[key] = body
        ok += 1
        print(f"[ok] {key} ({len(body)} chars)")

    # assemble the full registry (all types), preserving order
    registry = []
    for t in types:
        key, zh = t["key"], t["zh"]
        body = bodies.get(key) or existing.get(key, {}).get("body", "")
        registry.append(
            {"key": key, "zh": zh, "body": body, "slot_instructions": default_slot_instructions(zh)}
        )
    REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"\nwrote {len(registry)} templates to {REGISTRY_PATH} "
        f"(ok={ok}, cached={cached}, failed={failed})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
