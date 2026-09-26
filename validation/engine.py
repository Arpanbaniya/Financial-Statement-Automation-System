"""Reconcile accepted values without editing or guessing missing figures."""

from collections import defaultdict
from decimal import Decimal, localcontext

from normalization.taxonomy import fields_for_statement
from validation.types import (
    SourceRef,
    StatementSnapshot,
    TolerancePolicy,
    ValidationResult,
    ValidationStatus,
    ValidationValue,
)


def _refs(values: tuple[ValidationValue, ...]) -> tuple[SourceRef, ...]:
    return tuple(dict.fromkeys(value.source_ref for value in values))


def _result(
    name: str,
    status: ValidationStatus,
    explanation: str,
    *,
    statement_id: str | None = None,
    expected: Decimal | None = None,
    actual: Decimal | None = None,
    tolerance: Decimal | None = None,
    refs: tuple[SourceRef, ...] = (),
) -> ValidationResult:
    severity = {
        "pass": "info",
        "warning": "warning",
        "fail": "error",
        "unavailable": "info",
    }[status]
    return ValidationResult(
        check_name=name,
        status=status,
        expected_value=expected,
        actual_value=actual,
        difference=actual - expected
        if actual is not None and expected is not None
        else None,
        tolerance=tolerance,
        severity=severity,
        source_refs=refs,
        explanation=explanation,
        statement_id=statement_id,
    )


def _accepted(statement: StatementSnapshot, field: str) -> tuple[ValidationValue, ...]:
    return tuple(
        value
        for value in statement.values
        if value.field == field
        and value.status == "accepted"
        and value.normalized_value is not None
    )


def _currency(statement: StatementSnapshot, value: ValidationValue) -> str | None:
    return value.currency or statement.currency


def _unit(statement: StatementSnapshot, value: ValidationValue) -> str | None:
    return value.unit_scale or statement.unit_scale


def _unique(
    statement: StatementSnapshot, field: str, policy: TolerancePolicy
) -> ValidationValue | None:
    values = _accepted(statement, field)
    if not values:
        return None
    first = values[0]
    for other in values[1:]:
        if (
            _currency(statement, first) != _currency(statement, other)
            or first.normalized_value is None
            or other.normalized_value is None
            or abs(first.normalized_value - other.normalized_value)
            > policy.for_values(first.normalized_value, other.normalized_value)
        ):
            return None
    return first


def _equation(
    statement: StatementSnapshot,
    name: str,
    terms: tuple[tuple[str, int], ...],
    actual_field: str,
    policy: TolerancePolicy,
    *,
    enabled: bool = True,
    reason: str = "Source structure does not establish this subtotal.",
) -> ValidationResult:
    fields = tuple(field for field, _ in terms) + (actual_field,)
    related = tuple(value for value in statement.values if value.field in fields)
    refs = _refs(related)
    if not enabled:
        return _result(
            name, "unavailable", reason, statement_id=statement.id, refs=refs
        )
    chosen = {field: _unique(statement, field, policy) for field in fields}
    missing = [field for field, value in chosen.items() if value is None]
    if missing:
        return _result(
            name,
            "unavailable",
            "Accepted, unambiguous values are unavailable for: "
            + ", ".join(missing)
            + ".",
            statement_id=statement.id,
            refs=refs,
        )
    values = tuple(value for value in chosen.values() if value is not None)
    currencies = {_currency(statement, value) for value in values}
    units = {_unit(statement, value) for value in values}
    if None in currencies or len(currencies) != 1 or None in units:
        return _result(
            name,
            "unavailable",
            "Currency or unit metadata is incomplete; amounts were not compared.",
            statement_id=statement.id,
            refs=refs,
        )
    if statement.currency and any(
        value.currency and value.currency != statement.currency for value in values
    ):
        return _result(
            name,
            "unavailable",
            "A line-item currency disagrees with the statement currency.",
            statement_id=statement.id,
            refs=refs,
        )
    expected = sum(
        (
            chosen[field].normalized_value * sign  # type: ignore[union-attr]
            for field, sign in terms
        ),
        Decimal(0),
    )
    actual = chosen[actual_field].normalized_value  # type: ignore[union-attr]
    tolerance = policy.for_values(expected, actual)
    passed = abs(actual - expected) <= tolerance
    return _result(
        name,
        "pass" if passed else "fail",
        "Reported value reconciles within tolerance."
        if passed
        else "Reported value differs from source arithmetic beyond tolerance.",
        statement_id=statement.id,
        expected=expected,
        actual=actual,
        tolerance=tolerance,
        refs=refs,
    )


def _metadata(statement: StatementSnapshot, kind: str) -> ValidationResult:
    values = tuple(
        value
        for value in statement.values
        if value.status == "accepted" and value.normalized_value is not None
    )
    name = "inconsistent_currencies" if kind == "currency" else "inconsistent_units"
    if not values:
        return _result(
            name,
            "unavailable",
            "No accepted values are available for a metadata comparison.",
            statement_id=statement.id,
        )
    get = _currency if kind == "currency" else _unit
    metadata = statement.currency if kind == "currency" else statement.unit_scale
    seen = {get(statement, value) for value in values}
    explicit = {
        value.currency if kind == "currency" else value.unit_scale for value in values
    } - {None}
    if None in seen or len(seen) > 1 or (metadata and explicit - {metadata}):
        explanation = (
            "Line items use mixed or unresolved currencies; no conversion was made."
            if kind == "currency"
            else "Line items have mixed or unresolved unit scales.",
        )
        status: ValidationStatus = "warning"
    else:
        explanation = "Accepted line items have consistent reported metadata."
        status = "pass"
    return _result(
        name,
        status,
        explanation,
        statement_id=statement.id,
        refs=_refs(values),
    )


def _required(statement: StatementSnapshot) -> ValidationResult:
    required = {
        field.machine_name
        for field in fields_for_statement(statement.statement_type)
        if field.required
    }
    present = {
        value.field
        for value in statement.values
        if value.status == "accepted" and value.normalized_value is not None
    }
    missing = sorted(required - present)
    return _result(
        "missing_required_fields",
        "warning" if missing else "pass",
        "Core fields missing or awaiting review: " + ", ".join(missing) + "."
        if missing
        else "All core fields have accepted values.",
        statement_id=statement.id,
        refs=_refs(statement.values),
    )


def _within_conflicts(
    statement: StatementSnapshot, policy: TolerancePolicy
) -> tuple[ValidationResult, ...]:
    by_field: dict[str, list[ValidationValue]] = defaultdict(list)
    for value in statement.values:
        if value.status == "accepted" and value.normalized_value is not None:
            by_field[value.field].append(value)
    results: list[ValidationResult] = []
    for field, values in sorted(by_field.items()):
        if len(values) < 2:
            continue
        first = values[0]
        for other in values[1:]:
            if _currency(statement, first) != _currency(statement, other):
                continue
            tolerance = policy.for_values(
                first.normalized_value,
                other.normalized_value,  # type: ignore[arg-type]
            )
            if abs(first.normalized_value - other.normalized_value) > tolerance:  # type: ignore[operator]
                results.append(
                    _result(
                        f"conflicting_values:{field}",
                        "fail",
                        "Accepted values for this field and period disagree.",
                        statement_id=statement.id,
                        expected=first.normalized_value,
                        actual=other.normalized_value,
                        tolerance=tolerance,
                        refs=_refs((first, other)),
                    )
                )
                break
    if not results:
        results.append(
            _result(
                "conflicting_values",
                "pass",
                "No conflicting accepted values were found within this statement.",
                statement_id=statement.id,
            )
        )
    return tuple(results)


def _statement_checks(
    statement: StatementSnapshot, policy: TolerancePolicy
) -> tuple[ValidationResult, ...]:
    results = [
        _metadata(statement, "currency"),
        _metadata(statement, "unit"),
        _required(statement),
        *_within_conflicts(statement, policy),
    ]
    if statement.statement_type == "balance_sheet":
        results.extend(
            (
                _equation(
                    statement,
                    "accounting_equation",
                    (("total_liabilities", 1), ("shareholders_equity", 1)),
                    "total_assets",
                    policy,
                ),
                _equation(
                    statement,
                    "current_assets_subtotal",
                    (
                        ("cash_and_cash_equivalents", 1),
                        ("short_term_investments", 1),
                        ("accounts_receivable", 1),
                        ("inventory", 1),
                        ("other_current_assets", 1),
                    ),
                    "total_current_assets",
                    policy,
                    enabled=statement.current_assets_components_complete,
                    reason="Current-assets breakdown is not confirmed complete.",
                ),
                _equation(
                    statement,
                    "current_liabilities_subtotal",
                    (
                        ("accounts_payable", 1),
                        ("short_term_debt", 1),
                        ("other_current_liabilities", 1),
                    ),
                    "total_current_liabilities",
                    policy,
                    enabled=statement.current_liabilities_components_complete,
                    reason="Current-liabilities breakdown is not confirmed complete.",
                ),
            )
        )
    elif statement.statement_type == "income_statement":
        results.extend(
            (
                _equation(
                    statement,
                    "gross_profit",
                    (("revenue", 1), ("cost_of_revenue", -1)),
                    "gross_profit",
                    policy,
                ),
                _equation(
                    statement,
                    "operating_income",
                    (("gross_profit", 1), ("operating_expenses", -1)),
                    "operating_income",
                    policy,
                    enabled=statement.operating_expenses_exclude_cost,
                ),
            )
        )
    else:
        results.extend(
            (
                _equation(
                    statement,
                    "cash_bridge",
                    (("beginning_cash", 1), ("net_change_in_cash", 1)),
                    "ending_cash",
                    policy,
                ),
                _equation(
                    statement,
                    "cash_flow_subtotal",
                    (
                        ("operating_cash_flow", 1),
                        ("investing_cash_flow", 1),
                        ("financing_cash_flow", 1),
                    ),
                    "net_change_in_cash",
                    policy,
                    enabled=statement.cash_flow_components_complete,
                    reason="Cash-flow categories may omit other adjustments.",
                ),
            )
        )
    return tuple(results)


def _period_key(statement: StatementSnapshot) -> tuple | None:
    period = statement.period
    if (
        period.status != "normalized"
        or period.period_end is None
        or period.period_type is None
    ):
        return None
    if period.period_type != "instant" and period.period_start is None:
        return None
    return (
        statement.company_id,
        statement.statement_type,
        period.period_type,
        period.period_start,
        period.period_end,
    )


def _period_checks(
    statements: tuple[StatementSnapshot, ...], policy: TolerancePolicy
) -> tuple[ValidationResult, ...]:
    groups: dict[tuple, list[StatementSnapshot]] = defaultdict(list)
    for statement in statements:
        key = _period_key(statement)
        if key is not None:
            groups[key].append(statement)
    results: list[ValidationResult] = []
    for statement in statements:
        key = _period_key(statement)
        if key is None:
            results.append(
                _result(
                    "duplicate_period",
                    "unavailable",
                    "Reporting period needs review before duplicates can be checked.",
                    statement_id=statement.id,
                    refs=(SourceRef(statement.id),),
                )
            )
            continue
        group = groups[key]
        results.append(
            _result(
                "duplicate_period",
                "warning" if len(group) > 1 else "pass",
                "Another statement for this company, type, and reporting period exists."
                if len(group) > 1
                else "No duplicate reporting period was found.",
                statement_id=statement.id,
                refs=tuple(SourceRef(item.id) for item in group),
            )
        )
    for group in groups.values():
        if len(group) < 2:
            continue
        fields = sorted(
            {value.field for statement in group for value in statement.values}
        )
        for field in fields:
            items = [
                (statement, value)
                for statement in group
                if (value := _unique(statement, field, policy)) is not None
            ]
            if len(items) < 2:
                continue
            first_statement, first = items[0]
            for other_statement, other in items[1:]:
                currencies = {
                    _currency(first_statement, first),
                    _currency(other_statement, other),
                }
                statement_conflict = any(
                    snapshot.currency
                    and item.currency
                    and snapshot.currency != item.currency
                    for snapshot, item in (
                        (first_statement, first),
                        (other_statement, other),
                    )
                )
                if None in currencies or len(currencies) != 1 or statement_conflict:
                    results.append(
                        _result(
                            f"cross_statement_currency:{field}",
                            "warning",
                            "Duplicate-period currencies differ or are unresolved.",
                            refs=_refs((first, other)),
                        )
                    )
                    break
                if (
                    _unit(first_statement, first) is None
                    or _unit(other_statement, other) is None
                ):
                    results.append(
                        _result(
                            f"cross_statement_units:{field}",
                            "warning",
                            "Duplicate-period unit scales are unresolved.",
                            refs=_refs((first, other)),
                        )
                    )
                    break
                if _unit(first_statement, first) != _unit(other_statement, other):
                    results.append(
                        _result(
                            f"cross_statement_units:{field}",
                            "warning",
                            "Duplicate-period source unit scales differ.",
                            refs=_refs((first, other)),
                        )
                    )
                tolerance = policy.for_values(
                    first.normalized_value,
                    other.normalized_value,  # type: ignore[arg-type]
                )
                if abs(first.normalized_value - other.normalized_value) > tolerance:  # type: ignore[operator]
                    results.append(
                        _result(
                            f"cross_statement_conflict:{field}",
                            "fail",
                            "Accepted values for this field and period disagree.",
                            expected=first.normalized_value,
                            actual=other.normalized_value,
                            tolerance=tolerance,
                            refs=_refs((first, other)),
                        )
                    )
                    break
    return tuple(results)


def validate_statements(
    statements: tuple[StatementSnapshot, ...] | list[StatementSnapshot],
    *,
    tolerance: TolerancePolicy | None = None,
) -> tuple[ValidationResult, ...]:
    """Return deterministic checks for immutable, already-normalized snapshots."""
    snapshots = tuple(statements)
    if len({statement.id for statement in snapshots}) != len(snapshots):
        raise ValueError("Statement IDs must be unique in one validation batch")
    policy = tolerance or TolerancePolicy()
    numbers = [
        value.normalized_value
        for statement in snapshots
        for value in statement.values
        if value.normalized_value is not None
    ] + [policy.absolute, policy.relative]
    integer_digits = max(
        max(len(number.as_tuple().digits) + number.as_tuple().exponent, 0)
        for number in numbers
    )
    fractional_digits = max(max(-number.as_tuple().exponent, 0) for number in numbers)
    with localcontext() as context:
        context.prec = max(28, integer_digits + fractional_digits + 12)
        results = [
            result
            for statement in snapshots
            for result in _statement_checks(statement, policy)
        ]
        results.extend(_period_checks(snapshots, policy))
    return tuple(results)
