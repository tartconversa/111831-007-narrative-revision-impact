from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class AnalysisReport:
    report_id: str
    title: str
    period_start: str
    period_end: str
    source_ids: tuple[str, ...]
    measures: dict[str, float]
    created_at: str
    # 生成报告时钉住的分类口径版本；旧报告保留其原版本，新报告使用新版本。
    taxonomy_version: str = None
    # 生成时快照的口径缺口说明（如拆分后无法判定子类的观察），
    # 与报告绑定，后续口径继续演进也不改变旧报告的解释。
    coverage_notes: tuple[str, ...] = ()


def create_report(report_id, title, period_start, period_end, source_ids,
                  measures, taxonomy_version=None, coverage_notes=()):
    return AnalysisReport(
        report_id=report_id, title=title, period_start=period_start, period_end=period_end,
        source_ids=tuple(sorted(set(source_ids))), measures=dict(measures),
        created_at=datetime.now(timezone.utc).isoformat(),
        taxonomy_version=taxonomy_version,
        coverage_notes=tuple(coverage_notes),
    )
