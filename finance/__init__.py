"""Financial statement detection and source-linked ratio calculations."""

from finance.detection import (
    DEFAULT_RULES,
    DetectionEvidence,
    StatementDetection,
    StatementRule,
    detect_statements,
)
from finance.ratio_registry import FORMULAS, RatioFormula
from finance.ratios import MetricInput, MetricResult, MetricWarning, calculate_ratios

__all__ = [
    "DEFAULT_RULES",
    "DetectionEvidence",
    "FORMULAS",
    "MetricInput",
    "MetricResult",
    "MetricWarning",
    "RatioFormula",
    "StatementDetection",
    "StatementRule",
    "calculate_ratios",
    "detect_statements",
]
