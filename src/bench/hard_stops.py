"""硬停清单：智能体做什么动作会被拒，以及拒因。

spec `domain-agent-team` 的「权限矩阵与硬停清单」写了五个动作「SHALL NOT 被任何
智能体执行」，而这五个判据在代码里一直**没有实现**——2026-11-21 实测
`grep HARD_STOP src` 零命中。同一个空档里发生了一次真实事故：为了让一支舰队能确认
提案，我把它的域角色提到了 `lead`，于是「智能体最高 expert」这条也随之被破。

所以这个模块存在的理由不是「再加一层校验」，是**让禁令有一个执行点**。写进 spec
却没有落点的禁令，在需要它的时候不会出现——那时能拦住你的只有记忆。

五个动作与它们的落点（一个动作只在一处判）：

    open_or_archive_domain   workspaces.instantiate_domain / archive / restore
    widen_sourcing_scope     libraries 的订阅写入（父域未授予的源）
    change_template_version  templates.update_template / promote_template_via_gate
    delete_unit              authoring.authoring_delete_unit
    mint_credential          apikey 铸造入口

**确认提案不在这份清单上**（2026-11-21 修订）。智能体确认产出 `silver`，升 `gold`
须人类 reviewer；人签落在升档而非确认，见 `bench-platform` 的档位阶梯条款。

判据只回答「这个身份能不能做这个动作」，不查库、不看域——身份类别是纯函数。这样
每个入口只要调一次，测试也不用准备数据库。
"""

from __future__ import annotations

from typing import Optional

from . import agent_ids

#: 硬停动作，闭集。加一项等于加一份权限面，所以词表是闭的。
HARD_STOP_ACTIONS: tuple[str, ...] = (
    "open_or_archive_domain",
    "widen_sourcing_scope",
    "change_template_version",
    "delete_unit",
    "mint_credential",
)

#: 每类动作被拒时给调用方的正解。只说「不允许」而不说「那该怎么做」，是让下一个人
#: 去猜，而他猜到的第一件事通常是绕过它——2026-11-21 我提权就是那么发生的。
_REMEDY: dict[str, str] = {
    "open_or_archive_domain":
        "开域与归档属平台管理员的操作；智能体可以提出申请（任务或报告）",
    "widen_sourcing_scope":
        "取材范围由父域授予；智能体只能提出申请，不得自行订阅或放宽",
    "change_template_version":
        "模板版本由域负责人变更；智能体可以把改进写成提案，不能自行升版",
    "delete_unit":
        "删除知识单元须人工执行；智能体可以标注存疑（提案或报告），不能删",
    "mint_credential":
        "凭据铸造属平台管理员；智能体的身份由铸造者登记，不能自铸",
}


class HardStopError(PermissionError):
    """一个硬停动作被机器身份发起。"""

    def __init__(self, action: str, actor: str) -> None:
        if action not in HARD_STOP_ACTIONS:
            raise ValueError(
                f"unknown hard-stop action {action!r}; "
                f"expected one of {list(HARD_STOP_ACTIONS)}"
            )
        self.action = action
        self.actor = actor
        super().__init__(
            f"动作 {action!r} 不允许机器身份 {actor!r} 执行；{_REMEDY[action]}"
        )


def remedy_for(action: str) -> str:
    if action not in HARD_STOP_ACTIONS:
        raise ValueError(f"unknown hard-stop action {action!r}")
    return _REMEDY[action]


def check(actor: Optional[str], action: str) -> None:
    """Refuse a hard-stop action from a machine identity; otherwise return.

    Raises :class:`HardStopError` (a ``PermissionError``, so existing
    ``except PermissionError`` callers keep working) naming the action, the
    actor and the legitimate path.

    A human identity — bare name, email, ``user:``, or the operational-decision
    class ``ops:<operator>/<reason>`` — passes. The ops class is a person's
    batch disposition, not a machine action; see ``agent_ids.is_ops``.
    """
    if not agent_ids.is_machine(actor):
        return
    raise HardStopError(action, actor or "")
