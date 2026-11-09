# 概念层验收（2026-11-09，镜像 `sha-40a2315`）

## 一、这条路径打通了

```
模板 v2 发布：entity_types ['clause','law','concept']
              relationship_kinds [..., 'defines']    （其余词表原样）
legal 域升版：v1 → v2（template_id 1→2，一条 UPDATE 可回退）
裁判要点库登记：case-library / source guide_cases（text-table，text 列=gist）
legal 订阅：scope 变为 case-library(1 源) + law-library(7 源)
抽取（概念模式，8 条案例）：
  produced=2 submitted=2 duplicate=0  → by_kind {concept: 2}  可用率 1.0
  八类拒绝全为 0
```

**关键点：这 2 条是 `concept`，不是 `clause`。** 同一套管道在法规语料上只出条款，
在裁判要点上出概念——语料面决定产出类型这件事，现在是实测而不是推断。

## 二、但候选质量还不行

```
[concept] 没收较大数额涉案财产的行政处罚决定
[concept] 行政处罚违反法定程序
```

这两条是**案件事实描述**，不是概念。它们是「本条的适用情形」，抽象层级不对：真正的
概念是「听证程序」「行政处罚法定程序」「较大数额财产」。

原因：概念提示词只要求「优先抽取法律概念」并给了示例，但没有给**判别标准**——
什么样的字符串算概念。这一步不是管道问题，是提示词设计问题，需要：
- 明确要求「名词性、可跨案复用、不含具体数额/主体/事实」；
- 或加一道后置校验（长度上限、含数字/当事人名即拒）。

## 三、八类拒绝闸这次全是 0 —— 说明闸没被触发，不是闸失灵

上一轮法规语料里每类至少触发一次；这一轮 8 条案例只产出 2 条候选，样本太小。
扩量（293 条）时才会看到 `not_concept` 真正开始拦。

## 四、起始概念集已就位（未导入）

`packs/legal/starters/concepts-v1.json`：15 条，12 条带法条引用、3 条标「判例确立」，
6 条 `defines` 关系。**未写入生产**——导入是写操作，等复核后再做（dry-run 已在测试里
验过全部 create、零 error）。

## 五、回退

- 域升版：`UPDATE domains SET template_id=1, template_version=1 WHERE key='legal'`
- 裁判要点库：取消订阅或删除 `case-library`
- 模板 v2：模板只增不改，v2 留着不影响 v1 域
