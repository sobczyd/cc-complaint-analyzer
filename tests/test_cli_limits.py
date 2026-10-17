"""Regression tests: limit handling, token accounting, and worker shutdown."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from complaint_analyzer import runner
from complaint_analyzer.__main__ import EXIT_CONFIG, EXIT_OK, main
from complaint_analyzer.prompts import get_analysis
from complaint_analyzer.data import load_sheet, select
from complaint_analyzer.llm.build import build
from complaint_analyzer.logs import RunLog
from complaint_analyzer.run_paths import RunPaths
from complaint_analyzer.settings import Settings

from conftest import SHEET, FakeTransport, make_settings, rca_payload


def _write_config(tmp_path: Path, workbook: Path, runs_dir: Path, *, limit: str = "null") -> Path:
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
  limit: {limit}
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


# --- --limit ---------------------------------------------------------------------


def test_limit_zero_lifts_a_configured_limit(tmp_path: Path, workbook_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir, limit="2")

    code = main(["--config", str(config), "--dry-run", "--limit", "0", "--run-id", "all", "--no-echo"])

    assert code == EXIT_OK
    assert "dryrun.done records=3" in (runs_dir / "all" / "run.log").read_text(encoding="utf-8")


def test_without_limit_the_configured_limit_still_applies(
    tmp_path: Path, workbook_path: Path
) -> None:
    runs_dir = tmp_path / "runs"
    config = _write_config(tmp_path, workbook_path, runs_dir, limit="2")

    main(["--config", str(config), "--dry-run", "--run-id", "capped", "--no-echo"])

    assert "dryrun.done records=2" in (runs_dir / "capped" / "run.log").read_text(encoding="utf-8")


def test_negative_limit_is_rejected(tmp_path: Path, workbook_path: Path, capsys) -> None:
    config = _write_config(tmp_path, workbook_path, tmp_path / "runs")

    assert main(["--config", str(config), "--dry-run", "--limit", "-1"]) == EXIT_CONFIG
    assert "0 or greater" in capsys.readouterr().err


def test_a_help_request_still_exits_normally(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0


# --- token accounting -------------------------------------------------------------


async def _run(settings: Settings, credentials, transport, *, run_id: str, log=None):
    workbook = load_sheet(settings.dataset.path, settings.dataset.sheet)
    selection = select(workbook, settings.dataset)
    paths = RunPaths.create(settings.output.runs_dir, run_id)
    run_log = log or RunLog(paths.run_log_path, echo=False)
    stack = build(settings, credentials, paths, run_log, transport=transport)
    try:
        report = await runner.run(
            selection,
            analysis=get_analysis(settings.analysis.name),
            settings=settings,
            client=stack.client,
            model=credentials.model,
            run_paths=paths,
            run_id=run_id,
            log=run_log,
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
    run_log.close()
    return paths, report


async def test_a_cached_run_reports_no_current_run_tokens(settings, credentials) -> None:
    runs_dir = settings.output.runs_dir
    first = make_settings(settings.dataset.path, runs_dir)
    _, original = await _run(first, credentials, FakeTransport(), run_id="run_1")

    reuse = make_settings(settings.dataset.path, runs_dir, cache={"mode": "reuse"})
    transport = FakeTransport(responder=lambda _r: pytest.fail("cache should have answered"))
    paths, report = await _run(reuse, credentials, transport, run_id="run_2")

    assert report.cache_hits == 3
    assert report.prompt_tokens == 0
    assert report.completion_tokens == 0
    assert report.reused_prompt_tokens == original.prompt_tokens
    assert report.reused_completion_tokens == original.completion_tokens

    results = json.loads(paths.manifest_path.read_text(encoding="utf-8"))["results"]
    assert results["total_tokens"] == 0
    assert results["reused_total_tokens"] == original.prompt_tokens + original.completion_tokens


async def test_an_uncached_run_still_counts_its_tokens(settings, credentials) -> None:
    paths, report = await _run(settings, credentials, FakeTransport(), run_id="fresh")

    assert report.prompt_tokens == 360
    assert report.reused_prompt_tokens == 0

    results = json.loads(paths.manifest_path.read_text(encoding="utf-8"))["results"]
    assert results["total_tokens"] == 540
    assert results["reused_total_tokens"] == 0


# --- worker shutdown --------------------------------------------------------------


class _ExplodingLog(RunLog):
    """A run log that fails once, the way any unexpected worker error would."""

    def __init__(self, path: Path, *, record_id: str) -> None:
        super().__init__(path, echo=False)
        self._record_id = record_id

    def event(self, event: str, **fields) -> None:
        if event == "record.done" and fields.get("record_id") == self._record_id:
            raise OSError("run.log is gone")
        super().event(event, **fields)


async def test_every_worker_finishes_before_the_run_returns(
    settings, credentials, tmp_path: Path
) -> None:
    started = 0
    ended = 0

    class SlowTransport(FakeTransport):
        async def complete(self, request):
            nonlocal started, ended
            self.requests.append(request)
            started += 1
            try:
                if request.record_id == "R-001":
                    for _ in range(3):  # Let the siblings reach their own call first.
                        await asyncio.sleep(0)
                else:
                    await asyncio.sleep(30)
                return self._materialize(rca_payload(), request)
            finally:
                ended += 1

    settings = make_settings(
        settings.dataset.path, settings.output.runs_dir, analysis={"concurrency": 3}
    )
    workbook = load_sheet(settings.dataset.path, settings.dataset.sheet)
    selection = select(workbook, settings.dataset)
    paths = RunPaths.create(settings.output.runs_dir, "crash")
    log = _ExplodingLog(paths.run_log_path, record_id="R-001")
    stack = build(settings, credentials, paths, log, transport=SlowTransport())

    with pytest.raises(OSError):
        await runner.run(
            selection,
            analysis=get_analysis(settings.analysis.name),
            settings=settings,
            client=stack.client,
            model=credentials.model,
            run_paths=paths,
            run_id="crash",
            log=log,
            cache=stack.cache,
        )

    # No sibling is still in flight once the failure surfaces, so closing the
    # transport and the results file cannot race with a live worker.
    assert started == 3
    assert ended == started

    await stack.aclose()
    log.close()
    assert paths.results_path.read_text(encoding="utf-8") == ""
