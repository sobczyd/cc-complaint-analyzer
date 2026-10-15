"""Versioned file exchange for completions produced by an interactive harness."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..analyses.base import Analysis, AnalysisError, parse_json_object
from ..run_paths import RunPaths, safe_component, utc_now
from ..settings import ConfigError
from .protocol import ChatRequest, ChatResponse

FORMAT_VERSION = 1


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"could not read {label} {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError(f"{label} must contain a JSON object: {path}")
    return payload


def _request_file_name(record_id: str) -> str:
    return safe_component(record_id) + ".json"


def _build_assignments(
    records: Sequence[dict[str, Any]],
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for offset in range(0, len(records), batch_size):
        number = len(assignments) + 1
        members = records[offset : offset + batch_size]
        assignments.append(
            {
                "assignment_id": f"batch-{number:03d}",
                "records": [
                    {
                        "record_id": item["record_id"],
                        "fingerprint": item["fingerprint"],
                        "request_file": item["request_file"],
                        "response_file": item["response_file"],
                    }
                    for item in members
                ],
            }
        )
    return assignments


def prepare_exchange(
    run_paths: RunPaths,
    requests: Sequence[ChatRequest],
    *,
    config_path: str,
    model: str,
    batch_size: int = 10,
    effective_limit: int | None = None,
) -> None:
    """Write a new exchange manifest and one immutable request file per record."""
    if run_paths.exchange_dir.exists():
        raise ConfigError(f"harness exchange already exists: {run_paths.exchange_dir}")
    if batch_size < 1:
        raise ConfigError("harness batch size must be at least 1")

    names = [_request_file_name(request.record_id) for request in requests]
    if len(names) != len(set(names)):
        raise ConfigError("record IDs collide after conversion to safe exchange filenames")

    records: list[dict[str, Any]] = []
    for request, file_name in zip(requests, names, strict=True):
        payload = {
            "format_version": FORMAT_VERSION,
            **request.request_payload(),
        }
        _write_json_atomic(run_paths.exchange_requests_dir / file_name, payload)
        records.append(
            {
                "record_id": request.record_id,
                "source_row": request.source_row,
                "fingerprint": request.fingerprint(),
                "request_file": file_name,
                "response_file": file_name,
            }
        )

    run_paths.exchange_responses_dir.mkdir(parents=True, exist_ok=True)
    assignments = _build_assignments(records, batch_size=batch_size)
    _write_json_atomic(
        run_paths.exchange_assignments_path,
        {
            "format_version": FORMAT_VERSION,
            "batch_size": batch_size,
            "record_count": len(records),
            "assignment_count": len(assignments),
            "assignments": assignments,
        },
    )
    _write_json_atomic(
        run_paths.exchange_manifest_path,
        {
            "format_version": FORMAT_VERSION,
            "prepared_at": utc_now().isoformat(),
            "config_path": config_path,
            "model": model,
            "batch_size": batch_size,
            "effective_limit": effective_limit,
            "assignments_file": run_paths.exchange_assignments_path.name,
            "records": records,
        },
    )


@dataclass(frozen=True)
class ExchangeInspection:
    """Result of validating a prepared harness exchange without writing artifacts."""

    responses: Mapping[str, ChatResponse]
    errors: tuple[str, ...]
    invalid_record_ids: tuple[str, ...]
    incomplete_assignment_ids: tuple[str, ...]
    record_count: int
    valid_response_count: int

    @property
    def ready(self) -> bool:
        return not self.errors

    def as_json(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "record_count": self.record_count,
            "valid_response_count": self.valid_response_count,
            "invalid_record_ids": list(self.invalid_record_ids),
            "incomplete_assignment_ids": list(self.incomplete_assignment_ids),
            "errors": list(self.errors),
        }


class ExchangeResponseClient:
    """Serve preflighted response files through the normal ``ChatClient`` seam."""

    def __init__(self, responses: Mapping[str, ChatResponse]) -> None:
        self._responses = dict(responses)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        try:
            return self._responses[request.fingerprint()]
        except KeyError:
            raise ConfigError(
                f"no preflighted harness response for record {request.record_id!r}"
            ) from None


def _assignment_index(
    run_paths: RunPaths,
    prepared: Mapping[str, dict[str, Any]],
) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    if not run_paths.exchange_assignments_path.is_file():
        legacy = _build_assignments(list(prepared.values()), batch_size=10)
        return {
            member["record_id"]: assignment["assignment_id"]
            for assignment in legacy
            for member in assignment["records"]
        }, []
    try:
        payload = _read_object(run_paths.exchange_assignments_path, label="exchange assignments")
    except ConfigError as exc:
        return {}, [str(exc)]
    if payload.get("format_version") != FORMAT_VERSION:
        errors.append("unsupported exchange assignments format version")
    raw_assignments = payload.get("assignments")
    if not isinstance(raw_assignments, list):
        return {}, [*errors, "exchange assignments field 'assignments' must be a list"]

    record_to_assignment: dict[str, str] = {}
    assignment_ids: set[str] = set()
    for assignment in raw_assignments:
        if not isinstance(assignment, dict):
            errors.append("exchange assignments contains a non-object assignment")
            continue
        assignment_id = assignment.get("assignment_id")
        if not isinstance(assignment_id, str) or not assignment_id:
            errors.append("exchange assignments contains an invalid assignment ID")
            continue
        if assignment_id in assignment_ids:
            errors.append(f"duplicate assignment ID: {assignment_id!r}")
            continue
        assignment_ids.add(assignment_id)
        members = assignment.get("records")
        if not isinstance(members, list) or not members:
            errors.append(f"{assignment_id}: records must be a non-empty list")
            continue
        for member in members:
            if not isinstance(member, dict):
                errors.append(f"{assignment_id}: contains a non-object record")
                continue
            record_id = member.get("record_id")
            if not isinstance(record_id, str) or record_id not in prepared:
                errors.append(f"{assignment_id}: contains unknown record {record_id!r}")
                continue
            if record_id in record_to_assignment:
                errors.append(f"{record_id}: assigned more than once")
                continue
            expected = prepared[record_id]
            for field in ("fingerprint", "request_file", "response_file"):
                if member.get(field) != expected.get(field):
                    errors.append(f"{record_id}: assignment {field} does not match manifest")
            record_to_assignment[record_id] = assignment_id

    for record_id in sorted(set(prepared) - set(record_to_assignment)):
        errors.append(f"{record_id}: record is not assigned")
    if payload.get("record_count") != len(prepared):
        errors.append("exchange assignments record count does not match manifest")
    if payload.get("assignment_count") != len(assignment_ids):
        errors.append("exchange assignments assignment count does not match contents")
    return record_to_assignment, errors


def _validated_content(
    content: object,
    *,
    analysis: Analysis,
    record_id: str,
) -> str:
    if isinstance(content, dict):
        payload = content
        rendered = json.dumps(content, ensure_ascii=False)
    elif isinstance(content, str) and content.strip():
        rendered = content
        try:
            payload = parse_json_object(content)
        except AnalysisError as exc:
            raise ConfigError(f"{record_id}: response content is invalid: {exc}") from exc
    else:
        raise ConfigError(
            f"{record_id}: response content must be a non-empty string or object"
        )
    try:
        analysis.result_model.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigError(f"{record_id}: response content failed schema validation: {details}") from exc
    return rendered


def inspect_exchange(
    run_paths: RunPaths,
    requests: Sequence[ChatRequest],
    *,
    model: str,
    analysis: Analysis,
) -> ExchangeInspection:
    """Validate an exchange without creating final run artifacts."""
    manifest = _read_object(run_paths.exchange_manifest_path, label="exchange manifest")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ConfigError(
            f"unsupported exchange format version: {manifest.get('format_version')!r}"
        )
    if manifest.get("model") != model:
        raise ConfigError(
            f"harness model changed since preparation: expected {manifest.get('model')!r}, "
            f"got {model!r}"
        )

    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        raise ConfigError("exchange manifest field 'records' must be a list")

    prepared: dict[str, dict[str, Any]] = {}
    for item in raw_records:
        if not isinstance(item, dict):
            raise ConfigError("exchange manifest contains a non-object record")
        record_id = item.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            raise ConfigError("exchange manifest contains an invalid record ID")
        if record_id in prepared:
            raise ConfigError(f"duplicate record in exchange manifest: {record_id!r}")
        prepared[record_id] = item

    current = {request.record_id: request for request in requests}
    if set(prepared) != set(current):
        missing = sorted(set(prepared) - set(current))
        added = sorted(set(current) - set(prepared))
        raise ConfigError(
            "selection changed since harness preparation"
            + (f"; missing now: {', '.join(missing)}" if missing else "")
            + (f"; newly selected: {', '.join(added)}" if added else "")
        )

    assignment_by_record, assignment_errors = _assignment_index(run_paths, prepared)
    expected_files: set[str] = set()
    responses: dict[str, ChatResponse] = {}
    errors: list[str] = list(assignment_errors)
    invalid_record_ids: set[str] = set()
    for record_id, request in current.items():
        record_error_count = len(errors)
        item = prepared[record_id]
        expected_fingerprint = request.fingerprint()
        if item.get("source_row") != request.source_row:
            errors.append(f"{record_id}: source row changed")
            invalid_record_ids.add(record_id)
        if item.get("fingerprint") != expected_fingerprint:
            errors.append(f"{record_id}: request fingerprint changed")
            invalid_record_ids.add(record_id)

        request_file = item.get("request_file")
        if not isinstance(request_file, str) or Path(request_file).name != request_file:
            errors.append(f"{record_id}: invalid request filename")
            invalid_record_ids.add(record_id)
        else:
            request_path = run_paths.exchange_requests_dir / request_file
            if not request_path.is_file():
                errors.append(f"{record_id}: prepared request file is missing")
                invalid_record_ids.add(record_id)
            else:
                try:
                    exported = _read_object(
                        request_path,
                        label=f"prepared request for {record_id}",
                    )
                except ConfigError as exc:
                    errors.append(str(exc))
                    invalid_record_ids.add(record_id)
                else:
                    expected_request = {
                        "format_version": FORMAT_VERSION,
                        **request.request_payload(),
                    }
                    if exported != expected_request:
                        errors.append(f"{record_id}: prepared request file changed")
                        invalid_record_ids.add(record_id)

        response_file = item.get("response_file")
        if not isinstance(response_file, str) or Path(response_file).name != response_file:
            errors.append(f"{record_id}: invalid response filename")
            invalid_record_ids.add(record_id)
            continue
        expected_files.add(response_file)
        path = run_paths.exchange_responses_dir / response_file
        if not path.is_file():
            errors.append(f"{record_id}: response is missing")
            invalid_record_ids.add(record_id)
            continue
        try:
            response = _read_object(path, label=f"response for {record_id}")
        except ConfigError as exc:
            errors.append(str(exc))
            invalid_record_ids.add(record_id)
            continue
        if response.get("format_version") != FORMAT_VERSION:
            errors.append(f"{record_id}: unsupported response format version")
            invalid_record_ids.add(record_id)
        if response.get("record_id") != record_id:
            errors.append(f"{record_id}: response record ID does not match")
            invalid_record_ids.add(record_id)
        if response.get("fingerprint") != expected_fingerprint:
            errors.append(f"{record_id}: response fingerprint does not match")
            invalid_record_ids.add(record_id)
        response_model = response.get("model")
        if response_model != model:
            errors.append(f"{record_id}: response model does not match")
            invalid_record_ids.add(record_id)
        try:
            rendered = _validated_content(
                response.get("content"),
                analysis=analysis,
                record_id=record_id,
            )
        except ConfigError as exc:
            errors.append(str(exc))
            invalid_record_ids.add(record_id)
        if len(errors) == record_error_count:
            responses[expected_fingerprint] = ChatResponse(
                content=rendered,
                model=model,
                raw={
                    "backend": "harness",
                    "response_file": str(path),
                },
            )

    if run_paths.exchange_responses_dir.is_dir():
        actual_files = {
            entry.name
            for entry in run_paths.exchange_responses_dir.iterdir()
            if entry.is_file() and entry.suffix.lower() == ".json"
        }
        for extra in sorted(actual_files - expected_files):
            errors.append(f"unexpected response file: {extra}")

    incomplete_assignment_ids = sorted(
        {
            assignment_by_record[record_id]
            for record_id in invalid_record_ids
            if record_id in assignment_by_record
        }
    )
    return ExchangeInspection(
        responses=responses,
        errors=tuple(errors),
        invalid_record_ids=tuple(sorted(invalid_record_ids)),
        incomplete_assignment_ids=tuple(incomplete_assignment_ids),
        record_count=len(current),
        valid_response_count=len(responses),
    )


def load_exchange_client(
    run_paths: RunPaths,
    requests: Sequence[ChatRequest],
    *,
    model: str,
    analysis: Analysis,
) -> ExchangeResponseClient:
    """Validate the complete exchange before any result or call artifact is written."""
    inspection = inspect_exchange(
        run_paths,
        requests,
        model=model,
        analysis=analysis,
    )
    if inspection.errors:
        raise ConfigError(
            "harness exchange is not ready:\n- " + "\n- ".join(inspection.errors)
        )
    return ExchangeResponseClient(inspection.responses)


def publish_response(
    run_paths: RunPaths,
    candidate_path: Path,
    *,
    assignment_id: str,
    model: str,
    analysis: Analysis,
) -> Path:
    """Validate and atomically publish one assignment-scoped response."""
    manifest = _read_object(run_paths.exchange_manifest_path, label="exchange manifest")
    if manifest.get("model") != model:
        raise ConfigError(
            f"harness model changed since preparation: expected {manifest.get('model')!r}, "
            f"got {model!r}"
        )
    if not run_paths.exchange_assignments_path.is_file():
        raise ConfigError("response publication requires persisted exchange assignments")
    raw_records = manifest.get("records")
    if not isinstance(raw_records, list):
        raise ConfigError("exchange manifest field 'records' must be a list")
    prepared = {
        item["record_id"]: item
        for item in raw_records
        if isinstance(item, dict) and isinstance(item.get("record_id"), str)
    }
    assignment_by_record, assignment_errors = _assignment_index(run_paths, prepared)
    if assignment_errors:
        raise ConfigError("invalid exchange assignments:\n- " + "\n- ".join(assignment_errors))

    candidate = _read_object(candidate_path, label="candidate response")
    record_id = candidate.get("record_id")
    if not isinstance(record_id, str) or record_id not in prepared:
        raise ConfigError(f"candidate response has unknown record ID: {record_id!r}")
    if assignment_by_record.get(record_id) != assignment_id:
        raise ConfigError(
            f"{record_id}: belongs to {assignment_by_record.get(record_id)!r}, "
            f"not {assignment_id!r}"
        )
    item = prepared[record_id]
    expected_fingerprint = item.get("fingerprint")
    request_file = item.get("request_file")
    if not isinstance(request_file, str) or Path(request_file).name != request_file:
        raise ConfigError(f"{record_id}: invalid request filename")
    request = _read_object(
        run_paths.exchange_requests_dir / request_file,
        label=f"prepared request for {record_id}",
    )
    if request.get("record_id") != record_id:
        raise ConfigError(f"{record_id}: prepared request record ID does not match")
    if request.get("fingerprint") != expected_fingerprint:
        raise ConfigError(f"{record_id}: prepared request fingerprint does not match")
    if request.get("model") != model:
        raise ConfigError(f"{record_id}: prepared request model does not match")
    checks = {
        "format_version": FORMAT_VERSION,
        "fingerprint": expected_fingerprint,
        "model": model,
    }
    for field, expected in checks.items():
        if candidate.get(field) != expected:
            raise ConfigError(f"{record_id}: candidate {field} does not match")
    _validated_content(candidate.get("content"), analysis=analysis, record_id=record_id)

    response_file = item.get("response_file")
    if not isinstance(response_file, str) or Path(response_file).name != response_file:
        raise ConfigError(f"{record_id}: invalid response filename")
    destination = run_paths.exchange_responses_dir / response_file
    if candidate_path.resolve() == destination.resolve():
        raise ConfigError("candidate response must not be the final response path")
    _write_json_atomic(destination, candidate)
    candidate_path.unlink()
    return destination
