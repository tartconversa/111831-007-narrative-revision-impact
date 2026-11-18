# 分类版本演进工作流

本文用一个拆分场景演示从“启用新口径”到“生成可解释报告”的完整流程。

## 1. 登记旧口径与新口径

```python
from datetime import date
from signal_lab import (
    Category, CategoryMapping, MappingKind, TaxonomyRegistry, TaxonomyVersion,
)

registry = TaxonomyRegistry()
registry.add_version(TaxonomyVersion(
    "v1", date(2026, 1, 1),
    {"security": Category("security", "安全议题"),
     "cooperation": Category("cooperation", "合作议题")},
))
registry.add_version(TaxonomyVersion(
    "v2", date(2026, 6, 1),
    {"military-security": Category("military-security", "军事安全"),
     "economic-security": Category("economic-security", "经济安全"),
     "cooperation": Category("cooperation", "合作议题"),
     "climate": Category("climate", "气候议题")},
))
```

## 2. 登记相邻版本之间的映射

```python
registry.add_mapping(CategoryMapping(
    "v1", "v2", "security",
    ("military-security", "economic-security"), MappingKind.SPLIT,
))
registry.add_mapping(CategoryMapping(
    "v1", "v2", "cooperation", ("cooperation",), MappingKind.ONE_TO_ONE,
))
```

启用前可以先做类别层面的盘点：`registry.coverage_between("v1", "v2")` 返回
`mapped`、`split`、`unmapped` 三个清单，说明哪些历史类别可直接投影、哪些
需要逐条复核。

## 3. 对拆分观察做逐条复核

```python
from signal_lab import Observation, Reclassification

observations = [
    Observation("o-1", "desk-1", date(2026, 11, 1), "security", 4,
                taxonomy_version="v1"),
    Observation("o-2", "desk-2", date(2026, 11, 8), "security", 3,
                taxonomy_version="v1"),
]

# 只有证据充分的 o-1 能判定子类；o-2 材料不足，不做复核就保持未决
decisions = [
    Reclassification("o-1", "v2", "military-security",
                     "researcher-a", date(2026, 6, 15)),
]

result = registry.reinterpret(observations, "v2", reclassifications=decisions)
```

`result.resolved` 中 o-1 的状态为 `reinterpreted`；`result.unresolved` 中
o-2 的原因为 `split-requires-review`，候选子类一并保留，`result.notes()`
给出可读说明。复核记录若写错观察编号或适用版本，`reinterpret` 会直接抛出
`TaxonomyError`，避免记录静默失效。

## 4. 在目标口径下比较周期并生成报告

```python
from signal_lab import compare_periods, create_report

comparison = compare_periods(
    observations, (2026, 11), (2026, 12),
    taxonomy=registry, target_version="v2",
    reclassifications=decisions,
)

measures = {item.code: item.end_value for item in comparison.categories}
report = create_report(
    "r-1", "月度比较", "2026-11", "2026-12",
    [obs.source_id for obs in observations],
    measures,
    taxonomy_version="v2",
    coverage_notes=comparison.notes,
)
```

`PeriodComparison` 的关键约束：

- 未决观察不计入任何类别，单独列在 `unresolved`，并给出两个周期各自的缺口
  数值；读者看到的子类趋势是**下限**而不是被补齐的平滑曲线；
- 新类别（如 `climate`）在历史周期为零，不会被旧观察凑数；
- `coverage` 给出每个周期的已解决/未决计数与占比，便于判断比较的可靠程度；
- 报告钉住 `v2` 并快照缺口说明。之后再启用 `v3` 时，旧报告仍按 `v2` 复现，
  新报告按 `v3` 生成，两者差异可以通过映射链与未决清单解释。
