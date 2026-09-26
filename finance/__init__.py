"""Financial statement detection and source-linked analysis."""

from finance.common_size import CommonSizeResult, calculate_common_size
from finance.detection import (
    DEFAULT_RULES,
    DetectionEvidence,
    StatementDetection,
    StatementRule,
    detect_statements,
)
from finance.horizontal import (
    GROWTH_DEFINITIONS,
    GrowthDefinition,
    HorizontalResult,
    calculate_horizontal,
)
from finance.ratio_registry import FORMULAS, RatioFormula
from finance.ratios import MetricInput, MetricResult, MetricWarning, calculate_ratios

__all__ = [
    "CommonSizeResult",
    "DEFAULT_RULES",
    "DetectionEvidence",
    "FORMULAS",
    "GROWTH_DEFINITIONS",
    "GrowthDefinition",
    "HorizontalResult",
    "MetricInput",
    "MetricResult",
    "MetricWarning",
    "RatioFormula",
    "StatementDetection",
    "StatementRule",
    "calculate_common_size",
    "calculate_horizontal",
    "calculate_ratios",
    "detect_statements",
]
