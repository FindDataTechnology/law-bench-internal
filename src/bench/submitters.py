"""提交方身份的判定（纯函数，零 DB 依赖）。

**为什么单独一个模块**：这条判定要在进程内与 HTTP 两个调用点用同一份逻辑，而
它最容易错的地方不是查表，是**哪一类来源凭什么可信**。三类来源的可信依据完全
不同：

- ``fleet:<fleet_id>/<post_id>`` —— 外部提交方，凭**登记 + 凭据**（登记绑定域、
  可吊销）。这是唯一允许走外部 HTTP 的类别。
- ``extract:<model>:<prompt_version>`` —— 抽取流水线，凭**调用位置**。它由
  ``src/bench/extraction.py`` 在进程内调用，没有凭据可验；因此它的可信依据就是
  「不在网络面上」。外部端点必须拒绝该类，否则任何人把来源写成 ``extract:任意``
  即可冒充流水线。
- ``agent:<role>@<domain>`` —— 平台自铸身份（``agent_ids.py``），凭**已铸凭据 +
  域成员身份**。自报该前缀会让「自提自确认禁令」在错误身份上生效。

把三类压成一条「有登记就放行」的规则会同时放过冒充者、拒掉真正的生产者（生产库
实测：93 条提案里 78 条是 ``extract:`` 前缀的流水线产物）。

判定与查表分开：本模块只做判断，调用方负责把登记行与成员事实取来。这样判定可以
在没有任何数据库的情况下被穷举测试——而这正是它必须被穷举的理由。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

#: 三类来源的前缀。改它们等于改契约，不轻改。
PREFIX_FLEET = "fleet:"
PREFIX_EXTRACT = "extract:"
PREFIX_AGENT = "agent:"

#: 提交通道。``extract:`` 只在 ``in_process`` 下被接受。
VIA_HTTP = "http"
VIA_IN_PROCESS = "in_process"

#: 判定结论。每一个都对应一句能对提交方说清的话，不留「其它」。
VERDICTS: tuple[str, ...] = (
    "ok",
    "unregistered",          # fleet：没有这条登记
    "revoked",               # fleet：登记已吊销
    "domain_mismatch",       # fleet：登记未绑定目标域
    "pipeline_impersonation",  # extract：从外部通道提交
    "agent_domain_mismatch",  # agent：身份里的域与目标域不一致
    "agent_not_member",      # agent：身份不在该域活跃成员里
    "malformed",             # 前缀认得，形状不完整
    "unknown_prefix",        # 三类之外
)

#: 需要按类别报明给提交方的形状要求（拼错前缀时就列这个）。
SHAPES: dict[str, str] = {
    PREFIX_FLEET: "fleet:<fleet_id>/<post_id>",
    PREFIX_EXTRACT: "extract:<model>:<prompt_version>",
    PREFIX_AGENT: "agent:<role>@<domain>",
}


def classify_source(source: Optional[str]) -> Tuple[Optional[str], Optional[dict], bool]:
    """把来源拆成 ``(prefix, parts, malformed)``。

    ``prefix`` 为 ``None`` 表示不属于任何一类；``malformed`` 表示前缀认得但形状
    不完整（例如 ``fleet:`` 后面没有 ``/``）。两者都拒绝，但报的话不同。
    """
    text = (source or "").strip()
    if text.startswith(PREFIX_FLEET):
        rest = text[len(PREFIX_FLEET):]
        fleet_id, sep, post_id = rest.partition("/")
        if not sep or not fleet_id or not post_id:
            return PREFIX_FLEET, None, True
        return PREFIX_FLEET, {"fleet_id": fleet_id, "post_id": post_id}, False

    if text.startswith(PREFIX_EXTRACT):
        rest = text[len(PREFIX_EXTRACT):]
        model, sep, version = rest.partition(":")
        if not sep or not model or not version or ":" in version:
            return PREFIX_EXTRACT, None, True
        return PREFIX_EXTRACT, {"model": model, "prompt_version": version}, False

    if text.startswith(PREFIX_AGENT):
        rest = text[len(PREFIX_AGENT):]
        role, sep, domain = rest.partition("@")
        if not sep or not role or not domain or "@" in domain:
            return PREFIX_AGENT, None, True
        return PREFIX_AGENT, {"role": role, "domain": domain}, False

    return None, None, False


def verdict(
    source: Optional[str],
    *,
    domain_key: str,
    via: str,
    fleet: Optional[Mapping[str, Any]] = None,
    agent_is_member: Optional[bool] = None,
) -> str:
    """判定一条提交来源在其目标域上是否可被接受。

    ``fleet`` 传登记行投影（``{"domains": [...], "revoked": bool}``），``None``
    表示查无登记。``agent_is_member`` 为该身份是否仍是目标域的活跃成员。

    调用方**必须**把 ``via`` 说对：``extract:`` 的放行只依赖它。传错的后果不是
    「校验变宽松」，而是「校验消失」——所以两个调用点各传自己的常量，不共享。
    """
    prefix, parts, malformed = classify_source(source)

    if prefix is None:
        return "unknown_prefix"
    if malformed or parts is None:
        return "malformed"

    if prefix == PREFIX_EXTRACT:
        return "ok" if via == VIA_IN_PROCESS else "pipeline_impersonation"

    if prefix == PREFIX_AGENT:
        if parts["domain"] != (domain_key or "").strip():
            return "agent_domain_mismatch"
        return "ok" if agent_is_member else "agent_not_member"

    # fleet
    if fleet is None:
        return "unregistered"
    if fleet.get("revoked"):
        return "revoked"
    domains = fleet.get("domains") or []
    if (domain_key or "").strip() not in domains:
        return "domain_mismatch"
    return "ok"


def is_allowed(result: str) -> bool:
    """结论是否放行。只有 ``ok`` 放行；宽松迁移档由调用方另行处理。"""
    return result == "ok"
