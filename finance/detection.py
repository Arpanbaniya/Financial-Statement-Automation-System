"""Deterministic, source-linked financial statement classification."""

import re
from dataclasses import dataclass
from typing import Literal

from ingestion.types import ExtractedDocument, ExtractedRow, IngestionWarning

StatementType = Literal[
    "income_statement", "balance_sheet", "cash_flow_statement", "unknown"
]
KnownStatementType = Literal["income_statement", "balance_sheet", "cash_flow_statement"]
SignalKind = Literal["heading", "line_item"]


@dataclass(frozen=True, slots=True)
class StatementRule:
    statement_type: KnownStatementType
    heading_patterns: tuple[str, ...]
    line_item_patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DetectionEvidence:
    statement_type: KnownStatementType
    kind: SignalKind
    matched_text: str
    source_reference: str


@dataclass(frozen=True, slots=True)
class StatementDetection:
    statement_type: StatementType
    confidence: float
    evidence: tuple[DetectionEvidence, ...]
    source_page: int | None
    source_sheet: str | None
    source_table: str | None
    warnings: tuple[IngestionWarning, ...]


DEFAULT_RULES = (
    StatementRule(
        "income_statement",
        (
            r"(?:statements? of (?:operations|income|earnings)|income statements?)",
            r"(?:profit (?:and|&) loss(?: statements?)?|p\s*&\s*l)",
        ),
        (
            r"(?:net )?revenues?\b",
            r"(?:cost of (?:revenue|sales)|cost of goods sold)\b",
            r"gross profit\b",
            r"operating (?:income|loss|expenses?)\b",
            r"(?:net income|net loss|net earnings)\b",
            r"(?:income tax expense|provision for income taxes)\b",
        ),
    ),
    StatementRule(
        "balance_sheet",
        (r"(?:balance sheets?|statements? of financial position)",),
        (
            r"total assets\b",
            r"total liabilities\b",
            r"(?:stockholders|shareholders|owners)[’']? equity\b",
            r"accounts receivable\b",
            r"inventor(?:y|ies)\b",
            r"(?:cash and cash equivalents|cash & cash equivalents)\b",
            r"accounts payable\b",
            r"retained earnings\b",
        ),
    ),
    StatementRule(
        "cash_flow_statement",
        (r"(?:statements? of cash flows?|cash flow statements?)",),
        (
            r"cash flows? from operating activities\b",
            r"cash flows? from investing activities\b",
            r"cash flows? from financing activities\b",
            r"net cash (?:provided by|used in) operating activities\b",
            r"net cash (?:provided by|used in) investing activities\b",
            r"net cash (?:provided by|used in) financing activities\b",
            r"(?:capital expenditures?|purchase of property and equipment)\b",
            r"(?:net increase|net decrease) in cash\b",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class _Line:
    text: str
    reference: str


@dataclass(frozen=True, slots=True)
class _Unit:
    page: int | None
    sheet: str | None
    table: str | None
    heading_lines: tuple[_Line, ...]
    content_lines: tuple[_Line, ...]


def _label(row: ExtractedRow) -> tuple[str, str] | None:
    for cell in row.cells:
        if isinstance(cell.value, str) and cell.value.strip():
            return cell.value.strip(), cell.coordinate
    return None


def _normalized(text: str) -> str:
    return " ".join(text.casefold().strip(" :\t–—-").split())[:200]


def _units(
    document: ExtractedDocument, heading_patterns: tuple[re.Pattern[str], ...]
) -> tuple[_Unit, ...]:
    units: list[_Unit] = []
    if document.file_type == "pdf":
        for page in document.pages:
            lines = tuple(
                _Line(text.strip(), f"page {page.number} line {number}")
                for number, text in enumerate(page.text.splitlines(), start=1)
                if text.strip()
            )
            table_lines: list[_Line] = []
            for table in document.tables:
                if table.page_number != page.number:
                    continue
                for row in table.rows:
                    label = _label(row)
                    if label:
                        table_lines.append(_Line(label[0], f"{table.name} {label[1]}"))
            units.append(
                _Unit(
                    page.number,
                    None,
                    None,
                    lines[:8] or tuple(table_lines[:8]),
                    (*lines, *table_lines),
                )
            )
    elif document.file_type == "xlsx":
        for sheet in document.sheets:
            regions = [table for table in document.tables if table.source == sheet.name]
            blocks = [(table.name, table.rows) for table in regions]
            if not blocks:
                blocks = [(None, sheet.rows)]
            merged_blocks: list[tuple[str | None, tuple[ExtractedRow, ...]]] = []
            index = 0
            while index < len(blocks):
                name, rows = blocks[index]
                if index + 1 < len(blocks) and rows:
                    next_name, next_rows = blocks[index + 1]
                    has_heading = any(
                        any(
                            pattern.fullmatch(_normalized(label[0]))
                            for pattern in heading_patterns
                        )
                        for row in rows[:3]
                        if (label := _label(row)) is not None
                    )
                    if (
                        len(rows) <= 3
                        and has_heading
                        and next_rows
                        and next_rows[0].number - rows[-1].number <= 4
                    ):
                        merged_blocks.append(
                            (f"{name} + {next_name}", rows + next_rows)
                        )
                        index += 2
                        continue
                merged_blocks.append((name, rows))
                index += 1
            blocks = merged_blocks
            for region_name, rows in blocks:
                lines = tuple(
                    _Line(label[0], f"{sheet.name}!{label[1]}")
                    for row in rows
                    if (label := _label(row)) is not None
                )
                sheet_heading = (
                    (_Line(sheet.name, f"sheet {sheet.name}"),)
                    if len(blocks) == 1
                    else ()
                )
                units.append(
                    _Unit(
                        None,
                        sheet.name,
                        region_name,
                        (*sheet_heading, *lines[:8]),
                        lines,
                    )
                )
    elif document.file_type == "csv":
        for table in document.tables:
            lines = tuple(
                _Line(label[0], f"record {row.number} ({label[1]})")
                for row in table.rows
                if (label := _label(row)) is not None
            )
            units.append(_Unit(None, None, table.name, lines[:8], lines))
    return tuple(units)


def _prepare_rules(
    rules: tuple[StatementRule, ...],
) -> tuple[
    tuple[StatementRule, tuple[re.Pattern[str], ...], tuple[re.Pattern[str], ...]], ...
]:
    if not rules or len({rule.statement_type for rule in rules}) != len(rules):
        raise ValueError("Statement rules must contain unique statement types")
    prepared = []
    for rule in rules:
        if rule.statement_type not in {
            "income_statement",
            "balance_sheet",
            "cash_flow_statement",
        }:
            raise ValueError("Statement rule has an unsupported statement type")
        headings = tuple(
            re.compile(
                rf"^(?:(?:unaudited|condensed|consolidated|combined)\s+)*"
                rf"(?:{pattern})(?:\s*\(unaudited\))?$",
                re.IGNORECASE,
            )
            for pattern in rule.heading_patterns
        )
        items = tuple(
            re.compile(rf"^(?:{pattern})", re.IGNORECASE)
            for pattern in rule.line_item_patterns
        )
        prepared.append((rule, headings, items))
    return tuple(prepared)


def _score(
    unit: _Unit,
    rule: StatementRule,
    headings: tuple[re.Pattern[str], ...],
    items: tuple[re.Pattern[str], ...],
) -> tuple[float, tuple[DetectionEvidence, ...]]:
    if not unit.content_lines:
        return 0.0, ()
    evidence: list[DetectionEvidence] = []
    heading_found = False
    for line in unit.heading_lines:
        text = _normalized(line.text)
        if any(pattern.fullmatch(text) for pattern in headings):
            evidence.append(
                DetectionEvidence(
                    rule.statement_type, "heading", line.text, line.reference
                )
            )
            heading_found = True
            break
    matched_items = 0
    for pattern in items:
        for line in unit.content_lines:
            text = " ".join(line.text.casefold().strip().split())[:200]
            if pattern.match(text):
                evidence.append(
                    DetectionEvidence(
                        rule.statement_type, "line_item", line.text, line.reference
                    )
                )
                matched_items += 1
                break
    if not heading_found and matched_items < 2:
        return 0.0, tuple(evidence)
    density = matched_items / max(len(unit.content_lines), 1)
    confidence = (
        (0.64 if heading_found else 0.25)
        + min(matched_items, 4) * (0.07 if heading_found else 0.12)
        + min(density, 1.0) * 0.08
    )
    return min(round(confidence, 2), 0.94), tuple(evidence)


def detect_statements(
    document: ExtractedDocument,
    *,
    rules: tuple[StatementRule, ...] = DEFAULT_RULES,
) -> tuple[StatementDetection, ...]:
    """Classify each PDF page, workbook sheet, or CSV table without changing it."""
    prepared = _prepare_rules(rules)
    heading_patterns = tuple(
        pattern for _, headings, _ in prepared for pattern in headings
    )
    detections: list[StatementDetection] = []
    for unit in _units(document, heading_patterns):
        scored = sorted(
            (
                (*_score(unit, rule, headings, items), rule.statement_type)
                for rule, headings, items in prepared
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        best = scored[0]
        second = scored[1] if len(scored) > 1 else None
        location = (
            f"page {unit.page}" if unit.page is not None else unit.sheet or unit.table
        )
        warnings = [
            warning
            for warning in document.warnings
            if warning.location is None
            or document.file_type == "csv"
            or warning.location == location
            or (
                unit.sheet is not None and warning.location.startswith(f"{unit.sheet}!")
            )
        ]
        ambiguous = second is not None and best[0] - second[0] < 0.12 and second[0] > 0
        if best[0] < 0.45 or ambiguous:
            code = "AMBIGUOUS_STATEMENT" if ambiguous else "WEAK_STATEMENT_SIGNALS"
            message = (
                "Multiple statement types have similar evidence"
                if ambiguous
                else "No reliable statement type was found"
            )
            warnings.append(IngestionWarning(code, message, location))
            evidence = (
                best[1] + (second[1] if second else ())
                if ambiguous
                else tuple(item for scored_type in scored for item in scored_type[1])
            )
            statement_type: StatementType = "unknown"
            confidence = 0.0
        else:
            evidence = best[1]
            statement_type = best[2]
            confidence = best[0]
        detections.append(
            StatementDetection(
                statement_type=statement_type,
                confidence=confidence,
                evidence=evidence,
                source_page=unit.page,
                source_sheet=unit.sheet,
                source_table=unit.table,
                warnings=tuple(warnings),
            )
        )
    return tuple(detections)
