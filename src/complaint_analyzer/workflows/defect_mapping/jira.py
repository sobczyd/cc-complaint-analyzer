"""Reusable Jira corpus of Nurse Call defects and RCAs.

MCP tools can only be called by an agent, so the split mirrors the rest of the repo: Python
plans the fetch and normalizes what comes back, the agent does the Jira calls. ``plan`` writes
the JQL and field list; the agent saves each raw tool result under ``raw\\``; ``normalize``
turns those into ``issues.jsonl`` and ``issues.xlsx``.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

MANIFEST = "manifest.json"
RAW_DIR = "raw"
ISSUES_FILE = "issues.jsonl"
WORKBOOK_FILE = "issues.xlsx"
COMMENT_SUMMARY_FIELD = "comment_summary"

# Custom field ids confirmed against NC-24878 (Defect_CC) and RCA-1823 / RCA-1942.
DEFECT_FIELDS: dict[str, str] = {
    "impact_description": "customfield_10602",
    "version_reported": "customfield_14726",
    "set_up": "customfield_10680",
    "steps_taken": "customfield_10685",
    "expected_results": "customfield_10679",
    "actual_results": "customfield_10673",
    "work_around": "customfield_10688",
    "requirements": "customfield_14004",
    "direct_tests": "customfield_10607",
    "regression_tests": "customfield_10611",
    "crm_case_number": "customfield_10693",
    "reported_in_project": "customfield_10635",
    "reported_in_stage": "customfield_10674",
}
RCA_FIELDS: dict[str, str] = {
    "troubleshooting_steps": "customfield_14721",
    "troubleshooting_results": "customfield_14722",
    "server_details": "customfield_14723",
    "investigation_details": "customfield_10762",
    "root_cause_summary": "customfield_10765",
    "root_cause_trend_code": "customfield_10766",
    "rca_review_comments": "customfield_11027",
    "verification_summary": "customfield_11029",
    "crm_case_number": "customfield_10693",
    "version_reported": "customfield_14726",
}
# Custom field display names, for responses fetched with the evidence view.
FIELD_LABELS: dict[str, str] = {
    "impact_description": "Impact Description",
    "version_reported": "Reported in version",
    "set_up": "Set Up",
    "steps_taken": "Steps Taken",
    "expected_results": "Expected Results",
    "actual_results": "Actual Results",
    "work_around": "Work Around",
    "requirements": "Requirements",
    "direct_tests": "Direct Tests",
    "regression_tests": "Regression Tests",
    "crm_case_number": "CRM Case Number",
    "reported_in_project": "Reported In Project",
    "reported_in_stage": "Reported In Stage",
    "troubleshooting_steps": "Troubleshooting Steps",
    "troubleshooting_results": "Troubleshooting Results",
    "server_details": "Server Details",
    "investigation_details": "Investigation Details",
    "root_cause_summary": "Root Cause Summary",
    "root_cause_trend_code": "Root Cause Trend Code",
    "rca_review_comments": "RCA Review Comments",
    "verification_summary": "Verification Summary",
}
BASE_FIELDS = ("summary", "description", "status", "issuetype", "created", "updated", "labels")
TEXT_COLUMNS = (
    "issue_key",
    "issue_type",
    "project",
    "summary",
    "status",
    "created",
    "updated",
    "version_reported",
    "version_fix",
    "version_affects",
    "crm_case_number",
    "description",
    COMMENT_SUMMARY_FIELD,
)

PROJECTS: dict[str, dict[str, Any]] = {
    "defect": {
        "project": "NC",
        "issue_type": "Defect_CC",
        "fields": DEFECT_FIELDS,
        "jql": (
            'project = NC AND issuetype = "Defect_CC" '
            'AND (fixVersion ~ "4." OR "Reported in version" ~ "4.") '
            "ORDER BY created DESC"
        ),
    },
    "rca": {
        "project": "RCA",
        "issue_type": "Root Cause Analysis",
        "fields": RCA_FIELDS,
        "jql": 'project = RCA AND issuetype = "Root Cause Analysis" ORDER BY created DESC',
    },
}


class JiraCorpusError(Exception):
    """Raised for an unusable corpus directory or raw page."""


# -- text -----------------------------------------------------------------------------------


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("br", "p", "li", "tr", "div", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")


def html_to_text(value: str) -> str:
    """Flatten Jira's HTML field bodies to plain text, keeping line structure."""
    parser = _Text()
    parser.feed(value)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def as_text(value: Any) -> str:
    """Render any Jira field value (string, option, user, list, ADF) as plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return html_to_text(value) if "<" in value else value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(part for part in (as_text(item) for item in value) if part)
    if isinstance(value, dict):
        for key in ("name", "value", "displayName", "text"):
            if isinstance(value.get(key), str):
                return value[key].strip()
        if "content" in value:  # Atlassian document format
            return as_text(value["content"])
        return ""
    return str(value)


# -- versions -------------------------------------------------------------------------------

_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_version(value: Any) -> tuple[int, int, int] | None:
    """First ``x.y.z`` in a version string, as a comparable tuple.

    Handles ``Voalte Nurse Call 4.0.405``, ``NC 4.1.200`` and ``PRJ01099 - NNC 4.2.000``.
    """
    text = as_text(value)
    if not text:
        return None
    for candidate in re.split(r"[,;]", text):
        match = _VERSION.search(candidate)
        if match:
            return tuple(int(part) for part in match.groups())  # type: ignore[return-value]
    return None


def parse_versions(value: Any) -> list[tuple[int, int, int]]:
    """Every ``x.y.z`` found in a (possibly multi-valued) version field."""
    items = value if isinstance(value, list) else re.split(r"[,;]", as_text(value))
    found: list[tuple[int, int, int]] = []
    for item in items:
        version = parse_version(item)
        if version is not None and version not in found:
            found.append(version)
    return found


# -- case numbers ---------------------------------------------------------------------------

_CASE = re.compile(r"\d{5,8}")


def parse_case_numbers(value: Any) -> list[str]:
    """Case numbers from a free-text CRM field.

    Handles ``00979158 00980526``, ``00543751 & 00543522``, ``01074804/01083150``,
    ``00218496 - Service Cloud`` and short numbers such as ``1067661`` (padded to 8).
    """
    text = as_text(value)
    numbers: list[str] = []
    for match in _CASE.findall(text):
        number = match.zfill(8)
        if number not in numbers:
            numbers.append(number)
    return numbers


# -- raw pages ------------------------------------------------------------------------------


def _issue_nodes(payload: Any) -> Iterator[dict[str, Any]]:
    """Yield issue objects from any shape an Atlassian MCP tool returns."""
    if isinstance(payload, list):
        for item in payload:
            yield from _issue_nodes(item)
        return
    if not isinstance(payload, dict):
        return
    if "key" in payload and isinstance(payload.get("fields"), dict):
        yield payload
        return
    for key in ("data", "issues", "nodes", "results", "values"):
        if key in payload:
            yield from _issue_nodes(payload[key])


def _parse_json_stream(text: str, path: Path) -> list[Any]:
    """Parse one or more concatenated JSON values (MCP results are sometimes offloaded that way)."""
    decoder = json.JSONDecoder()
    values: list[Any] = []
    position = 0
    while position < len(text):
        while position < len(text) and text[position] in " \r\n\t":
            position += 1
        if position >= len(text):
            break
        try:
            value, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError as exc:
            raise JiraCorpusError(f"{path} is not valid JSON: {exc}") from None
        values.append(value)
    return values


def _merge_issue(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Combine two copies of one issue; a non-empty field never loses to an empty one.

    Pages fetched for different field sets (for example the field pass and a later
    comments-only pass) are merged instead of overwriting each other.
    """
    merged = dict(existing)
    fields = dict(existing.get("fields") or {})
    for name, value in (incoming.get("fields") or {}).items():
        if value in (None, "", [], {}) and name in fields:
            continue
        fields[name] = value
    merged["fields"] = fields
    return merged


def read_raw_pages(directory: Path) -> list[dict[str, Any]]:
    """Every issue found in ``raw\\*.json``, merged by issue key across pages."""
    raw_dir = directory / RAW_DIR
    if not raw_dir.is_dir():
        raise JiraCorpusError(f"no raw directory: {raw_dir}")
    issues: dict[str, dict[str, Any]] = {}
    for path in sorted(raw_dir.glob("*.json")):
        for payload in _parse_json_stream(path.read_text(encoding="utf-8"), path):
            for issue in _issue_nodes(payload):
                key = str(issue["key"])
                issues[key] = _merge_issue(issues[key], issue) if key in issues else issue
    if not issues:
        raise JiraCorpusError(f"no issues found in {raw_dir}")
    return [issues[key] for key in sorted(issues, key=_key_sort)]


def _key_sort(key: str) -> tuple[str, int]:
    project, _, number = key.partition("-")
    return project, int(number) if number.isdigit() else 0


def _field_value(fields: dict[str, Any], name: str, field_id: str) -> Any:
    """Read a custom field from either a raw response (by id) or an evidence view (by name)."""
    if field_id in fields:
        return fields[field_id]
    custom = fields.get("customFields")
    if isinstance(custom, dict):
        entry = custom.get(FIELD_LABELS.get(name, name))
        if isinstance(entry, dict) and "value" in entry:
            return entry.get("value")
        if entry is not None:
            return entry
    return None


def normalize_issue(issue: dict[str, Any], *, field_map: dict[str, str]) -> dict[str, Any]:
    """One raw Jira issue as a flat record of plain-text fields."""
    fields = issue.get("fields") or {}
    key = str(issue["key"])
    record: dict[str, Any] = {
        "issue_key": key,
        "project": key.partition("-")[0],
        "issue_type": as_text(fields.get("issuetype")),
        "summary": as_text(fields.get("summary")),
        "status": as_text(fields.get("status")),
        "created": as_text(fields.get("created")),
        "updated": as_text(fields.get("updated")),
        "labels": as_text(fields.get("labels")),
        "description": as_text(fields.get("description")),
        "version_fix": as_text(fields.get("fixVersions")),
        "version_affects": as_text(fields.get("versions")),
    }
    for name, field_id in field_map.items():
        record[name] = as_text(_field_value(fields, name, field_id))
    record["case_numbers"] = parse_case_numbers(record.get("crm_case_number", ""))
    record["versions_reported"] = [list(v) for v in parse_versions(record.get("version_reported", ""))]
    record["versions_fix"] = [list(v) for v in parse_versions(record.get("version_fix", ""))]
    record["comments"] = _comments(fields)
    record.setdefault(COMMENT_SUMMARY_FIELD, "")
    return record


def _comments(fields: dict[str, Any]) -> list[str]:
    comment = fields.get("comment")
    items: Iterable[Any] = ()
    if isinstance(comment, dict):
        items = comment.get("comments") or []
    elif isinstance(comment, list):
        items = comment
    texts = []
    for item in items:
        body = as_text(item.get("body") if isinstance(item, dict) else item)
        if body:
            texts.append(body)
    return texts


# -- commands -------------------------------------------------------------------------------


def plan(out_dir: Path, *, kind: str, jql: str | None = None) -> dict[str, Any]:
    """Create the corpus directory and record the JQL and field ids the agent must request."""
    if kind not in PROJECTS:
        raise JiraCorpusError(f"unknown kind '{kind}' (expected: {', '.join(PROJECTS)})")
    spec = PROJECTS[kind]
    field_ids = list(BASE_FIELDS) + ["fixVersions", "versions", "comment"] + sorted(set(spec["fields"].values()))
    manifest = {
        "kind": kind,
        "project": spec["project"],
        "issue_type": spec["issue_type"],
        "jql": jql or spec["jql"],
        "fields": field_ids,
        "field_map": spec["fields"],
        "raw_dir": RAW_DIR,
        "status": "planned",
    }
    (out_dir / RAW_DIR).mkdir(parents=True, exist_ok=True)
    (out_dir / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_manifest(directory: Path) -> dict[str, Any]:
    path = directory / MANIFEST
    if not path.is_file():
        raise JiraCorpusError(f"not a corpus directory (no {MANIFEST}): {directory}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_issues(directory: Path) -> list[dict[str, Any]]:
    path = directory / ISSUES_FILE
    if not path.is_file():
        raise JiraCorpusError(f"corpus is not normalized (no {ISSUES_FILE}): {directory}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_issues(directory: Path, issues: Sequence[dict[str, Any]]) -> None:
    with (directory / ISSUES_FILE).open("w", encoding="utf-8") as handle:
        for issue in issues:
            handle.write(json.dumps(issue, ensure_ascii=False) + "\n")
    _write_workbook(directory / WORKBOOK_FILE, issues)


def _write_workbook(path: Path, issues: Sequence[dict[str, Any]]) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "Issues"
    extra = [k for k in (issues[0] if issues else {}) if k not in TEXT_COLUMNS and k != "comments"]
    columns = list(TEXT_COLUMNS) + sorted(extra)
    sheet.append(columns)
    for issue in issues:
        sheet.append([_cell(issue.get(name)) for name in columns])
    book.save(path)


def _cell(value: Any) -> str:
    if isinstance(value, list):
        text = "\n".join(str(item) for item in value)
    else:
        text = str(value if value is not None else "")
    return ILLEGAL_CHARACTERS_RE.sub("", text)[:32000]


def normalize(directory: Path, *, summaries: Path | None = None) -> dict[str, Any]:
    """Turn the saved raw pages into ``issues.jsonl`` / ``issues.xlsx``.

    ``summaries`` is a harness ``results.jsonl`` of comment summaries; when given, each
    issue keeps its summary so the corpus stays reusable.
    """
    manifest = read_manifest(directory)
    field_map = manifest.get("field_map") or PROJECTS[manifest["kind"]]["fields"]
    issues = [normalize_issue(issue, field_map=field_map) for issue in read_raw_pages(directory)]
    if summaries is not None:
        issues = merge_comment_summaries(issues, summaries)
    write_issues(directory, issues)
    manifest.update(
        status="normalized",
        issue_count=len(issues),
        with_comments=sum(1 for issue in issues if issue["comments"]),
        with_case_numbers=sum(1 for issue in issues if issue["case_numbers"]),
        with_comment_summary=sum(1 for issue in issues if issue.get(COMMENT_SUMMARY_FIELD)),
    )
    (directory / MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        key: manifest[key]
        for key in ("kind", "issue_count", "with_comments", "with_case_numbers", "with_comment_summary")
    }


def merge_comment_summaries(issues: Sequence[dict[str, Any]], results: Path) -> list[dict[str, Any]]:
    """Attach ``comment_summary`` from a finalized harness run, keyed by issue key."""
    if not results.is_file():
        raise JiraCorpusError(f"results file not found: {results}")
    summaries: dict[str, str] = {}
    for line in results.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        values = entry.get("values") or {}
        if entry.get("status") == "ok" and entry.get("record_id"):
            text = values.get("summary", "")
            points = values.get("key_points") or []
            if points:
                text = (text + "\n" + "\n".join(f"- {point}" for point in points)).strip()
            summaries[str(entry["record_id"])] = text
    merged = []
    for issue in issues:
        issue = dict(issue)
        issue[COMMENT_SUMMARY_FIELD] = summaries.get(issue["issue_key"], issue.get(COMMENT_SUMMARY_FIELD, ""))
        merged.append(issue)
    return merged


def comment_dataset(directory: Path, out_path: Path) -> dict[str, Any]:
    """Write an xlsx of issues that have comments, as input for the comment-summary run."""
    issues = [issue for issue in read_issues(directory) if issue["comments"]]
    book = Workbook()
    sheet = book.active
    sheet.title = "Issues"
    sheet.append(["issue_key", "Issue Context"])
    for issue in issues:
        context = "\n".join(
            [
                f"issue_key: {issue['issue_key']}",
                f"summary: {issue['summary']}",
                f"status: {issue['status']}",
                "comments:",
                *(f"- {text}" for text in issue["comments"]),
            ]
        )
        sheet.append([issue["issue_key"], _cell(context)])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    book.save(out_path)
    return {"workbook": str(out_path), "issue_count": len(issues)}
