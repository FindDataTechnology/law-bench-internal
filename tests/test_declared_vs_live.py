"""声明 vs live 一致性校验器自身的行为（lex-matter-spine 5.6）。

为什么校验器需要被测试：它第一版就有过一个自伤式 bug——采集产物里的"值"是类型令牌
（`"bool"`/`"int"`），而比对器拿 **Python 类型名** 去比，于是 10 件声明全被判"实返回 str"。
**校验器的假红会让人把正确的声明改错**，比漏报更危险；所以三个方向都要钉住：

1. 一致时绿（且空集只告警不判红——"数据空"不是"声明错"）；
2. 缺字段时红，并指名字段路径；
3. 类型令牌能正确比对（本测试的第 3 条就是那个 bug 的回归锚点）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_declared_vs_live.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_declared_vs_live", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker():
    return _load()


def _compare(checker, declared, live):
    problems: list[str] = []
    notes: list[str] = []
    checker.compare("t", declared, live, problems, notes)
    return problems, notes


def test_type_tokens_compare_equal(checker):
    """采集产物给的是令牌字符串，声明写的是类型名——两者必须判等。"""
    declared = {"passed": "bool", "count": "int", "name": "string", "path": "string|null"}
    live = {"passed": "bool", "count": "int", "name": "string", "path": "null"}
    problems, _ = _compare(checker, declared, live)
    assert problems == []


def test_missing_key_is_named(checker):
    problems, _ = _compare(checker, {"body_text": "string"}, {})
    assert problems == ["t.body_text: 声明有、实返回无"]


def test_kind_mismatch_is_named(checker):
    problems, _ = _compare(checker, {"dims": {"stance": ["string"]}}, {"dims": ["string"]})
    assert problems == ["t.dims: 声明为对象，实返回 list"]


def test_extra_key_is_named(checker):
    problems, _ = _compare(checker, {"a": "string"}, {"a": "string", "b": "int"})
    assert problems == ["t: 实返回多出未声明键 ['b']"]


def test_empty_array_is_a_note_not_a_failure(checker):
    """库里没数据时元素形状无法证明——那是数据缺口，不该冒充声明缺陷。"""
    problems, notes = _compare(checker, {"result": [{"key": "string"}]}, {"result": []})
    assert problems == []
    assert notes and "未观测" in notes[0]


def test_int_is_not_satisfied_by_bool(checker):
    """bool 是 int 的子类；放宽会漏掉"计数位被写成开关"这类真实漂移。"""
    problems, _ = _compare(checker, {"slot_count": "int"}, {"slot_count": "bool"})
    assert problems == ["t.slot_count: 声明 int，实返回 bool"]


def test_manifest_entries_carry_no_prose_in_returns():
    """形状栏只允许类型令牌：说明文字进 field_notes，字面取值进 values。

    混写会让"类型"这个词在 manifest 里失去唯一含义，比对器也就无从下手。
    """
    manifest = json.loads((REPO / "tool-surface.json").read_text(encoding="utf-8"))
    detail = manifest["output_structure"]["declared_detail"]

    def walk(path, node):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{path}.{key}", value)
            return
        if isinstance(node, list):
            for index, value in enumerate(node):
                walk(f"{path}[{index}]", value)
            return
        # object / array 也是类型令牌：guard 要拦的是"说明文字混进 returns"，
        # 不是"只许标量"。白名单漏了容器类型，另线的 manifest 一写 object|null
        # 就会被误判成散文。
        assert node in {"string", "int", "bool", "float", "null", "string|null",
                        "object", "array", "object|null", "array|null"}, (
            f"{path}: returns 里出现了非类型内容 {node!r}；说明文字请放 field_notes"
        )

    for name, spec in detail.items():
        walk(name, spec.get("returns", {}))


def test_empty_dict_declaration_means_variable_keys(checker):
    """空对象 = 键随数据变化的映射（sha256_by_format），只验是对象、键留旁注。"""
    problems, notes = _compare(checker, {"by_format": {}}, {"by_format": {"pdf": "string"}})
    assert problems == []
    assert notes and "动态键映射" in notes[0]


def test_empty_dict_declaration_still_requires_an_object(checker):
    problems, _ = _compare(checker, {"by_format": {}}, {"by_format": ["string"]})
    assert problems == ["t.by_format: 声明为对象，实返回 list"]
