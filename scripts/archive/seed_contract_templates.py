"""Generate the contract template + slot-instruction registry.

Writes ``src/contracts/data/contracts.json``: a list of
``{key, zh, body, slot_instructions:[{name,label,description,example,required}]}``
for every contract class in ``output/law_info/contract_types.json``.

The body is a standard Chinese contract skeleton with ``{{slot}}`` placeholders
(reusing the ``document-generation`` slot token model); the slot-instruction
manifest documents every slot. Run after editing to refresh the registry::

    uv run python scripts/seed_contract_templates.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from src.contracts.slots import default_slot_instructions  # noqa: E402

TYPES_PATH = REPO_ROOT / "src" / "eval" / "seed" / "law_info" / "contract_types.json"
OUT_PATH = REPO_ROOT / "src" / "contracts" / "data" / "contracts.json"

# Body skeleton. %ZH% is replaced with the contract's 中文名; {{slot}} tokens are
# fillable placeholders (kept verbatim, not f-string interpolation).
_BODY_TEMPLATE = """\
甲方：{{party_a}}
乙方：{{party_b}}

鉴于甲乙双方就%ZH%事宜，经友好协商，依据《中华人民共和国民法典》及相关法律法规，本着平等自愿、诚实信用的原则，达成如下协议，以资共同遵守。

## 第一条 合同标的

本合同标的为：{{subject}}。

## 第二条 价款及支付方式

本合同项下价款为人民币{{amount}}元。支付方式及支付期限由双方按本条约定执行。

## 第三条 履行期限

本合同履行期限自{{term_start}}起至{{term_end}}止。

## 第四条 双方权利义务

1. 甲方的主要义务：{{party_a_duty}}。
2. 乙方的主要义务：{{party_b_duty}}。

## 第五条 违约责任

任何一方违反本合同约定，应向守约方支付违约金{{penalty}}，并赔偿守约方因此遭受的实际损失。

## 第六条 争议解决

因本合同引起的或与本合同有关的任何争议，双方应友好协商解决；协商不成的，按下列方式解决：{{jurisdiction}}。

## 第七条 附则

1. 本合同自双方签字（盖章）之日起生效。
2. 本合同一式两份，甲乙双方各执一份，具有同等法律效力。

签署日期：{{sign_date}}
签署地点：{{sign_location}}
"""


def main() -> None:
    types = json.loads(TYPES_PATH.read_text(encoding="utf-8"))
    registry = []
    for t in types:
        key, zh = t["key"], t["zh"]
        body = _BODY_TEMPLATE.replace("%ZH%", zh)
        registry.append(
            {"key": key, "zh": zh, "body": body, "slot_instructions": default_slot_instructions(zh)}
        )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {len(registry)} contract templates to {OUT_PATH}")


if __name__ == "__main__":
    main()
