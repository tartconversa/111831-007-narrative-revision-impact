"""跨周期趋势比较。

两条路径：

- 不传 taxonomy / target_version：保留按观察自带 topic 裸聚合的旧行为，
  适用于口径单一且调用方自行保证标签一致的场景；
- 传入 TaxonomyRegistry 与 target_version：先把观察投影到目标口径再聚合。
  无法可靠映射的观察不进入任何类别，单独列入 unresolved，并附上面向读者的
  缺口说明——分类拆分后材料不足的子类不会被自动凑数，趋势曲线如实反映缺口。
"""

from collections import defaultdict
from dataclasses import dataclass

from .taxonomy import REASON_SPLIT_REQUIRES_REVIEW


@dataclass(frozen=True)
class CategoryComparison:
    code: str
    start_value: float
    end_value: float
    start_sources: int
    end_sources: int
    # direct：两个周期都有目标口径原生数据；partial：部分数值来自跨口径投影
    history_status: str


@dataclass(frozen=True)
class UnresolvedGroup:
    code: str  # 未决观察在其来源口径下的原 topic
    reason: str
    boundary_version: object
    candidate_codes: tuple
    start_value: float
    end_value: float
    observation_ids: tuple


@dataclass(frozen=True)
class PeriodComparison:
    target_version: str
    categories: tuple  # tuple[CategoryComparison, ...]，按类别代码排序
    unresolved: tuple  # tuple[UnresolvedGroup, ...]
    coverage: dict  # start / end 各自的 resolved、unresolved 计数与占比
    notes: tuple  # 面向读者的缺口说明


def compare_periods(observations, start, end, *, region=None,
                    taxonomy=None, target_version=None, reclassifications=()):
    """汇总两个周期内的观察值与来源覆盖数量。"""
    if taxonomy is None and target_version is None:
        return _compare_raw(observations, start, end, region=region)
    if taxonomy is None or target_version is None:
        raise ValueError(
            "口径模式下必须同时提供 taxonomy（TaxonomyRegistry）与 target_version"
        )
    return _compare_under_taxonomy(
        observations, start, end, region, taxonomy,
        target_version, tuple(reclassifications),
    )


def _in_slot(observations, start, end, region):
    periods = ((start[0], start[1]), (end[0], end[1]))
    selected = []
    for observation in observations:
        if region is not None and observation.region != region:
            continue
        key = (observation.observed_on.year, observation.observed_on.month)
        if key not in periods:
            continue
        selected.append((periods.index(key), observation))
    return selected


def _compare_raw(observations, start, end, *, region=None):
    """旧行为：直接按当前 topic 标签聚合，不做任何口径投影。"""
    totals = [defaultdict(float), defaultdict(float)]
    sources = [defaultdict(set), defaultdict(set)]
    for slot, observation in _in_slot(observations, start, end, region):
        totals[slot][observation.topic] += observation.value
        sources[slot][observation.topic].add(observation.source_id)
    topics = sorted(set(totals[0]) | set(totals[1]))
    return {topic: {
        "start_value": totals[0][topic], "end_value": totals[1][topic],
        "start_sources": len(sources[0][topic]), "end_sources": len(sources[1][topic]),
    } for topic in topics}


def _compare_under_taxonomy(observations, start, end, region,
                            taxonomy, target_version, reclassifications):
    in_slots = _in_slot(observations, start, end, region)
    selected = tuple(observation for _, observation in in_slots)
    result = taxonomy.reinterpret(
        selected, target_version, reclassifications=reclassifications
    )

    totals = [defaultdict(float), defaultdict(float)]
    sources = [defaultdict(set), defaultdict(set)]
    seen_native = [set(), set()]
    slot_of = {
        observation.observation_id: slot for slot, observation in in_slots
    }
    for item in result.resolved:
        slot = slot_of[item.observation.observation_id]
        totals[slot][item.code] += item.observation.value
        sources[slot][item.code].add(item.observation.source_id)
        if item.status == "direct":
            seen_native[slot].add(item.code)

    target_categories = taxonomy.get_version(target_version).categories
    categories = []
    for code in sorted(target_categories):
        native_both = code in seen_native[0] and code in seen_native[1]
        categories.append(CategoryComparison(
            code=code,
            start_value=totals[0][code],
            end_value=totals[1][code],
            start_sources=len(sources[0][code]),
            end_sources=len(sources[1][code]),
            history_status="direct" if native_both else "partial",
        ))

    unresolved_groups = _group_unresolved(
        result.unresolved, slot_of, target_version
    )
    coverage = _coverage_summary(result.resolved, result.unresolved, slot_of)
    notes = _gap_notes(unresolved_groups, target_version)
    return PeriodComparison(
        target_version=target_version,
        categories=tuple(categories),
        unresolved=tuple(unresolved_groups),
        coverage=coverage,
        notes=notes,
    )


def _group_unresolved(unresolved, slot_of, target_version):
    buckets = {}
    for item in unresolved:
        key = (
            item.observation.topic,
            item.reason,
            item.boundary_version,
            item.candidate_codes,
        )
        group = buckets.setdefault(key, {
            "values": [0.0, 0.0], "ids": [],
        })
        slot = slot_of[item.observation.observation_id]
        group["values"][slot] += item.observation.value
        group["ids"].append(item.observation.observation_id)
    groups = []
    for (code, reason, boundary, candidates), data in sorted(buckets.items()):
        groups.append(UnresolvedGroup(
            code=code,
            reason=reason,
            boundary_version=boundary,
            candidate_codes=candidates,
            start_value=data["values"][0],
            end_value=data["values"][1],
            observation_ids=tuple(sorted(data["ids"])),
        ))
    return groups


def _coverage_summary(resolved, unresolved, slot_of):
    coverage = {}
    for label, slot in (("start", 0), ("end", 1)):
        resolved_count = sum(
            1 for item in resolved
            if slot_of[item.observation.observation_id] == slot
        )
        unresolved_count = sum(
            1 for item in unresolved
            if slot_of[item.observation.observation_id] == slot
        )
        total = resolved_count + unresolved_count
        coverage[label] = {
            "resolved": resolved_count,
            "unresolved": unresolved_count,
            "resolved_share": None if total == 0 else resolved_count / total,
        }
    return coverage


def _gap_notes(unresolved_groups, target_version):
    notes = []
    for group in unresolved_groups:
        if group.reason == REASON_SPLIT_REQUIRES_REVIEW:
            notes.append(
                f"原分类 {group.code} 在 {group.boundary_version} 拆分为 "
                f"{'、'.join(group.candidate_codes)}；{len(group.observation_ids)} "
                f"条观察因材料不足无法判定子类，未计入目标口径 {target_version} "
                f"的任何类别（起始周期缺口 {group.start_value}，结束周期缺口 "
                f"{group.end_value}），相关子类的对比值为下限。"
            )
        else:
            notes.append(
                f"原分类 {group.code} 有 {len(group.observation_ids)} 条观察无法"
                f"可靠投影到目标口径 {target_version}（原因：{group.reason}；"
                f"起始周期缺口 {group.start_value}，结束周期缺口 "
                f"{group.end_value}），未计入任何类别。"
            )
    return tuple(notes)
