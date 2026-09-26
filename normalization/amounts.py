"""Parse reported amounts without losing their source notation or currency."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from normalization.mapping import SourceLocation

UnitScale = Literal["ones", "thousands", "millions", "billions"]
NormalizationStatus = Literal["normalized", "missing", "needs_review"]

_MULTIPLIERS: dict[UnitScale, Decimal] = {
    "ones": Decimal(1),
    "thousands": Decimal(1_000),
    "millions": Decimal(1_000_000),
    "billions": Decimal(1_000_000_000),
}
_UNIT_NAMES: dict[str, UnitScale] = {
    "actual": "ones",
    "actuals": "ones",
    "one": "ones",
    "ones": "ones",
    "unit": "ones",
    "units": "ones",
    "thousand": "thousands",
    "thousands": "thousands",
    "000": "thousands",
    "000s": "thousands",
    "million": "millions",
    "millions": "millions",
    "billion": "billions",
    "billions": "billions",
}
_SYMBOL_CURRENCIES = {"€": "EUR", "£": "GBP", "₹": "INR"}
_AMBIGUOUS_SYMBOLS = {"$", "¥"}
_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_AMOUNT = re.compile(
    rf"(?P<sign>[+-]?)(?P<prefix>[$€£¥₹]|[A-Za-z]{{3}})?\s*"
    rf"(?P<number>{_NUMBER})\s*(?P<suffix>[A-Za-z]{{3}})?"
)


@dataclass(frozen=True, slots=True)
class NormalizationWarning:
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class NormalizedAmount:
    original_value: str | int | float | Decimal | None
    normalized_value: Decimal | None
    original_unit: str | None
    original_currency: str | None
    unit_scale: UnitScale | None
    multiplier: Decimal | None
    currency_symbol: str | None
    currency: str | None
    status: NormalizationStatus
    warnings: tuple[NormalizationWarning, ...]
    source_location: SourceLocation


def _unit_scale(unit: str | None) -> UnitScale | None:
    if unit is None:
        return "ones"
    key = re.sub(r"\s+", " ", unit.strip().casefold())
    key = key.removeprefix("in ").strip("() ")
    return _UNIT_NAMES.get(key)


def _scale_number(number: Decimal, scale: UnitScale) -> Decimal:
    """Shift the exponent without context rounding."""
    shift = {"ones": 0, "thousands": 3, "millions": 6, "billions": 9}[scale]
    parts = number.as_tuple()
    return Decimal((parts.sign, parts.digits, parts.exponent + shift))


def normalize_amount(
    value: str | int | float | Decimal | None,
    *,
    unit: str | None = None,
    currency: str | None = None,
    source_location: SourceLocation | None = None,
) -> NormalizedAmount:
    """Scale an amount exactly; unresolved values remain reviewable, never zero.

    A missing unit means actual/ones. Currency hints must be ISO-style three-letter
    codes; symbols do not cause an exchange-rate conversion.
    """
    warnings: list[NormalizationWarning] = []
    scale = _unit_scale(unit)
    if scale is None:
        warnings.append(
            NormalizationWarning("unknown_unit", "Unit scale needs review.")
        )
    hint = currency.upper() if currency is not None else None
    if hint is not None and not re.fullmatch(r"[A-Z]{3}", hint):
        warnings.append(
            NormalizationWarning(
                "invalid_currency", "Currency must be a three-letter code."
            )
        )
        hint = None

    number: Decimal | None = None
    marker: str | None = None
    explicit_code: str | None = None
    code_conflict = False
    if value is None or (
        isinstance(value, str) and value.strip() in {"", "-", "–", "—"}
    ):
        warnings.append(
            NormalizationWarning("missing_value", "No amount was reported.")
        )
        status: NormalizationStatus = "missing"
    elif isinstance(value, bool):
        warnings.append(
            NormalizationWarning("invalid_number", "A boolean is not an amount.")
        )
        status = "needs_review"
    elif isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
            if not number.is_finite():
                number = None
                raise InvalidOperation
        except InvalidOperation:
            warnings.append(
                NormalizationWarning("invalid_number", "Amount is not finite.")
            )
        status = "normalized" if number is not None else "needs_review"
    elif isinstance(value, str):
        original = value.strip()
        parenthesized = original.startswith("(") and original.endswith(")")
        if parenthesized:
            original = original[1:-1].strip()
        match = _AMOUNT.fullmatch(original)
        if match is None or (parenthesized and match.group("sign")):
            warnings.append(
                NormalizationWarning("invalid_number", "Amount format needs review.")
            )
            status = "needs_review"
        else:
            prefix, suffix = match.group("prefix"), match.group("suffix")
            if prefix in _AMBIGUOUS_SYMBOLS or prefix in _SYMBOL_CURRENCIES:
                marker = prefix
            elif prefix:
                explicit_code = prefix.upper()
            if suffix:
                suffix_code = suffix.upper()
                if explicit_code and explicit_code != suffix_code:
                    code_conflict = True
                    warnings.append(
                        NormalizationWarning(
                            "currency_conflict", "Currency codes disagree."
                        )
                    )
                explicit_code = suffix_code
            try:
                number = Decimal(match.group("number").replace(",", ""))
                if parenthesized or match.group("sign") == "-":
                    number = -number
            except InvalidOperation:
                warnings.append(
                    NormalizationWarning(
                        "invalid_number", "Amount format needs review."
                    )
                )
            status = "normalized" if number is not None else "needs_review"
    else:
        warnings.append(
            NormalizationWarning("invalid_number", "Unsupported amount type.")
        )
        status = "needs_review"

    resolved_currency = None if code_conflict else explicit_code or hint
    if explicit_code and hint and explicit_code != hint:
        warnings.append(
            NormalizationWarning("currency_conflict", "Currency codes disagree.")
        )
        resolved_currency = None
    if marker in _SYMBOL_CURRENCIES and not code_conflict:
        symbol_code = _SYMBOL_CURRENCIES[marker]
        if resolved_currency and resolved_currency != symbol_code:
            warnings.append(
                NormalizationWarning(
                    "currency_conflict", "Currency symbol and code disagree."
                )
            )
            resolved_currency = None
        else:
            resolved_currency = symbol_code
    elif marker in _AMBIGUOUS_SYMBOLS and resolved_currency is None:
        warnings.append(
            NormalizationWarning("ambiguous_currency", "Currency symbol needs a code.")
        )
    if scale is None or any(w.code != "missing_value" for w in warnings):
        status = "needs_review"

    return NormalizedAmount(
        original_value=value,
        normalized_value=_scale_number(number, scale)
        if number is not None and scale is not None
        else None,
        original_unit=unit,
        original_currency=currency,
        unit_scale=scale,
        multiplier=_MULTIPLIERS[scale] if scale is not None else None,
        currency_symbol=marker,
        currency=resolved_currency,
        status=status,
        warnings=tuple(warnings),
        source_location=source_location or SourceLocation(),
    )
