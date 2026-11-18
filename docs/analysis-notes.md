# 分析口径

当前项目的观察重点是 taxonomy version and trend。来源信息、观测记录与分析输出分别保存；报告保留生成时使用的来源标识，便于研究人员回看数据范围。输入观测的数值含义由调用方提供，项目不将报道计数解释为受众态度或传播因果。

## 分类口径是版本化的

每条 `Observation` 除 topic 外还带有 `taxonomy_version`，说明该 topic 是依据哪一版分类定义录入的；原始记录不可变。口径调整通过 `TaxonomyVersion` 与相邻版本之间的 `CategoryMapping` 显式登记，而不是改写历史标签：

- `one_to_one`：改名或等价迁移，类别级映射即可可靠投影；
- `merge`：多个旧类别合并为一个新类别；
- `split`：旧类别拆为多个候选子类。映射只声明候选范围，观察级归属必须由研究人员通过 `Reclassification` 逐条复核（含决策人与日期）；材料不足的观察保持“未决”，**不会自动并入最接近的子类来维持表面完整的序列**；
- `retired`：类别停用，无可靠新口径对应。

历史遗留观察若缺少 `taxonomy_version`，同样按未决处理（原因 `missing-source-version`），而不是猜测它属于哪个现行类别。

## 比较与报告如何使用口径

- `compare_periods` 在传入 `taxonomy` 与 `target_version` 后，先把观察投影到目标口径再聚合，返回 `PeriodComparison`：类别数值、未决观察分组（不计入任何类别）、各周期覆盖率，以及说明缺口影响的 `notes`（拆分造成的缺口会提示相关子类的对比值只是下限）。
- 不传口径参数时保留按裸 topic 聚合的旧行为，仅适用于口径单一且标签含义未变的场景。
- `AnalysisReport` 通过 `taxonomy_version` 钉住生成时的口径，并快照 `coverage_notes`。注册表保留全部历史版本，因此新报告使用新口径、旧报告仍可按其原版本复现，两类报告之间的差异可以用映射与未决清单解释。
