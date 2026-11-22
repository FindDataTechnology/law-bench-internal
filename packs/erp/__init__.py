"""ERP domain pack: 账本体一致性线。

两件事：

- **确定性 checker**（``checks``，``kind ∈ {account, crosswalk}``）——只读地对账
  ERP 域的知识单位：行业科目映射的目标在通用科目闭集内、映射近端在本域活着、
  映射不冒充已复核、科目带 evidence 锚点。零 LLM、零网络、零跨表联查。

导入即注册：``from packs.erp import checks`` 会把 checker 装进
``src.bench.data_checks``。没导入就是「什么都不做」——这是安全默认。
"""

from packs.erp import checks  # noqa: F401  (registration side effect)

__all__ = ["checks"]
