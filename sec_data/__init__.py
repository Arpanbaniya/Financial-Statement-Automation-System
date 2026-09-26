"""SEC EDGAR data access and explicit XBRL field mapping."""

from sec_data.adapter import (
    SecComparison,
    SecFact,
    SecFiling,
    compare_to_statement,
    map_company_facts,
    parse_recent_filings,
)
from sec_data.client import SecClient, SecError, normalize_cik

__all__ = [
    "SecClient",
    "SecComparison",
    "SecError",
    "SecFact",
    "SecFiling",
    "compare_to_statement",
    "map_company_facts",
    "normalize_cik",
    "parse_recent_filings",
]
