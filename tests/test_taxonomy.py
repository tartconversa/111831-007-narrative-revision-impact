import unittest
from datetime import date

from signal_lab.analysis import PeriodComparison, compare_periods
from signal_lab.records import Observation
from signal_lab.report import create_report
from signal_lab.taxonomy import (
    Category,
    CategoryMapping,
    MappingKind,
    Reclassification,
    REASON_MISSING_SOURCE_VERSION,
    REASON_NO_MAPPING,
    REASON_RETIRED,
    REASON_SPLIT_REQUIRES_REVIEW,
    TaxonomyError,
    TaxonomyRegistry,
    TaxonomyVersion,
)


def _categories(codes):
    return {code: Category(code, code) for code in codes}


def build_registry():
    """v1 -> v2 拆分与停用；v2 -> v3 改名与合并。"""
    registry = TaxonomyRegistry()
    v1 = TaxonomyVersion(
        "v1", date(2026, 1, 1),
        _categories(["security", "cooperation", "culture"]),
    )
    v2 = TaxonomyVersion(
        "v2", date(2026, 6, 1),
        _categories([
            "military-security", "economic-security", "cooperation", "climate",
        ]),
    )
    v3 = TaxonomyVersion(
        "v3", date(2027, 1, 1),
        _categories([
            "military-security", "economic-security", "partnership", "climate",
        ]),
    )
    registry.add_version(v1)
    registry.add_version(v2)
    registry.add_version(v3)
    registry.add_mapping(CategoryMapping(
        "v1", "v2", "security",
        ("military-security", "economic-security"), MappingKind.SPLIT,
    ))
    registry.add_mapping(CategoryMapping(
        "v1", "v2", "cooperation", ("cooperation",), MappingKind.ONE_TO_ONE,
    ))
    registry.add_mapping(CategoryMapping(
        "v1", "v2", "culture", (), MappingKind.RETIRED,
    ))
    registry.add_mapping(CategoryMapping(
        "v2", "v3", "military-security",
        ("military-security",), MappingKind.ONE_TO_ONE,
    ))
    registry.add_mapping(CategoryMapping(
        "v2", "v3", "cooperation", ("partnership",), MappingKind.ONE_TO_ONE,
    ))
    return registry


def build_observations():
    return [
        # 拆分后经逐条复核可落类
        Observation("o-1", "desk-1", date(2026, 11, 1), "security", 4,
                    taxonomy_version="v1"),
        # 拆分后无复核材料，必须保持未决
        Observation("o-2", "desk-2", date(2026, 11, 8), "security", 3,
                    taxonomy_version="v1"),
        # one_to_one 直接投影
        Observation("o-3", "desk-1", date(2026, 11, 3), "cooperation", 5,
                    taxonomy_version="v1"),
        # 停用类别
        Observation("o-4", "desk-3", date(2026, 11, 5), "culture", 2,
                    taxonomy_version="v1"),
        # 历史遗留数据，没有来源口径版本
        Observation("o-5", "desk-2", date(2026, 11, 9), "security", 1,
                    taxonomy_version=None),
        # 目标口径下的原生观察
        Observation("o-6", "desk-1", date(2026, 12, 2), "military-security", 6,
                    taxonomy_version="v2"),
        Observation("o-7", "desk-4", date(2026, 12, 4), "cooperation", 7,
                    taxonomy_version="v2"),
    ]


class TaxonomyResolutionTests(unittest.TestCase):
    def test_split_without_reclassification_stays_unresolved(self):
        registry = build_registry()
        result = registry.reinterpret(build_observations(), "v2")

        by_id = {item.observation.observation_id: item for item in result.resolved}
        unresolved_ids = {item.observation.observation_id for item in result.unresolved}
        self.assertNotIn("o-2", by_id)
        self.assertIn("o-2", unresolved_ids)
        item = next(x for x in result.unresolved
                    if x.observation.observation_id == "o-2")
        self.assertEqual(item.reason, REASON_SPLIT_REQUIRES_REVIEW)
        self.assertEqual(item.boundary_version, "v2")
        self.assertEqual(item.candidate_codes,
                         ("military-security", "economic-security"))

    def test_reclassification_resolves_split_observation(self):
        registry = build_registry()
        decision = Reclassification(
            "o-1", "v2", "economic-security",
            "researcher-a", date(2026, 6, 15),
        )
        result = registry.reinterpret(
            build_observations(), "v2", reclassifications=(decision,)
        )
        by_id = {item.observation.observation_id: item for item in result.resolved}
        self.assertEqual(by_id["o-1"].code, "economic-security")
        self.assertEqual(by_id["o-1"].status, "reinterpreted")
        self.assertIs(by_id["o-1"].applied_reclassification, decision)
        self.assertEqual(result.counts()["reinterpreted"], 1)

    def test_reclassification_outside_candidates_is_rejected(self):
        registry = build_registry()
        decision = Reclassification(
            "o-1", "v2", "cooperation",
            "researcher-a", date(2026, 6, 15),
        )
        with self.assertRaises(TaxonomyError):
            registry.reinterpret(
                build_observations(), "v2", reclassifications=(decision,)
            )

    def test_unused_reclassification_is_an_error(self):
        registry = build_registry()
        decision = Reclassification(
            "o-999", "v2", "military-security",
            "researcher-a", date(2026, 6, 15),
        )
        with self.assertRaises(TaxonomyError):
            registry.reinterpret(
                build_observations(), "v2", reclassifications=(decision,)
            )

    def test_retired_and_missing_version_are_unresolved(self):
        registry = build_registry()
        result = registry.reinterpret(build_observations(), "v2")
        reasons = {
            item.observation.observation_id: item.reason
            for item in result.unresolved
        }
        self.assertEqual(reasons["o-4"], REASON_RETIRED)
        self.assertEqual(reasons["o-5"], REASON_MISSING_SOURCE_VERSION)

    def test_chain_walks_multiple_versions(self):
        registry = build_registry()
        result = registry.reinterpret(build_observations(), "v3")
        by_id = {item.observation.observation_id: item for item in result.resolved}
        # v1 cooperation -> v2 cooperation -> v3 partnership
        self.assertEqual(by_id["o-3"].code, "partnership")
        self.assertEqual(by_id["o-3"].status, "carried")
        # v2 原生观察按 one_to_one 投影
        self.assertEqual(by_id["o-7"].code, "partnership")
        self.assertEqual(by_id["o-6"].code, "military-security")
        # 拆分缺口在链路中依然保留为未决
        unresolved_ids = {item.observation.observation_id for item in result.unresolved}
        self.assertIn("o-2", unresolved_ids)

    def test_backward_projection_is_rejected(self):
        registry = build_registry()
        with self.assertRaises(TaxonomyError):
            registry.reinterpret(
                [Observation("x", "d", date(2026, 12, 1),
                             "military-security", 1, taxonomy_version="v2")],
                "v1",
            )

    def test_unknown_category_in_source_version_is_unresolved(self):
        registry = build_registry()
        rows = [Observation("x", "d", date(2026, 11, 1), "ghost", 1,
                            taxonomy_version="v1")]
        result = registry.reinterpret(rows, "v2")
        self.assertEqual(len(result.resolved), 0)
        self.assertEqual(len(result.unresolved), 1)

    def test_mapping_without_registered_category_is_rejected(self):
        registry = TaxonomyRegistry()
        registry.add_version(TaxonomyVersion(
            "a", date(2026, 1, 1), _categories(["x"])))
        registry.add_version(TaxonomyVersion(
            "b", date(2026, 2, 1), _categories(["y"])))
        with self.assertRaises(TaxonomyError):
            registry.add_mapping(CategoryMapping(
                "a", "b", "missing", ("y",), MappingKind.ONE_TO_ONE))

    def test_split_mapping_requires_at_least_two_candidates(self):
        registry = TaxonomyRegistry()
        registry.add_version(TaxonomyVersion(
            "a", date(2026, 1, 1), _categories(["x"])))
        registry.add_version(TaxonomyVersion(
            "b", date(2026, 2, 1), _categories(["y"])))
        with self.assertRaises(TaxonomyError):
            registry.add_mapping(CategoryMapping(
                "a", "b", "x", ("y",), MappingKind.SPLIT))

    def test_mapping_only_between_adjacent_versions(self):
        registry = build_registry()
        with self.assertRaises(TaxonomyError):
            registry.add_mapping(CategoryMapping(
                "v1", "v3", "cooperation",
                ("partnership",), MappingKind.ONE_TO_ONE))

    def test_coverage_between_inventory(self):
        registry = build_registry()
        coverage = registry.coverage_between("v1", "v2")
        self.assertEqual(coverage["mapped"], (("cooperation", "cooperation"),))
        self.assertEqual(
            coverage["split"],
            (("security", ("military-security", "economic-security")),))
        self.assertEqual(coverage["unmapped"], ("culture",))

    def test_duplicate_version_is_rejected(self):
        registry = TaxonomyRegistry()
        version = TaxonomyVersion("a", date(2026, 1, 1), _categories(["x"]))
        registry.add_version(version)
        with self.assertRaises(TaxonomyError):
            registry.add_version(version)


class TaxonomyPeriodComparisonTests(unittest.TestCase):
    def test_comparison_aggregates_under_target_version_and_exposes_gaps(self):
        registry = build_registry()
        decision = Reclassification(
            "o-1", "v2", "military-security",
            "researcher-a", date(2026, 6, 15),
        )
        result = compare_periods(
            build_observations(), (2026, 11), (2026, 12),
            taxonomy=registry, target_version="v2",
            reclassifications=(decision,),
        )
        self.assertIsInstance(result, PeriodComparison)
        by_code = {item.code: item for item in result.categories}

        # o-1=4 经复核进入 military-security；o-6=6 为 v2 原生
        self.assertEqual(by_code["military-security"].start_value, 4)
        self.assertEqual(by_code["military-security"].end_value, 6)
        # o-2 未决，economic-security 起始周期没有可归入的观察
        self.assertEqual(by_code["economic-security"].start_value, 0)
        self.assertEqual(by_code["cooperation"].start_value, 5)
        self.assertEqual(by_code["cooperation"].end_value, 7)
        # 新增类别 climate 保留为零，而不是从历史观察凑数
        self.assertEqual(by_code["climate"].start_value, 0)
        self.assertEqual(by_code["climate"].end_value, 0)
        # military-security 起始周期仅含投影观察、结束周期为原生数据；
        # economic-security 两个周期都没有可归入的观察
        self.assertEqual(by_code["military-security"].history_status, "partial")
        self.assertEqual(by_code["economic-security"].history_status, "partial")

        reasons = {group.code: group for group in result.unresolved}
        self.assertEqual(reasons["security"].start_value, 3)
        self.assertEqual(reasons["security"].observation_ids, ("o-2",))
        self.assertEqual(reasons["culture"].reason, REASON_RETIRED)
        self.assertEqual(reasons["security"].reason, REASON_SPLIT_REQUIRES_REVIEW)

        self.assertEqual(result.coverage["start"]["resolved"], 2)
        self.assertEqual(result.coverage["start"]["unresolved"], 3)
        self.assertEqual(result.coverage["start"]["resolved_share"], 2 / 5)
        self.assertEqual(result.coverage["end"]["resolved"], 2)
        self.assertEqual(result.coverage["end"]["unresolved"], 0)
        self.assertEqual(result.coverage["end"]["resolved_share"], 1.0)

        joined = "\n".join(result.notes)
        self.assertIn("拆分为", joined)
        self.assertIn("military-security", joined)
        self.assertIn("下限", joined)

    def test_region_filter_applies_before_resolution(self):
        registry = build_registry()
        rows = [
            Observation("a", "d1", date(2026, 11, 1), "cooperation", 4,
                        region="europe", taxonomy_version="v1"),
            Observation("b", "d2", date(2026, 11, 2), "cooperation", 9,
                        region="asia", taxonomy_version="v1"),
        ]
        result = compare_periods(
            rows, (2026, 11), (2026, 12),
            region="asia", taxonomy=registry, target_version="v2",
        )
        by_code = {item.code: item for item in result.categories}
        self.assertEqual(by_code["cooperation"].start_value, 9)
        self.assertEqual(result.coverage["start"]["resolved"], 1)

    def test_direct_status_when_both_periods_have_native_observations(self):
        registry = build_registry()
        rows = [
            Observation("a", "d1", date(2026, 11, 1), "cooperation", 4,
                        taxonomy_version="v2"),
            Observation("b", "d2", date(2026, 12, 1), "cooperation", 6,
                        taxonomy_version="v2"),
        ]
        result = compare_periods(
            rows, (2026, 11), (2026, 12),
            taxonomy=registry, target_version="v2",
        )
        by_code = {item.code: item for item in result.categories}
        self.assertEqual(by_code["cooperation"].history_status, "direct")

    def test_legacy_path_keeps_raw_topic_aggregation(self):
        rows = [
            Observation("a", "desk-1", date(2026, 11, 1), "topic", 2),
            Observation("b", "desk-2", date(2026, 11, 8), "topic", 3),
        ]
        result = compare_periods(rows, (2026, 11), (2026, 11))
        self.assertEqual(result["topic"]["start_value"], 5)
        self.assertEqual(result["topic"]["start_sources"], 2)

    def test_partial_taxonomy_arguments_raise(self):
        registry = build_registry()
        with self.assertRaises(ValueError):
            compare_periods(
                build_observations(), (2026, 11), (2026, 12),
                taxonomy=registry,
            )
        with self.assertRaises(ValueError):
            compare_periods(
                build_observations(), (2026, 11), (2026, 12),
                target_version="v2",
            )


class ReportVersionTests(unittest.TestCase):
    def test_report_pins_taxonomy_version_and_gap_notes(self):
        report = create_report(
            "r-1", "月度比较", "2026-11", "2026-12", ["desk-1"],
            {"military-security": 10.0},
            taxonomy_version="v2",
            coverage_notes=("security 拆分后存在 1 条未决观察。",),
        )
        self.assertEqual(report.taxonomy_version, "v2")
        self.assertEqual(
            report.coverage_notes, ("security 拆分后存在 1 条未决观察。",)
        )

    def test_legacy_report_without_version_remains_valid(self):
        report = create_report(
            "r-0", "旧报告", "2026-09", "2026-10", ["desk-1"],
            {"security": 8.0},
        )
        self.assertIsNone(report.taxonomy_version)
        self.assertEqual(report.coverage_notes, ())
        # 旧报告引用的口径定义仍可从注册表取回
        registry = build_registry()
        self.assertIn("security", registry.get_version("v1").categories)


if __name__ == "__main__":
    unittest.main()
