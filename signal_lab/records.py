from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Source:
    source_id: str
    region: str
    language: str
    active: bool = True


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_id: str
    observed_on: date
    topic: str
    value: float
    region: str = "global"
    # topic 录入时所依据的分类口径版本；历史遗留数据为 None，
    # 投影到新口径时按“来源版本缺失”保留为未决，而不是猜测归类。
    taxonomy_version: str = None
