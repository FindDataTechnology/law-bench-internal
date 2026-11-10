"""智能体身份的识别口径（一个前缀，两处闸门共用）。

为什么单独一个模块：**同一个判断要用在两个互不依赖的地方**——

- ``apikey.create_key`` 铸凭据时不许给智能体 ``admin``/``*``；
- ``proposals.confirm`` 确认提案时不许智能体当签字人，且管理员豁免对智能体
  提交的提案无效。

如果两处各写一遍 ``startswith("agent:")``，它们迟早会漂移：一处改了前缀，另一处
还认得旧写法，闸门就静默失效。这里只有一个字符串常量，改它等于同时改两处。

身份形如 ``agent:<role>@<domain>``，例如 ``agent:concept@legal``。它是普通域成员
（``role=expert``），不是平台管理员——这条由铸凭据时的闸保证，不靠约定。
"""

from __future__ import annotations

from typing import Optional

#: 所有智能体身份共用的前缀。改它会让既有凭据失效，因此不轻易改。
AGENT_PREFIX = "agent:"

#: 不允许智能体持有的平台级权限。
FORBIDDEN_FOR_AGENTS = frozenset({"admin", "*"})


def is_agent(identity: Optional[str]) -> bool:
    """``True`` when ``identity`` is an agent identity (empty/None is not)."""
    return bool((identity or "").strip().startswith(AGENT_PREFIX))


def agent_identity(role: str, domain_key: str) -> str:
    """构造标准身份串：``agent:<role>@<domain>``。

    两个分量都不许为空、不许含空白或 ``@``——身份一旦带歧义，审计里就分不清
    是哪个岗位在哪条线上做的那件事。
    """
    role = (role or "").strip()
    domain_key = (domain_key or "").strip()
    if not role or not domain_key:
        raise ValueError("智能体身份需要 role 与 domain_key")
    for name, value in (("role", role), ("domain_key", domain_key)):
        if "@" in value or any(ch.isspace() for ch in value):
            raise ValueError(f"{name} 不得包含 '@' 或空白：{value!r}")
    return f"{AGENT_PREFIX}{role}@{domain_key}"


def forbidden_scopes(scopes: Optional[list[str]]) -> list[str]:
    """该身份不允许持有的 scope 中，实际给出的那些（空表示合规）。"""
    return sorted(FORBIDDEN_FOR_AGENTS.intersection(scopes or []))
