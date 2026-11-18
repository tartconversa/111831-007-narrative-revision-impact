"""分类口径的版本化与跨版本映射。

观察记录保存的是录入时的分类代码（topic）与来源口径版本
（Observation.taxonomy_version）。口径升级时，本模块通过显式登记的
CategoryMapping 把历史观察投影到新版本，而不是改写原始记录：

- one_to_one / merge：类别级映射即可可靠投影；
- split：只登记候选子类，必须有逐条复核结论（Reclassification）才能落类，
  材料不足的观察保持“未决”，绝不自动并入最接近的子类；
- retired / 缺少映射 / 缺少来源版本：同样保持未决。

未决观察由分析层汇总后单独披露，读者可以据此判断缺口对趋势比较的影响。
"""

from dataclasses import dataclass
from types import MappingProxyType

from .records import Observation


class TaxonomyError(ValueError):
    """口径版本、映射或重新分类记录不合法时抛出。"""


class MappingKind:
    ONE_TO_ONE = "one_to_one"
    MERGE = "merge"
    SPLIT = "split"
    RETIRED = "retired"


# UnresolvedObservation.reason 的取值
REASON_MISSING_SOURCE_VERSION = "missing-source-version"
REASON_UNKNOWN_CATEGORY = "unknown-category"
REASON_NO_MAPPING = "no-mapping"
REASON_RETIRED = "retired"
REASON_SPLIT_REQUIRES_REVIEW = "split-requires-review"


@dataclass(frozen=True)
class Category:
    code: str
    label: str
    definition: str = ""


@dataclass(frozen=True)
class TaxonomyVersion:
    """某一版生效的分类定义。"""

    version_id: str
    effective_from: object  # datetime.date
    categories: dict
    note: str = ""

    def __post_init__(self):
        categories = dict(self.categories)
        if not categories:
            raise TaxonomyError(f"口径版本 {self.version_id} 至少要包含一个类别")
        object.__setattr__(self, "categories", MappingProxyType(categories))


@dataclass(frozen=True)
class CategoryMapping:
    """相邻两个口径版本之间，单个旧类别的去向。

    new_codes 为空表示停用（retired）；单个表示改名或合并；两个及以上表示
    拆分。拆分只声明候选子类，观察级归属由 Reclassification 决定。
    """

    from_version: str
    to_version: str
    old_code: str
    new_codes: tuple = ()
    kind: str = MappingKind.ONE_TO_ONE
    note: str = ""

    def __post_init__(self):
        object.__setattr__(self, "new_codes", tuple(self.new_codes))


@dataclass(frozen=True)
class Reclassification:
    """研究人员对单条历史观察的逐条复核结论（不可由系统推断代替）。"""

    observation_id: str
    applies_at_version: str  # 拆分发生时新生效的口径版本
    new_code: str
    decided_by: str
    decided_on: object  # datetime.date
    note: str = ""


@dataclass(frozen=True)
class ResolvedObservation:
    observation: Observation
    code: str
    # direct：本就是目标口径下录入；carried：经 one_to_one/merge 投影；
    # reinterpreted：拆分后经逐条复核重新归类
    status: str
    applied_reclassification: object = None  # Reclassification | None


@dataclass(frozen=True)
class UnresolvedObservation:
    observation: Observation
    reason: str
    boundary_version: object  # 卡住时的新生效版本；str | None
    candidate_codes: tuple


@dataclass(frozen=True)
class ReinterpretationResult:
    target_version: str
    resolved: tuple
    unresolved: tuple

    def counts(self):
        return {
            "resolved": len(self.resolved),
            "unresolved": len(self.unresolved),
            "reinterpreted": sum(
                1 for item in self.resolved if item.status == "reinterpreted"
            ),
        }

    def notes(self):
        """逐条给出未决原因，便于在启用新口径时说明影响范围。"""
        lines = []
        for item in self.unresolved:
            obs = item.observation
            if item.reason == REASON_SPLIT_REQUIRES_REVIEW:
                lines.append(
                    f"观察 {obs.observation_id}（原分类 {obs.topic}，口径 "
                    f"{obs.taxonomy_version}）在 {item.boundary_version} 拆分为 "
                    f"{'、'.join(item.candidate_codes)}，现有材料不足以判定子类，"
                    f"未归入目标口径 {self.target_version} 的任何类别。"
                )
            elif item.reason == REASON_RETIRED:
                lines.append(
                    f"观察 {obs.observation_id} 的原分类 {obs.topic} 在 "
                    f"{item.boundary_version} 停用，无可靠的新口径对应。"
                )
            elif item.reason == REASON_NO_MAPPING:
                lines.append(
                    f"观察 {obs.observation_id} 的原分类 {obs.topic} 在 "
                    f"{item.boundary_version} 没有登记映射，无法可靠投影。"
                )
            elif item.reason == REASON_MISSING_SOURCE_VERSION:
                lines.append(
                    f"观察 {obs.observation_id} 缺少来源口径版本，无法在 "
                    f"{self.target_version} 口径下定位，未参与汇总。"
                )
            else:
                lines.append(
                    f"观察 {obs.observation_id} 的分类代码 {obs.topic} 在其登记"
                    f"口径中不存在，未参与汇总。"
                )
        return tuple(lines)


class TaxonomyRegistry:
    """保存全部历史口径版本与相邻版本之间的映射。"""

    def __init__(self):
        self._versions = {}
        self._mappings = {}

    def add_version(self, version):
        if version.version_id in self._versions:
            raise TaxonomyError(f"口径版本 {version.version_id} 已存在")
        self._versions[version.version_id] = version

    def add_mapping(self, mapping):
        if mapping.from_version not in self._versions:
            raise TaxonomyError(f"未知的来源口径版本：{mapping.from_version}")
        if mapping.to_version not in self._versions:
            raise TaxonomyError(f"未知的目标口径版本：{mapping.to_version}")
        ordered = self._ordered_versions()
        position = {version.version_id: i for i, version in enumerate(ordered)}
        if position[mapping.to_version] != position[mapping.from_version] + 1:
            raise TaxonomyError(
                f"映射只能登记在相邻生效的版本之间："
                f"{mapping.from_version} -> {mapping.to_version}"
            )
        if mapping.old_code not in self._versions[mapping.from_version].categories:
            raise TaxonomyError(
                f"旧类别 {mapping.old_code} 不存在于口径 {mapping.from_version}"
            )
        target_categories = self._versions[mapping.to_version].categories
        for code in mapping.new_codes:
            if code not in target_categories:
                raise TaxonomyError(
                    f"新类别 {code} 不存在于口径 {mapping.to_version}"
                )
        self._validate_cardinality(mapping)
        key = (mapping.from_version, mapping.old_code)
        if key in self._mappings:
            raise TaxonomyError(
                f"类别 {mapping.old_code} 在 {mapping.from_version} -> "
                f"{mapping.to_version} 已登记映射"
            )
        self._mappings[key] = mapping

    @staticmethod
    def _validate_cardinality(mapping):
        count = len(mapping.new_codes)
        kind = mapping.kind
        if kind in (MappingKind.ONE_TO_ONE, MappingKind.MERGE) and count != 1:
            raise TaxonomyError(f"{kind} 映射必须恰好指向一个新类别")
        if kind == MappingKind.SPLIT and count < 2:
            raise TaxonomyError("split 映射必须至少列出两个候选子类")
        if kind == MappingKind.RETIRED and count != 0:
            raise TaxonomyError("retired 映射不应指向任何新类别")
        if kind not in (
            MappingKind.ONE_TO_ONE,
            MappingKind.MERGE,
            MappingKind.SPLIT,
            MappingKind.RETIRED,
        ):
            raise TaxonomyError(f"未知的映射类型：{kind}")

    def get_version(self, version_id):
        return self._versions.get(version_id)

    def _ordered_versions(self):
        return tuple(
            sorted(
                self._versions.values(),
                key=lambda version: (version.effective_from, version.version_id),
            )
        )

    def _chain(self, source_version_id, target_version_id):
        if source_version_id not in self._versions:
            raise TaxonomyError(f"未知的来源口径版本：{source_version_id}")
        if target_version_id not in self._versions:
            raise TaxonomyError(f"未知的目标口径版本：{target_version_id}")
        ordered = self._ordered_versions()
        position = {version.version_id: i for i, version in enumerate(ordered)}
        start, stop = position[source_version_id], position[target_version_id]
        if start > stop:
            raise TaxonomyError(
                f"不能把较新口径 {source_version_id} 的观察反向投影到旧口径 "
                f"{target_version_id}；旧报告应按其钉住的原口径重新生成。"
            )
        return ordered[start : stop + 1]

    def reinterpret(self, observations, target_version_id, reclassifications=()):
        """把观察投影到目标口径，返回已解决与未决两个清单。

        重新分类记录按 (observation_id, applies_at_version) 索引；若某条记录
        没有被任何拆分场景使用，说明观察编号或版本对不上，直接报错而不是静默
        忽略。
        """
        if target_version_id not in self._versions:
            raise TaxonomyError(f"未知的目标口径版本：{target_version_id}")
        overrides = {}
        for item in reclassifications:
            key = (item.observation_id, item.applies_at_version)
            if key in overrides:
                raise TaxonomyError(f"观察 {item.observation_id} 存在重复的复核结论")
            overrides[key] = item

        resolved, unresolved, used = [], [], set()
        for observation in observations:
            outcome = self._resolve_one(
                observation, target_version_id, overrides, used
            )
            if isinstance(outcome, ResolvedObservation):
                resolved.append(outcome)
            else:
                unresolved.append(outcome)

        unused = sorted(set(overrides) - used)
        if unused:
            raise TaxonomyError(
                f"以下重新分类记录未被使用（观察编号或适用版本不匹配）：{unused}"
            )
        return ReinterpretationResult(
            target_version_id, tuple(resolved), tuple(unresolved)
        )

    def _resolve_one(self, observation, target_version_id, overrides, used_overrides):
        source_id = observation.taxonomy_version
        if source_id is None:
            return UnresolvedObservation(
                observation, REASON_MISSING_SOURCE_VERSION, None, ()
            )
        chain = self._chain(source_id, target_version_id)
        current_code = observation.topic
        if source_id == target_version_id:
            if current_code not in self._versions[source_id].categories:
                return UnresolvedObservation(
                    observation, REASON_UNKNOWN_CATEGORY, None, ()
                )
            return ResolvedObservation(observation, current_code, "direct", None)

        status, applied = "carried", None
        for left, right in zip(chain, chain[1:]):
            if current_code not in left.categories:
                return UnresolvedObservation(
                    observation, REASON_UNKNOWN_CATEGORY, left.version_id, ()
                )
            mapping = self._mappings.get((left.version_id, current_code))
            if mapping is None:
                return UnresolvedObservation(
                    observation, REASON_NO_MAPPING, right.version_id, ()
                )
            if mapping.kind == MappingKind.RETIRED:
                return UnresolvedObservation(
                    observation, REASON_RETIRED, right.version_id, ()
                )
            if mapping.kind == MappingKind.SPLIT:
                override = overrides.get(
                    (observation.observation_id, right.version_id)
                )
                if override is None:
                    return UnresolvedObservation(
                        observation,
                        REASON_SPLIT_REQUIRES_REVIEW,
                        right.version_id,
                        mapping.new_codes,
                    )
                if override.new_code not in mapping.new_codes:
                    raise TaxonomyError(
                        f"观察 {observation.observation_id} 的复核结论 "
                        f"{override.new_code} 不在候选子类 "
                        f"{mapping.new_codes} 之内"
                    )
                current_code = override.new_code
                status, applied = "reinterpreted", override
                used_overrides.add(
                    (observation.observation_id, right.version_id)
                )
            else:
                current_code = mapping.new_codes[0]

        if current_code not in self._versions[target_version_id].categories:
            return UnresolvedObservation(
                observation, REASON_UNKNOWN_CATEGORY, target_version_id, ()
            )
        return ResolvedObservation(observation, current_code, status, applied)

    def coverage_between(self, source_version_id, target_version_id):
        """类别层面的映射盘点（启用新口径前的规划视图）。

        返回 mapped（旧代码 -> 目标代码）、split（旧代码 -> 候选子类）、
        unmapped（停用或缺少映射的旧代码）三个清单。观察层面的实际覆盖以
        reinterpret() 的结果为准。
        """
        chain = self._chain(source_version_id, target_version_id)
        mapped, split, unmapped = [], [], []
        for old_code in chain[0].categories:
            current_code, covered = old_code, True
            for left, right in zip(chain, chain[1:]):
                mapping = self._mappings.get((left.version_id, current_code))
                if mapping is None or mapping.kind == MappingKind.RETIRED:
                    unmapped.append(old_code)
                    covered = False
                    break
                if mapping.kind == MappingKind.SPLIT:
                    split.append((old_code, mapping.new_codes))
                    covered = False
                    break
                current_code = mapping.new_codes[0]
            if covered:
                mapped.append((old_code, current_code))
        return {
            "mapped": tuple(mapped),
            "split": tuple(split),
            "unmapped": tuple(unmapped),
        }
