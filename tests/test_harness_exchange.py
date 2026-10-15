"""CLI coverage for the two-phase harness completion backend."""

from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook as OpenpyxlWorkbook

from complaint_analyzer.__main__ import EXIT_CONFIG, EXIT_OK, main

from conftest import SHEET, rca_payload, read_jsonl, sheet_rows


def _write_config(tmp_path: Path, workbook: Path, runs_dir: Path) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(
        f"""
dataset:
  path: {workbook.as_posix()}
  sheet: {SHEET}
  id_field: Record ID
  fields:
    - Service description
    - Troubleshooting
    - Resolution
  filters:
    - field: Status
      operator: eq
      value: Closed
  limit: null
analysis:
  name: rca
  version: v1
cache:
  mode: "off"
output:
  runs_dir: {runs_dir.as_posix()}
""",
        encoding="utf-8",
    )
    return path


def _prepare(config: Path, run_id: str = "harness", *extra: str) -> int:
    return main(
        [
            "--config",
            str(config),
            "--backend",
            "harness",
            "--prepare",
            "--run-id",
            run_id,
            "--no-echo",
            *extra,
        ]
    )


def _write_responses(run_dir: Path, *, mutate=None) -> None:
    requests_dir = run_dir / "exchange" / "requests"
    responses_dir = run_dir / "exchange" / "responses"
    for request_path in requests_dir.glob("*.json"):
        request = json.loads(request_path.read_text(encoding="utf-8"))
        response = {
            "format_version": 1,
            "record_id": request["record_id"],
            "fingerprint": request["fingerprint"],
            "model": request["model"],
            "content": rca_payload(),
        }
        if mutate is not None:
            mutate(response)
        (responses_dir / request_path.name).write_text(
            json.dumps(response),
            encoding="utf-8",
        )


def _finalize(config: Path, run_id: str = "harness", *extra: str) -> int:
    return main(
        [
            "--config",
            str(config),
            "--backend",
            "harness",
            "--finalize",
            "--run-id",
            run_id,
            "--no-echo",
            *extra,
        ]
    )


def test_prepare_needs_no_credentials_and_exports_requests(
    tmp_path: Path, workbook_path: Path, monkeypatch
) -> None:
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)

    assert _prepare(config) == EXIT_OK

    run_dir = runs_dir / "harness"
    requests = sorted((run_dir / "exchange" / "requests").glob("*.json"))
    assert len(requests) == 3
    assert (run_dir / "exchange" / "manifest.json").exists()
    assert not (run_dir / "results.jsonl").exists()
    assert not (run_dir / "analyzed.xlsx").exists()
    assert "harness.prepared" in (run_dir / "run.log").read_text(encoding="utf-8")


def test_prepare_refuses_to_overwrite_an_existing_run(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")
    assert _prepare(config) == EXIT_OK
    assert _prepare(config) == EXIT_CONFIG
    assert "already exists" in capsys.readouterr().err


def test_finalize_requires_every_response_before_writing_results(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK

    assert _finalize(config) == EXIT_CONFIG
    assert "response is missing" in capsys.readouterr().err
    assert not (runs_dir / "harness" / "results.jsonl").exists()


def test_finalize_rejects_a_stale_response(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    _write_responses(
        runs_dir / "harness",
        mutate=lambda response: response.update(fingerprint="stale"),
    )

    assert _finalize(config) == EXIT_CONFIG
    assert "fingerprint does not match" in capsys.readouterr().err
    assert not (runs_dir / "harness" / "results.jsonl").exists()


def test_finalize_rejects_an_unexpected_response_file(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    run_dir = runs_dir / "harness"
    _write_responses(run_dir)
    (run_dir / "exchange" / "responses" / "extra.json").write_text("{}", encoding="utf-8")

    assert _finalize(config) == EXIT_CONFIG
    assert "unexpected response file" in capsys.readouterr().err
    assert not (run_dir / "results.jsonl").exists()


def test_finalize_rejects_malformed_response_json(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    run_dir = runs_dir / "harness"
    _write_responses(run_dir)
    first = next((run_dir / "exchange" / "responses").glob("*.json"))
    first.write_text("{not-json", encoding="utf-8")

    assert _finalize(config) == EXIT_CONFIG
    assert "not valid JSON" in capsys.readouterr().err
    assert not (run_dir / "results.jsonl").exists()


def test_finalize_rejects_selection_drift(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    _write_responses(runs_dir / "harness")
    config.write_text(
        config.read_text(encoding="utf-8").replace("limit: null", "limit: 2"),
        encoding="utf-8",
    )

    assert _finalize(config) == EXIT_CONFIG
    assert "selection changed" in capsys.readouterr().err
    assert not (runs_dir / "harness" / "results.jsonl").exists()


def test_finalize_rejects_a_modified_prepared_request(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    run_dir = runs_dir / "harness"
    _write_responses(run_dir)
    request_path = next((run_dir / "exchange" / "requests").glob("*.json"))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["messages"][1]["content"] = "changed"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    assert _finalize(config) == EXIT_CONFIG
    assert "prepared request file changed" in capsys.readouterr().err
    assert not (run_dir / "results.jsonl").exists()


def test_finalize_writes_normal_artifacts_and_backend_provenance(
    tmp_path: Path, workbook_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    run_dir = runs_dir / "harness"
    _write_responses(run_dir)

    assert _finalize(config) == EXIT_OK

    assert len(read_jsonl(run_dir / "results.jsonl")) == 3
    assert len(sheet_rows(run_dir / "analyzed.xlsx")) == 4
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"] == {
        "type": "harness",
        "model": "copilot-harness",
    }
    assert manifest["results"]["failed"] == 0
    assert manifest["results"]["total_tokens"] == 0
    assert len(list((run_dir / "calls" / "rca-v1").iterdir())) == 3
    assert _finalize(config) == EXIT_CONFIG


def test_prepare_writes_deterministic_assignments_with_partial_final_batch(
    tmp_path: Path, workbook_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)

    assert _prepare(config, "assigned", "--batch-size", "2") == EXIT_OK

    payload = json.loads(
        (runs_dir / "assigned" / "exchange" / "assignments.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["batch_size"] == 2
    assert payload["record_count"] == 3
    assert payload["assignment_count"] == 2
    assert [
        [record["record_id"] for record in assignment["records"]]
        for assignment in payload["assignments"]
    ] == [["R-001", "R-002"], ["R-004"]]


def test_check_reports_missing_records_and_assignments(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config, "status", "--batch-size", "2") == EXIT_OK
    capsys.readouterr()

    exit_code = main(
        [
            "--config",
            str(config),
            "--backend",
            "harness",
            "--check",
            "--run-id",
            "status",
            "--no-echo",
        ]
    )

    assert exit_code == 1
    status = json.loads(capsys.readouterr().out)
    assert status["ready"] is False
    assert status["valid_response_count"] == 0
    assert status["invalid_record_ids"] == ["R-001", "R-002", "R-004"]
    assert status["incomplete_assignment_ids"] == ["batch-001", "batch-002"]


def test_check_rejects_overlapping_assignments(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config, "overlap", "--batch-size", "2") == EXIT_OK
    assignments_path = runs_dir / "overlap" / "exchange" / "assignments.json"
    assignments = json.loads(assignments_path.read_text(encoding="utf-8"))
    assignments["assignments"][1]["records"].append(
        assignments["assignments"][0]["records"][0]
    )
    assignments_path.write_text(json.dumps(assignments), encoding="utf-8")
    capsys.readouterr()

    exit_code = main(
        [
            "--config",
            str(config),
            "--backend",
            "harness",
            "--check",
            "--run-id",
            "overlap",
            "--no-echo",
        ]
    )

    assert exit_code == 1
    status = json.loads(capsys.readouterr().out)
    assert any("assigned more than once" in error for error in status["errors"])


def test_finalize_rejects_schema_invalid_content_before_writing_artifacts(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config) == EXIT_OK
    run_dir = runs_dir / "harness"
    _write_responses(
        run_dir,
        mutate=lambda response: response["content"].update(cause_status="not-valid"),
    )

    assert _finalize(config) == EXIT_CONFIG
    assert "failed schema validation" in capsys.readouterr().err
    assert not (run_dir / "results.jsonl").exists()
    assert not (run_dir / "calls").exists()
    assert not (run_dir / "analyzed.xlsx").exists()
    assert not (run_dir / "manifest.json").exists()


def test_cli_limit_override_is_recorded_in_final_manifest(
    tmp_path: Path, workbook_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config, "limited", "--limit", "2") == EXIT_OK
    _write_responses(runs_dir / "limited")

    assert _finalize(config, "limited", "--limit", "2") == EXIT_OK

    manifest = json.loads(
        (runs_dir / "limited" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["dataset"]["limit"] == 2
    assert manifest["selection"]["analyzed_rows"] == 2


def test_incomplete_finalization_artifacts_are_rebuilt(
    tmp_path: Path, workbook_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config, "retry") == EXIT_OK
    run_dir = runs_dir / "retry"
    _write_responses(run_dir)
    (run_dir / "results.jsonl").write_text("partial\n", encoding="utf-8")
    (run_dir / "analyzed.xlsx").write_text("partial", encoding="utf-8")
    (run_dir / "manifest.json").write_text('{"partial": true}', encoding="utf-8")
    stale_call = run_dir / "calls" / "rca-v1" / "stale"
    stale_call.mkdir(parents=True)

    assert _finalize(config, "retry") == EXIT_OK

    assert len(read_jsonl(run_dir / "results.jsonl")) == 3
    assert len(sheet_rows(run_dir / "analyzed.xlsx")) == 4
    assert not stale_call.exists()
    assert (run_dir / "manifest.json").exists()


def test_publish_response_enforces_assignment_and_validates_schema(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    assert _prepare(config, "publish", "--batch-size", "1") == EXIT_OK
    run_dir = runs_dir / "publish"
    request = json.loads(
        (run_dir / "exchange" / "requests" / "R-001.json").read_text(encoding="utf-8")
    )
    candidate = tmp_path / "candidate.tmp"
    candidate.write_text(
        json.dumps(
            {
                "format_version": 1,
                "record_id": "R-001",
                "fingerprint": request["fingerprint"],
                "model": request["model"],
                "content": rca_payload(),
            }
        ),
        encoding="utf-8",
    )

    base_args = [
        "--config",
        str(config),
        "--backend",
        "harness",
        "--publish-response",
        str(candidate),
        "--run-id",
        "publish",
        "--no-echo",
    ]
    assert main([*base_args, "--assignment-id", "batch-002"]) == EXIT_CONFIG
    assert "belongs to 'batch-001'" in capsys.readouterr().err
    assert main([*base_args, "--assignment-id", "batch-001"]) == EXIT_OK
    assert (run_dir / "exchange" / "responses" / "R-001.json").exists()
    assert not candidate.exists()


def test_one_hundred_record_harness_run_has_ten_assignments(
    tmp_path: Path,
) -> None:
    workbook = tmp_path / "hundred.xlsx"
    book = OpenpyxlWorkbook()
    sheet = book.active
    sheet.title = SHEET
    sheet.append(
        [
            "Record ID",
            "Status",
            "Service description",
            "Troubleshooting",
            "Resolution",
        ]
    )
    for number in range(1, 101):
        sheet.append(
            [
                f"R-{number:03d}",
                "Closed",
                f"Symptom {number}",
                f"Checked record {number}",
                f"Resolved record {number}",
            ]
        )
    book.save(workbook)
    book.close()

    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook, runs_dir)
    assert _prepare(
        config,
        "hundred",
        "--limit",
        "100",
        "--batch-size",
        "10",
    ) == EXIT_OK
    run_dir = runs_dir / "hundred"
    assignments = json.loads(
        (run_dir / "exchange" / "assignments.json").read_text(encoding="utf-8")
    )
    assert assignments["assignment_count"] == 10
    assert all(len(item["records"]) == 10 for item in assignments["assignments"])
    _write_responses(run_dir)

    assert _finalize(config, "hundred", "--limit", "100") == EXIT_OK

    assert len(read_jsonl(run_dir / "results.jsonl")) == 100
    assert len(list((run_dir / "calls" / "rca-v1").iterdir())) == 100
    assert len(sheet_rows(run_dir / "analyzed.xlsx")) == 101


def test_backend_phase_combinations_are_validated(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")

    assert main(["--config", str(config), "--backend", "harness"]) == EXIT_CONFIG
    assert "requires exactly one" in capsys.readouterr().err

    assert main(["--config", str(config), "--prepare"]) == EXIT_CONFIG
    assert "require --backend harness" in capsys.readouterr().err

    assert (
        main(["--config", str(config), "--backend", "harness", "--finalize"])
        == EXIT_CONFIG
    )
    assert "requires --run-id" in capsys.readouterr().err
