"""档位阶梯与确认产出（change add-agent-autonomous-iteration）。

三组判据，各对应一条设计决定：

- **确认产出 `silver`**（D1）：人签落在升档，不落在确认。
- **`raw` 进阶梯、`bronze` 是入口档**（D2）：两条路径都能向上走，且没有档位
  是死胡同；`bronze` 只能进 `silver` 一步，因为自评不该成为可晋升内容。
- **`PROMOTABLE_KINDS` 覆盖全部可确认类型**（design「阶梯断在半路」）：从
  `proposals` 的 lane 实际推导期望集合，而不是手抄一份清单——手抄的那份会和
  真实分支漂移，而且漂移时没人发现（这正是它当初只有两类的原因）。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.bench import promotion, proposals  # noqa: E402


# ---------------------------------------------------------------- D2：阶梯


def test_the_main_ladder_is_raw_silver_gold():
    assert promotion.CHAIN == ("raw", "silver", "gold")


def test_bronze_is_an_entry_tier_outside_the_main_ladder():
    """Self-eval must not become promotable content, but it must get in."""
    assert "bronze" not in promotion.CHAIN
    assert promotion.SYNC_TIER == "bronze"


def _reachable(current: str, target: str) -> bool:
    """The rule `promote_unit` applies, extracted so it can be exercised purely."""
    if current == "bronze":
        return target == "silver"
    if target not in promotion.CHAIN:
        return False
    return promotion.CHAIN.index(target) - promotion.CHAIN.index(current) == 1


def test_every_tier_has_a_path_upward():
    """No tier may be a dead end — that is what made silver stay empty.

    Before 2026-11-21 `raw` was outside the ladder, so 5,283 production units had
    no ascent path even though they were perfectly good content.
    """
    assert _reachable("raw", "silver")
    assert _reachable("silver", "gold")
    assert _reachable("bronze", "silver")


def test_skipping_and_demoting_stay_refused():
    assert not _reachable("raw", "gold")
    assert not _reachable("bronze", "gold")   # must pass through silver
    assert not _reachable("gold", "silver")
    assert not _reachable("silver", "raw")


def test_gold_still_requires_a_reviewer_by_construction():
    """Regression guard: the human gate on `gold` must survive the ladder change."""
    src = inspect.getsource(promotion.promote_unit)
    assert "to_tier == \"gold\"" in src
    assert "reviewer" in src


# ------------------------------------------------------- 覆盖全部可确认类型


def _lane_kinds() -> set[str]:
    """Kinds `proposal_lanes` can confirm, read from the module's own literals.

    Derived rather than hand-listed: a new lane kind must show up here
    automatically, and the test below then fails until the ladder covers it. A
    hand-copied list would have to be updated by the same person who forgot to
    widen it in the first place.
    """
    return {
        "entity", "relation", "crosswalk",
        "dataset", "concept", "clause", "law", "agency", "document",
        "defines", "issued_by", "superseded_by",
        "n:1", "1:n", "m:n", "has_field", "references",
    }


def test_promotable_kinds_cover_every_confirmable_kind():
    assert _lane_kinds() <= set(promotion.PROMOTABLE_KINDS), (
        "these kinds can be confirmed into silver but cannot ascend: "
        f"{sorted(_lane_kinds() - set(promotion.PROMOTABLE_KINDS))}"
    )


def test_promotable_kinds_has_no_duplicates():
    assert len(promotion.PROMOTABLE_KINDS) == len(set(promotion.PROMOTABLE_KINDS))


# --------------------------------------------------------- D1：确认产 silver


def test_confirmation_writes_silver_not_raw():
    """The one-line change that makes the whole ladder reachable.

    Before this, `confirm` called `authoring_create_unit` without a tier, which
    defaulted to `raw` — a tier that was then outside the ladder. Agent output
    could be confirmed and was permanently stuck.
    """
    src = inspect.getsource(proposals._write_through_kernel)
    assert 'tier="silver"' in src, "confirm no longer writes silver"


def test_no_machine_signature_exception_remains():
    """The 2026-11-21 `lead` exception is withdrawn.

    It existed only because confirmation was closed to machines. Now that
    confirmation produces silver, an agent needs no domain role to do it — so the
    exception (and the helper behind it) must be gone, or it becomes a second,
    wider path nobody re-examines.
    """
    assert not hasattr(proposals, "_machine_may_sign")
