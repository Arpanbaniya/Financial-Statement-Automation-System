"""Financial statement detection and source-linked analysis."""

from finance.cash_flow import (
    CashFlowResult,
    CashFlowTrend,
    calculate_cash_flow,
    compare_cash_flow,
)
from finance.commentary import CommentaryFinding, generate_commentary
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
from finance.working_capital import WorkingCapitalResult, calculate_working_capital

__all__ = [
    "CommonSizeResult",
    "CashFlowResult",
    "CashFlowTrend",
    "CommentaryFinding",
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
    "WorkingCapitalResult",
    "calculate_common_size",
    "calculate_cash_flow",
    "calculate_horizontal",
    "calculate_ratios",
    "calculate_working_capital",
    "compare_cash_flow",
    "detect_statements",
    "generate_commentary",
]
