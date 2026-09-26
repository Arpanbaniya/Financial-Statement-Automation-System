"""Keep reporting dates separate from fiscal labels and statement basis."""

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from normalization.amounts import NormalizationStatus, NormalizationWarning
from normalization.taxonomy import PeriodBasis, StatementType

PeriodType = Literal[
    "annual", "quarterly", "six_months", "nine_months", "other_duration", "instant"
]
_FY = re.compile(r"FY\s*(?P<year>\d{4})", re.IGNORECASE)
_QUARTER = re.compile(r"Q(?P<quarter>[1-4])\s*FY\s*(?P<year>\d{4})", re.IGNORECASE)
_DATE_TEXT = r"(?:\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
_RANGE = re.compile(
    rf"^\s*(?P<start>{_DATE_TEXT})\s+(?:to|through|-|–|—)\s+"
    rf"(?P<end>{_DATE_TEXT})\s*$",
    re.IGNORECASE,
)
_AS_OF = re.compile(rf"^\s*as\s+(?:of|at)\s+(?P<end>{_DATE_TEXT})\s*$", re.IGNORECASE)
_ENDED = re.compile(
    rf"^\s*(?:for\s+the\s+)?(?P<length>year|three\s+months|six\s+months|"
    rf"nine\s+months)\s+ended\s+(?P<end>{_DATE_TEXT})\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class NormalizedPeriod:
    original_label: str | None
    original_start: date | str | None
    original_end: date | str | None
    statement_type: StatementType
    period_basis: PeriodBasis
    period_type: PeriodType | None
    period_start: date | None
    period_end: date | None
    fiscal_year: int | None
    fiscal_quarter: int | None
    status: NormalizationStatus
    warnings: tuple[NormalizationWarning, ...]


def _parse_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("Period dates must be dates or date strings")
    for pattern in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(value.strip(), pattern).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized period date: {value}")


def _add_months(day: date, count: int) -> date:
    month_index = day.year * 12 + day.month - 1 + count
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _duration_type(start: date, end: date) -> PeriodType:
    for months, name in (
        (12, "annual"),
        (9, "nine_months"),
        (6, "six_months"),
        (3, "quarterly"),
    ):
        if _add_months(start, months) == end + timedelta(days=1):
            return name  # type: ignore[return-value]
    return "other_duration"


def _fiscal_dates(
    year: int, quarter: int | None, fiscal_year_end: tuple[int, int]
) -> tuple[date, date]:
    month, day = fiscal_year_end
    try:
        end = date(year, month, day)
        prior_end = date(year - 1, month, day)
    except ValueError as exc:
        raise ValueError("Fiscal year end must be a valid month and day") from exc
    start = prior_end + timedelta(days=1)
    if quarter is None:
        return start, end
    quarter_start = _add_months(start, 3 * (quarter - 1))
    quarter_end = _add_months(start, 3 * quarter) - timedelta(days=1)
    return quarter_start, quarter_end


def normalize_period(
    statement_type: StatementType,
    *,
    label: str | None = None,
    start: date | str | None = None,
    end: date | str | None = None,
    fiscal_year_end: tuple[int, int] | None = None,
) -> NormalizedPeriod:
    """Resolve explicit ranges, as-of dates, and FY/Q labels.

    An FY or quarter label alone cannot establish exact dates without a supplied
    fiscal-year end. Unresolved or contradictory dates require review.
    """
    if statement_type not in {
        "income_statement",
        "balance_sheet",
        "cash_flow_statement",
    }:
        raise ValueError("Unknown statement type")
    basis: PeriodBasis = "instant" if statement_type == "balance_sheet" else "duration"
    warnings: list[NormalizationWarning] = []
    try:
        period_start = _parse_date(start)
    except ValueError:
        period_start = None
        warnings.append(
            NormalizationWarning("invalid_period_start", "Start date needs review.")
        )
    try:
        period_end = _parse_date(end)
    except ValueError:
        period_end = None
        warnings.append(
            NormalizationWarning("invalid_period_end", "End date needs review.")
        )
    text = label.strip() if label else ""
    quarter_match = _QUARTER.fullmatch(text)
    year_match = _FY.fullmatch(text)
    fiscal_year = (
        int((quarter_match or year_match).group("year"))
        if quarter_match or year_match
        else None
    )
    fiscal_quarter = int(quarter_match.group("quarter")) if quarter_match else None
    if fiscal_year is not None and not 1900 <= fiscal_year <= 2200:
        warnings.append(
            NormalizationWarning(
                "invalid_fiscal_year", "Fiscal year is outside the supported range."
            )
        )

    range_match = _RANGE.fullmatch(text)
    as_of_match = _AS_OF.fullmatch(text)
    ended_match = _ENDED.fullmatch(text)
    if range_match:
        try:
            label_start = _parse_date(range_match.group("start"))
            label_end = _parse_date(range_match.group("end"))
        except ValueError:
            label_start = label_end = None
            warnings.append(
                NormalizationWarning("invalid_period_label", "Date range needs review.")
            )
        if (period_start and period_start != label_start) or (
            period_end and period_end != label_end
        ):
            warnings.append(
                NormalizationWarning(
                    "period_conflict", "Dates disagree with the source label."
                )
            )
        period_start = period_start or label_start
        period_end = period_end or label_end
    elif as_of_match:
        try:
            label_end = _parse_date(as_of_match.group("end"))
        except ValueError:
            label_end = None
            warnings.append(
                NormalizationWarning("invalid_period_label", "As-of date needs review.")
            )
        if period_end and period_end != label_end:
            warnings.append(
                NormalizationWarning(
                    "period_conflict", "Date disagrees with the source label."
                )
            )
        period_end = period_end or label_end
    elif ended_match:
        try:
            label_end = _parse_date(ended_match.group("end"))
        except ValueError:
            label_end = None
            warnings.append(
                NormalizationWarning("invalid_period_label", "End date needs review.")
            )
        if label_end:
            months = {"year": 12, "three months": 3, "six months": 6, "nine months": 9}[
                " ".join(ended_match.group("length").casefold().split())
            ]
            label_start = _add_months(label_end + timedelta(days=1), -months)
            if (period_start and period_start != label_start) or (
                period_end and period_end != label_end
            ):
                warnings.append(
                    NormalizationWarning(
                        "period_conflict", "Dates disagree with the source label."
                    )
                )
            period_start = period_start or label_start
            period_end = period_end or label_end
    elif fiscal_year is not None and fiscal_year_end is not None:
        fy_start, fy_end = _fiscal_dates(fiscal_year, fiscal_quarter, fiscal_year_end)
        if (period_start and period_start != fy_start) or (
            period_end and period_end != fy_end
        ):
            warnings.append(
                NormalizationWarning(
                    "period_conflict", "Dates disagree with the fiscal label."
                )
            )
        if basis == "duration":
            period_start = period_start or fy_start
        period_end = period_end or fy_end

    if period_end is None:
        warnings.append(
            NormalizationWarning(
                "missing_period_end", "Reporting end date needs review."
            )
        )
    if period_start and period_end and period_start > period_end:
        warnings.append(
            NormalizationWarning(
                "invalid_period_range", "Start date is after end date."
            )
        )
    if basis == "instant":
        period_type: PeriodType | None = "instant" if period_end else None
        if period_start:
            warnings.append(
                NormalizationWarning(
                    "basis_conflict",
                    "Balance sheet requires an as-of date, not a range.",
                )
            )
        if (
            fiscal_quarter is not None
            and fiscal_year_end is None
            and period_end is None
        ):
            warnings.append(
                NormalizationWarning(
                    "missing_fiscal_calendar", "Quarter needs a fiscal calendar."
                )
            )
    else:
        period_type = (
            _duration_type(period_start, period_end)
            if period_start and period_end and period_start <= period_end
            else None
        )
        if period_start is None:
            warnings.append(
                NormalizationWarning(
                    "missing_period_start", "Duration start date needs review."
                )
            )
        if as_of_match:
            warnings.append(
                NormalizationWarning(
                    "basis_conflict", "A duration statement needs a date range."
                )
            )
    if fiscal_year is not None and fiscal_year_end is None and period_end is None:
        warnings.append(
            NormalizationWarning(
                "missing_fiscal_calendar",
                "Fiscal label needs a fiscal calendar or explicit dates.",
            )
        )
    if fiscal_year is None and period_end is not None:
        fiscal_year = period_end.year
    if fiscal_quarter is not None and period_type not in {"quarterly", "instant", None}:
        warnings.append(
            NormalizationWarning(
                "quarter_conflict", "Quarter label does not match the date range."
            )
        )
    if year_match and period_type not in {"annual", "instant", None}:
        warnings.append(
            NormalizationWarning(
                "fiscal_label_conflict",
                "Fiscal year label does not match the date range.",
            )
        )
    return NormalizedPeriod(
        original_label=label,
        original_start=start,
        original_end=end,
        statement_type=statement_type,
        period_basis=basis,
        period_type=period_type,
        period_start=period_start,
        period_end=period_end,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        status="needs_review" if warnings else "normalized",
        warnings=tuple(warnings),
    )
