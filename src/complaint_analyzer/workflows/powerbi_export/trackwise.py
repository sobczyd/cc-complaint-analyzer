"""Trackwise integration: the ``FactComplaint`` table and the Trackwise-only ``FactSource`` columns.

Ports the trackforce-insight reduction (``scripts/dev/preprocess/preprocess_tw_export.py`` and
``scripts/dev/export/{columns,dedupe,combine}.py``) onto the three raw Trackwise CSV exports.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_TRACKWISE_DIR = Path("data") / "trackwise"
QUERY_FILE = "query_export_results.csv"
PRODUCT_FILE = "Product Information.csv"
CODES_FILE = "As Determined Codes.csv"

PR_ID = "PR ID"
SOURCE_IDENTIFIER = "Source Identifier"
SOURCE_IDENTIFIER_RAW = "Source Identifier Raw"
PRODUCT_CODE = "Product Code/Part #^"
PRODUCT_IS_DUPLICATED = "product_IsDuplicated"
CODES_IS_DUPLICATED = "codes_IsDuplicated"
KEPT_FILE = "kept_file"
YES, NO = "Yes", "No"

QUERY_COLUMNS = (
    "Project", "Complaint Receipt Date", "Date Opened", "Date Closed", "PR State", "Source Status",
    "Source Created Date", "Source Closed Date", "Event Description", "Evaluation Rationale",
)
PRODUCT_COLUMNS = (
    "Product Family^", PRODUCT_CODE, "Product Lot/Serial #^", "Product Name^", "As Reported Problem Code^",
    "As Reported Problem Category^", "As Reported Component Code^",
)
# The codes export also carries the part number, used ahead of the product export's value.
CODE_COLUMNS = (
    "Manufacturing Location Code^", "As Determined Product Family^", PRODUCT_CODE, "Lot #^", "As Determined Code^",
    "As Determined Category^", "As Determined Component Code^", "As Determined Cause Code^",
    "As Determined Cause Category^",
)
# (merged header, Trackwise header, Salesforce header): Trackwise wins when non-blank.
MERGED_CODE_COLUMNS = (
    ("As Determined Problem Codes_Merged", "As Determined Code^", "As Determined Problem Codes"),
    ("As Determined Cause Codes_Merged", "As Determined Cause Code^", "As Determined Cause Codes"),
    ("Component Code_Merged", "As Determined Component Code^", "Component Code"),
)
MERGED_COLUMNS = tuple(name for name, _, _ in MERGED_CODE_COLUMNS)
CODE_ONLY_COLUMNS = tuple(name for name in CODE_COLUMNS if name != PRODUCT_CODE)
FACT_COMPLAINT_COLUMNS = (
    [PR_ID, SOURCE_IDENTIFIER, SOURCE_IDENTIFIER_RAW]
    + list(QUERY_COLUMNS)
    + list(PRODUCT_COLUMNS)
    + list(CODE_ONLY_COLUMNS)
    + list(MERGED_COLUMNS)
    + [PRODUCT_IS_DUPLICATED, CODES_IS_DUPLICATED]
)
# FactSource headers this module fills (the dashboard's Trackwise-only columns).
FACT_SOURCE_COLUMNS = (
    list(QUERY_COLUMNS) + [KEPT_FILE] + list(PRODUCT_COLUMNS) + list(CODE_ONLY_COLUMNS) + list(MERGED_COLUMNS)
)


class TrackwiseError(Exception):
    pass


def canon(value: Any) -> str | None:
    """Trimmed text, or None when blank."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def id_key(value: Any) -> str | None:
    """Compare numeric ids with or without leading zeros."""
    text = canon(value)
    if text is None or not text.isdigit():
        return text
    return text.lstrip("0") or "0"


def _encoding(path: Path) -> str:
    with path.open("rb") as handle:
        return "utf-16" if handle.read(2) in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"


def read_csv(path: Path) -> list[dict[str, str]]:
    """Tab-delimited Trackwise export as text records (nothing is type-converted, so leading zeros survive)."""
    if not path.is_file():
        raise TrackwiseError(f"Trackwise export not found: {path}")
    csv.field_size_limit(2**31 - 1)
    with path.open(encoding=_encoding(path), newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _reduce_last(
    records: Iterable[Mapping[str, str]], columns: Iterable[str]
) -> tuple[dict[str, dict[str, str | None]], dict[str, int]]:
    """Keep the last row per PR ID (blank ids dropped) and count the rows seen for each."""
    table: dict[str, dict[str, str | None]] = {}
    counts: dict[str, int] = {}
    for record in records:
        key = canon(record.get(PR_ID))
        if key is None:
            continue
        counts[key] = counts.get(key, 0) + 1
        table[key] = {name: canon(record.get(name)) for name in columns}
    return table, counts


@dataclass
class TrackwiseData:
    directory: Path
    query: dict[str, dict[str, str | None]]
    product: dict[str, dict[str, str | None]]
    codes: dict[str, dict[str, str | None]]
    product_duplicates: set[str]
    codes_duplicates: set[str]
    by_source: dict[str, list[str]] = field(default_factory=dict)  # id_key(Source Identifier) -> PR IDs, file order
    stats: dict[str, int] = field(default_factory=dict)

    def part_number(self, pr_key: str | None) -> str | None:
        if pr_key is None:
            return None
        return canon(self.codes.get(pr_key, {}).get(PRODUCT_CODE)) or canon(self.product.get(pr_key, {}).get(PRODUCT_CODE))

    def product_codes(self, pr_key: str | None) -> dict[str, str | None]:
        """Product and code columns for one PR; the part number prefers the codes export."""
        out: dict[str, str | None] = {}
        for name in PRODUCT_COLUMNS + CODE_ONLY_COLUMNS:
            source = self.product if name in PRODUCT_COLUMNS else self.codes
            out[name] = None if pr_key is None else canon(source.get(pr_key, {}).get(name))
        out[PRODUCT_CODE] = self.part_number(pr_key)
        return out

    def match(self, source_id: Any, pr_id: Any = None) -> tuple[str | None, int]:
        """PR ID of the Trackwise row for a case, plus how many PR candidates it had.

        Source Identifier first (leading zeros ignored; the last Closed PR wins, else the last),
        then the case's own PR ID.
        """
        candidates = self.by_source.get(id_key(source_id) or "", [])
        if candidates:
            closed = [pr for pr in candidates if (self.query[pr].get("PR State") or "").casefold() == "closed"]
            return (closed or candidates)[-1], len(candidates)
        pr_key = canon(_int_text(pr_id))
        if pr_key is not None and pr_key in self.query:
            return pr_key, 1
        return None, 0


def _int_text(value: Any) -> str | None:
    text = canon(value)
    if text is not None and text.endswith(".0"):
        text = text[:-2]
    return text


def load_trackwise(directory: Path) -> TrackwiseData:
    query_rows = [row for row in read_csv(directory / QUERY_FILE) if (row.get("Project") or "").strip() == "Complaint"]
    query, _ = _reduce_last(query_rows, [SOURCE_IDENTIFIER, *QUERY_COLUMNS])
    product, product_counts = _reduce_last(read_csv(directory / PRODUCT_FILE), PRODUCT_COLUMNS)
    codes, codes_counts = _reduce_last(read_csv(directory / CODES_FILE), CODE_COLUMNS)
    by_source: dict[str, list[str]] = {}
    for pr_key, row in query.items():
        key = id_key(row.get(SOURCE_IDENTIFIER))
        if key:
            by_source.setdefault(key, []).append(pr_key)
    return TrackwiseData(
        directory=directory,
        query=query,
        product=product,
        codes=codes,
        product_duplicates={key for key, count in product_counts.items() if count > 1},
        codes_duplicates={key for key, count in codes_counts.items() if count > 1},
        by_source=by_source,
        stats={"query_rows": len(query), "product_rows": len(product), "code_rows": len(codes)},
    )


def apply_trackwise(
    tw: TrackwiseData | None, headers: list[str], row: list[Any], kept_file: str
) -> tuple[str | None, int]:
    """Fill the Trackwise-only columns of one FactSource row in place; return the matched PR ID and candidate count."""
    index = {name: position for position, name in enumerate(headers)}

    def get(name: str) -> Any:
        return row[index[name]] if name in index else None

    def put(name: str, value: Any) -> None:
        if name in index and value is not None:
            row[index[name]] = value

    pr_key, candidates = (None, 0)
    if tw is not None:
        pr_key, candidates = tw.match(get(SOURCE_IDENTIFIER), get(PR_ID))
    if pr_key is not None:
        tw_row = tw.query[pr_key]
        for name in QUERY_COLUMNS:
            put(name, tw_row.get(name))
        for name, value in tw.product_codes(pr_key).items():
            put(name, value)
        if get(PR_ID) is None:
            put(PR_ID, int(pr_key) if pr_key.isdigit() else pr_key)
        put(KEPT_FILE, kept_file)
    for merged, trackwise, salesforce in MERGED_CODE_COLUMNS:
        value = canon(get(trackwise)) or canon(get(salesforce))
        if merged in index:
            row[index[merged]] = value
    return pr_key, candidates


def complaint_rows(tw: TrackwiseData, fact_rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """FactComplaint: one row per Trackwise PR ID.

    ``Source Identifier Raw`` is the matched FactSource case number, so the table relates 1:* to FactSource; PRs with
    no case in the run keep the Trackwise Source Identifier text.
    """
    case_by_source: dict[str, str] = {}
    sf_codes: dict[str, Mapping[str, Any]] = {}
    for fact in fact_rows:
        number = canon(fact.get(SOURCE_IDENTIFIER_RAW))
        if number is None:
            continue
        case_by_source[id_key(number) or ""] = number
        sf_codes[number] = fact
    pr_to_case: dict[str, str] = {}
    for fact in fact_rows:
        number, pr_key = canon(fact.get(SOURCE_IDENTIFIER_RAW)), tw.match(fact.get(SOURCE_IDENTIFIER), fact.get(PR_ID))[0]
        if number and pr_key:
            pr_to_case[pr_key] = number

    out: list[dict[str, Any]] = []
    for pr_key, tw_row in tw.query.items():
        source = tw_row.get(SOURCE_IDENTIFIER)
        case = case_by_source.get(id_key(source) or "") or pr_to_case.get(pr_key)
        record: dict[str, Any] = {name: tw_row.get(name) for name in QUERY_COLUMNS}
        record.update(tw.product_codes(pr_key))
        for merged, trackwise, salesforce in MERGED_CODE_COLUMNS:
            salesforce_value = canon(sf_codes[case].get(salesforce)) if case in sf_codes else None
            record[merged] = canon(record.get(trackwise)) or salesforce_value
        record[PR_ID] = int(pr_key) if pr_key.isdigit() else pr_key
        record[SOURCE_IDENTIFIER] = source
        record[SOURCE_IDENTIFIER_RAW] = case or source
        record[PRODUCT_IS_DUPLICATED] = YES if pr_key in tw.product_duplicates else NO
        record[CODES_IS_DUPLICATED] = YES if pr_key in tw.codes_duplicates else NO
        out.append({name: record.get(name) for name in FACT_COMPLAINT_COLUMNS})
    return out
