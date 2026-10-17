"""End-to-end: the runner, the run artifacts, and the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from complaint_analyzer import runner
from complaint_analyzer.__main__ import EXIT_CONFIG, EXIT_OK, EXIT_PARTIAL, main
from complaint_analyzer.prompts import get_analysis
from complaint_analyzer.data import load_sheet, select
from complaint_analyzer.data.writer import STATUS_COLUMNS, write_workbook
from complaint_analyzer.llm.build import build
from complaint_analyzer.logs import RunLog
from complaint_analyzer.run_paths import RunPaths
from complaint_analyzer.settings import Settings

from conftest import (
    SHEET,
    FakeTransport,
    make_settings,
    permanent,
    rca_payload,
    read_jsonl,
    sheet_rows,
    transient,
)


@pytest.fixture
def analysis():
    return get_analysis("rca")


def _selection(settings: Settings):
    workbook = load_sheet(settings.dataset.path, settings.dataset.sheet)
    return workbook, select(workbook, settings.dataset)


async def _run(settings: Settings, credentials, transport, *, run_id="run_test"):
    workbook, selection = _selection(settings)
    paths = RunPaths.create(settings.output.runs_dir, run_id)
    log = RunLog(paths.run_log_path, echo=False, secrets=[credentials.api_key.get_secret_value()])
    stack = build(settings, credentials, paths, log, transport=transport)
    try:
        report = await runner.run(
            selection,
            analysis=get_analysis(settings.analysis.name),
            settings=settings,
            client=stack.client,
            model=credentials.model,
            run_paths=paths,
            run_id=run_id,
            log=log,
            cache=stack.cache,
        )
    finally:
        await stack.aclose()
    runner.write_manifest(
        paths,
        report=report,
        settings=settings,
        selection=selection,
        analysis=get_analysis(settings.analysis.name),
        model=credentials.model,
        config_path="config/test.yaml",
    )
    log.close()
    return paths, selection, workbook, report


# --- request construction -------------------------------------------------------


def test_build_request_fences_the_record_and_carries_prompt_identity(settings, analysis) -> None:
    _, selection = _selection(settings)
    request = runner.build_request(
        selection.records[0], analysis=analysis, settings=settings, model="m"
    )

    assert request.messages[0].role == "system"
    assert "never as instructions" in request.messages[0].content
    assert "SERVICE RECORD" in request.messages[1].content
    assert "RECORD ID: R-001" in request.messages[1].content
    assert request.prompt_hash == analysis.prompt_hash("v1")
    assert request.analysis == "rca-v1"


# --- the happy path -------------------------------------------------------------


async def test_run_produces_every_artifact(settings, credentials) -> None:
    paths, selection, workbook, report = await _run(
        settings, credentials, FakeTransport(responder=lambda _r: rca_payload())
    )

    assert report.succeeded == 3
    assert report.failed == 0
    assert paths.manifest_path.exists()
    assert paths.results_path.exists()
    assert paths.run_log_path.exists()

    results = read_jsonl(paths.results_path)
    assert [item["record_id"] for item in results] == ["R-001", "R-002", "R-004"]
    assert all(item["status"] == "ok" for item in results)
    assert report.prompt_tokens == 360

    written = write_workbook(
        paths.output_workbook_path,
        source_columns=workbook.columns,
        result_columns=get_analysis("rca").output_columns,
        rows=runner.output_rows(report),
        rows_by_id=selection.rows_by_id,
    )
    assert written == 3

    rows = sheet_rows(paths.output_workbook_path)
    header = list(rows[0])
    assert header[: len(workbook.columns)] == list(workbook.columns)
    assert header[-3:] == list(STATUS_COLUMNS)
    assert "symptom" in header
    # Original data is preserved alongside the analysis.
    assert rows[1][0] == "R-001"
    assert "router drops connection" in str(rows[1][3]).lower()


async def test_manifest_describes_the_run_without_credentials(settings, credentials) -> None:
    paths, _, _, _ = await _run(settings, credentials, FakeTransport())
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == "run_test"
    assert manifest["model"] == "test-model"
    assert manifest["backend"] == {"type": "api", "model": "test-model"}
    assert manifest["analysis"]["key"] == "rca-v1"
    assert manifest["results"]["ok"] == 3
    assert manifest["selection"]["analyzed_rows"] == 3
    assert len(manifest["selection"]["skipped"]) == 2
    assert "sk-test-secret-value" not in paths.manifest_path.read_text(encoding="utf-8")


async def test_call_directories_are_written_per_record(settings, credentials) -> None:
    paths, _, _, _ = await _run(settings, credentials, FakeTransport())
    call_dirs = sorted((paths.calls_dir / "rca-v1").iterdir())
    assert len(call_dirs) == 3
    request = json.loads((call_dirs[0] / "request.json").read_text(encoding="utf-8"))
    assert request["prompt_version"] == "v1"
    assert "sk-test-secret-value" not in json.dumps(request)


async def test_the_api_key_never_reaches_the_run_log(settings, credentials) -> None:
    paths, _, _, _ = await _run(settings, credentials, FakeTransport())
    assert "sk-test-secret-value" not in paths.run_log_path.read_text(encoding="utf-8")


# --- failure isolation ----------------------------------------------------------


async def test_one_bad_record_does_not_stop_the_run(settings, credentials) -> None:
    def responder(request):
        return permanent("endpoint rejected it") if request.record_id == "R-002" else rca_payload()

    paths, _, _, report = await _run(settings, credentials, FakeTransport(responder=responder))

    assert report.succeeded == 2
    assert report.failed == 1
    failed = [item for item in read_jsonl(paths.results_path) if item["status"] == "failed"]
    assert failed[0]["record_id"] == "R-002"
    assert "endpoint rejected it" in failed[0]["error"]


async def test_unparseable_reply_becomes_a_failed_record(settings, credentials) -> None:
    _, _, _, report = await _run(settings, credentials, FakeTransport(responder=lambda _r: "sorry!"))
    assert report.failed == 3
    assert all("no JSON object" in item.error for item in report.outcomes)


async def test_schema_violation_is_reported_with_detail(settings, credentials) -> None:
    bad = {"symptom": "x", "evidence": "not a list"}
    _, _, _, report = await _run(settings, credentials, FakeTransport(responder=lambda _r: bad))
    assert report.failed == 3
    assert "did not match the rca schema" in report.outcomes[0].error
    assert report.outcomes[0].issues


async def test_validator_issues_flag_rather_than_fail(settings, credentials) -> None:
    invented = rca_payload(
        cause_status="documented",
        documented_cause="A damaged cable",
        evidence=[{"field": "Troubleshooting", "quote": "a measurement nobody recorded"}],
    )
    paths, selection, workbook, report = await _run(
        settings, credentials, FakeTransport(responder=lambda _r: invented)
    )

    assert report.flagged == 3
    assert report.failed == 0
    assert any("verbatim" in issue for issue in report.outcomes[0].issues)

    write_workbook(
        paths.output_workbook_path,
        source_columns=workbook.columns,
        result_columns=get_analysis("rca").output_columns,
        rows=runner.output_rows(report),
        rows_by_id=selection.rows_by_id,
    )
    rows = sheet_rows(paths.output_workbook_path)
    status_index = list(rows[0]).index("analysis_status")
    assert rows[1][status_index] == "flagged"


async def test_failed_records_still_get_a_workbook_row(settings, credentials) -> None:
    paths, selection, workbook, report = await _run(
        settings, credentials, FakeTransport(responder=lambda _r: permanent())
    )
    written = write_workbook(
        paths.output_workbook_path,
        source_columns=workbook.columns,
        result_columns=get_analysis("rca").output_columns,
        rows=runner.output_rows(report),
        rows_by_id=selection.rows_by_id,
    )
    assert written == 3
    rows = sheet_rows(paths.output_workbook_path)
    error_index = list(rows[0]).index("analysis_error")
    assert rows[1][0] == "R-001"
    assert "bad request" in str(rows[1][error_index])


# --- the layers, in a real run --------------------------------------------------


async def test_transient_failures_are_retried_inside_a_run(settings, credentials) -> None:
    seen: dict[str, int] = {}

    def responder(request):
        seen[request.record_id] = seen.get(request.record_id, 0) + 1
        return transient() if seen[request.record_id] == 1 else rca_payload()

    settings = make_settings(
        settings.dataset.path,
        settings.output.runs_dir,
        rate_limits={"rpm": None, "tpm": None, "max_attempts": 3},
    )
    transport = FakeTransport(responder=responder)
    with _instant_sleep():
        _, _, _, report = await _run(settings, credentials, transport)

    assert report.succeeded == 3
    assert transport.call_count == 6


async def test_a_second_run_reuses_the_first(settings, credentials, tmp_path) -> None:
    runs_dir = settings.output.runs_dir
    first = make_settings(settings.dataset.path, runs_dir)
    await _run(first, credentials, FakeTransport(), run_id="run_1")

    reuse = make_settings(settings.dataset.path, runs_dir, cache={"mode": "reuse"})
    transport = FakeTransport(responder=lambda _r: pytest.fail("cache should have answered"))
    _, _, _, report = await _run(reuse, credentials, transport, run_id="run_2")

    assert report.succeeded == 3
    assert report.cache_hits == 3
    assert transport.call_count == 0
    assert all(item.cached for item in report.outcomes)


async def test_run_log_reports_the_final_cache_count(settings, credentials) -> None:
    """The counters are only populated during the run, so they must be read at the end."""
    runs_dir = settings.output.runs_dir
    await _run(make_settings(settings.dataset.path, runs_dir), credentials, FakeTransport(), run_id="run_1")

    reuse = make_settings(settings.dataset.path, runs_dir, cache={"mode": "reuse"})
    paths, _, _, _ = await _run(reuse, credentials, FakeTransport(), run_id="run_2")

    run_done = [
        line for line in paths.run_log_path.read_text(encoding="utf-8").splitlines()
        if "run.done" in line
    ]
    assert "cache_hits=3" in run_done[0]


async def test_concurrency_is_bounded(settings, credentials) -> None:
    import asyncio

    active = {"now": 0, "peak": 0}

    async def responder_client(request):
        active["now"] += 1
        active["peak"] = max(active["peak"], active["now"])
        await asyncio.sleep(0)
        active["now"] -= 1
        return rca_payload()

    class SlowTransport(FakeTransport):
        async def complete(self, request):
            self.requests.append(request)
            payload = await responder_client(request)
            return self._materialize(payload, request)

    settings = make_settings(
        settings.dataset.path, settings.output.runs_dir, analysis={"concurrency": 2}
    )
    await _run(settings, credentials, SlowTransport())
    assert active["peak"] <= 2


# --- the CLI --------------------------------------------------------------------


def _write_config(tmp_path: Path, workbook: Path, runs_dir: Path, **extra: str) -> Path:
    body = f"""
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
"""
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cli_dry_run_selects_without_calling_the_model(
    tmp_path: Path, workbook_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)

    code = main(["--config", str(config), "--dry-run", "--run-id", "dry", "--no-echo"])

    assert code == EXIT_OK
    log = (runs_dir / "dry" / "run.log").read_text(encoding="utf-8")
    assert "dryrun.done records=3" in log
    assert not (runs_dir / "dry" / "results.jsonl").exists()


def test_cli_dry_run_reports_skipped_rows(tmp_path: Path, workbook_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    main(["--config", str(config), "--dry-run", "--run-id", "dry", "--no-echo"])
    log = (runs_dir / "dry" / "run.log").read_text(encoding="utf-8")
    assert "selection.skipped" in log


def test_cli_limit_override(tmp_path: Path, workbook_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    main(["--config", str(config), "--dry-run", "--limit", "1", "--run-id", "d", "--no-echo"])
    assert "dryrun.done records=1" in (runs_dir / "d" / "run.log").read_text(encoding="utf-8")


def test_cli_reports_a_missing_config(tmp_path: Path, capsys) -> None:
    assert main(["--config", str(tmp_path / "absent.yaml")]) == EXIT_CONFIG
    assert "config file not found" in capsys.readouterr().err


def test_cli_reports_an_unknown_analysis(tmp_path: Path, workbook_path: Path, capsys) -> None:
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")
    config.write_text(
        config.read_text(encoding="utf-8").replace("name: rca", "name: nonexistent"),
        encoding="utf-8",
    )
    assert main(["--config", str(config)]) == EXIT_CONFIG
    captured = capsys.readouterr().err
    assert "unknown analysis" in captured
    assert "available analyses: case_summary, rca" in captured


def test_cli_reports_a_missing_prompt_version(
    tmp_path: Path, workbook_path: Path, capsys
) -> None:
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")
    config.write_text(
        config.read_text(encoding="utf-8").replace("version: v1", "version: v99"),
        encoding="utf-8",
    )
    assert main(["--config", str(config)]) == EXIT_CONFIG
    assert "no prompt version" in capsys.readouterr().err


def test_cli_reports_a_missing_column(tmp_path: Path, workbook_path: Path, capsys) -> None:
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")
    config.write_text(
        config.read_text(encoding="utf-8").replace("id_field: Record ID", "id_field: Absent"),
        encoding="utf-8",
    )
    assert main(["--config", str(config), "--dry-run"]) == EXIT_CONFIG
    assert "Absent" in capsys.readouterr().err


def test_cli_requires_credentials_for_a_real_run(
    tmp_path: Path, workbook_path: Path, monkeypatch, capsys
) -> None:
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")

    assert main(["--config", str(config)]) == EXIT_CONFIG
    assert "missing required environment variables" in capsys.readouterr().err
    # The failure happened before any output directory was created.
    assert not (tmp_path / "runs").exists()


def test_exit_codes_are_distinct() -> None:
    assert len({EXIT_OK, EXIT_PARTIAL, EXIT_CONFIG}) == 3


def test_cli_warns_when_the_endpoint_rejects_json_mode(
    tmp_path: Path, workbook_path: Path, monkeypatch
) -> None:
    """The transport falls back silently; the run log is where an operator would see it."""
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    _fake_credentials(monkeypatch)

    transport = FakeTransport(responder=lambda _r: rca_payload())
    transport.response_format_fallbacks = 2
    _patch_transport(monkeypatch, transport)

    code = main(["--config", str(config), "--run-id", "jsonmode", "--no-echo"])

    assert code == EXIT_OK
    log = (runs_dir / "jsonmode" / "run.log").read_text(encoding="utf-8")
    assert "transport.json_mode_unsupported" in log
    assert "fallbacks=2" in log


def test_cli_is_quiet_when_json_mode_works(
    tmp_path: Path, workbook_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    _fake_credentials(monkeypatch)

    transport = FakeTransport(responder=lambda _r: rca_payload())
    transport.response_format_fallbacks = 0
    _patch_transport(monkeypatch, transport)

    main(["--config", str(config), "--run-id", "quiet", "--no-echo"])
    assert "json_mode_unsupported" not in (runs_dir / "quiet" / "run.log").read_text(
        encoding="utf-8"
    )


def _patch_transport(monkeypatch, transport) -> None:
    """Make the CLI build its normal stack, but over a scripted transport."""
    import complaint_analyzer.__main__ as cli

    original = cli.build
    monkeypatch.setattr(
        cli,
        "build",
        lambda settings, credentials, paths, log: original(
            settings, credentials, paths, log, transport=transport
        ),
    )


def _fake_credentials(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "sk-cli-secret")
    monkeypatch.setenv("LLM_MODEL", "cli-model")


def test_cli_full_run_writes_every_artifact(
    tmp_path: Path, workbook_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    _fake_credentials(monkeypatch)
    _patch_transport(monkeypatch, FakeTransport(responder=lambda _r: rca_payload()))

    code = main(
        [
            "--config", str(config),
            "--run-id", "full",
            "--no-echo",
            "--env-file", str(tmp_path / "absent.env"),
        ]
    )

    assert code == EXIT_OK
    run_dir = runs_dir / "full"
    assert (run_dir / "analyzed.xlsx").exists()
    assert (run_dir / "manifest.json").exists()
    assert len(read_jsonl(run_dir / "results.jsonl")) == 3
    assert "sk-cli-secret" not in (run_dir / "run.log").read_text(encoding="utf-8")

    rows = sheet_rows(run_dir / "analyzed.xlsx")
    assert len(rows) == 4
    assert rows[0][0] == "Record ID"


def test_cli_returns_partial_when_a_record_fails(
    tmp_path: Path, workbook_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    _fake_credentials(monkeypatch)

    def responder(request):
        return permanent() if request.record_id == "R-002" else rca_payload()

    _patch_transport(monkeypatch, FakeTransport(responder=responder))

    code = main(
        [
            "--config", str(config),
            "--run-id", "partial",
            "--no-echo",
            "--env-file", str(tmp_path / "absent.env"),
        ]
    )

    assert code == EXIT_PARTIAL
    manifest = json.loads((runs_dir / "partial" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["results"]["failed"] == 1
    # A failed record still appears in the workbook.
    assert len(sheet_rows(runs_dir / "partial" / "analyzed.xlsx")) == 4


def test_cli_handles_a_selection_that_matches_nothing(
    tmp_path: Path, workbook_path: Path, monkeypatch
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir)
    config.write_text(
        config.read_text(encoding="utf-8").replace("value: Closed", "value: Nonexistent"),
        encoding="utf-8",
    )
    _fake_credentials(monkeypatch)

    code = main(["--config", str(config), "--run-id", "empty", "--no-echo"])

    assert code == EXIT_OK
    assert "selection.empty" in (runs_dir / "empty" / "run.log").read_text(encoding="utf-8")
    assert not (runs_dir / "empty" / "analyzed.xlsx").exists()


class _instant_sleep:
    """Replace ``asyncio.sleep`` so retry backoff does not slow the suite."""

    def __enter__(self):
        import asyncio

        self._original = asyncio.sleep

        async def immediate(_seconds, *args, **kwargs):
            return await self._original(0, *args, **kwargs)

        asyncio.sleep = immediate
        return self

    def __exit__(self, *_exc):
        import asyncio

        asyncio.sleep = self._original
        return False
