"""Rule-based financial commentary using only supplied calculated facts."""

from decimal import ROUND_HALF_UP, Decimal

from ai.facts import AiFact

_ONE = Decimal("0.1")


def _number(value: Decimal) -> str:
    return f"{value.quantize(_ONE, rounding=ROUND_HALF_UP):,.1f}"


def _display(fact: AiFact) -> str:
    value = fact.value
    if value is None:
        return "unavailable"
    if fact.unit == "percent":
        return f"{_number(value)}%"
    if fact.unit == "currency":
        symbol = fact.currency or "currency units"
        if abs(value) >= 1_000_000:
            return f"{symbol} {_number(value / 1_000_000)} million"
        if abs(value) >= 1_000:
            return f"{symbol} {_number(value / 1_000)} thousand"
        return f"{symbol} {_number(value)}"
    suffix = " days" if fact.unit == "days" else ""
    return f"{_number(value)}{suffix}"


def _direction(current: Decimal, previous: Decimal) -> str:
    if current > previous:
        return "increased"
    if current < previous:
        return "decreased"
    return "remained unchanged"


def fallback_text(facts: tuple[AiFact, ...]) -> str:
    """Write a short summary without an API, model, or guessed values."""
    by_name: dict[str, list[AiFact]] = {}
    warnings: list[AiFact] = []
    for fact in facts:
        if fact.kind == "warning":
            warnings.append(fact)
        elif fact.value is not None and fact.period_end is not None:
            by_name.setdefault(fact.label, []).append(fact)
    for values in by_name.values():
        values.sort(key=lambda item: item.period_end, reverse=True)

    sentences: list[str] = []
    growth = by_name.get("revenue growth", [])
    if growth:
        value = growth[0].value
        if value > 0:
            sentences.append(
                f"Revenue increased by {_display(growth[0])} "
                "compared with the prior comparable period."
            )
        elif value < 0:
            sentences.append(
                f"Revenue decreased by {_number(abs(value))}% "
                "compared with the prior comparable period."
            )
        else:
            sentences.append("Revenue was unchanged from the prior comparable period.")

    for name, title in (
        ("gross margin", "Gross margin"),
        ("operating margin", "Operating margin"),
        ("net margin", "Net margin"),
        ("current ratio", "The current ratio"),
        ("debt to equity", "Debt-to-equity"),
    ):
        values = by_name.get(name, [])
        if not values:
            continue
        current = values[0]
        if len(values) > 1:
            previous = values[1]
            verb = _direction(current.value, previous.value)
            sentences.append(
                f"{title} {verb} from {_display(previous)} to {_display(current)}."
            )
        else:
            sentences.append(f"{title} was {_display(current)}.")

    for name, title in (
        ("return on assets", "Return on assets"),
        ("return on equity", "Return on equity"),
    ):
        values = by_name.get(name, [])
        if values:
            sentences.append(f"{title} was {_display(values[0])}.")

    for name, title in (
        ("operating cash flow", "Operating cash flow"),
        ("free cash flow", "Free cash flow"),
    ):
        values = by_name.get(name, [])
        if values:
            sign = (
                "positive"
                if values[0].value > 0
                else "negative"
                if values[0].value < 0
                else "zero"
            )
            sentences.append(f"{title} was {sign} at {_display(values[0])}.")

    handled = {
        "revenue growth",
        "gross margin",
        "operating margin",
        "net margin",
        "current ratio",
        "debt to equity",
        "return on assets",
        "return on equity",
        "operating cash flow",
        "free cash flow",
    }
    for name, values in by_name.items():
        if name not in handled:
            sentences.append(
                f"{name.replace('_', ' ').capitalize()} was {_display(values[0])}."
            )
    if warnings:
        names = ", ".join(warning.label for warning in warnings[:3])
        sentences.append(f"Review these validation warnings: {names}.")
    if not sentences:
        return "No validated, source-linked metrics are available to explain."
    return " ".join(sentences[:12])
