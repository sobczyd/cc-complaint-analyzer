"""The command line entry point.

Wiring only: load configuration, resolve the analysis, build the client stack, run,
and write the workbook. Any real logic belongs in the module that owns it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from . import __version__, runner
from .prompts import AnalysisError, available, get_analysis
from .data import DataError, load_sheet, select
from .data.writer import write_workbook
from .llm.build import build
from .llm.exchange import (
    inspect_exchange,
    load_exchange_client,
    prepare_exchange,
    publish_response,
)
from .llm.protocol import ChatClient
from .logs import RunLog
from .run_paths import RunPaths, default_run_id
from .settings import ConfigError, Credentials, load_credentials, load_settings

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2
EXIT_INTERRUPTED = 130


def _limit_value(value: str) -> int:
    """Parse ``--limit``: a non-negative integer, where 0 means no limit."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError(
            f"must be 0 or greater (0 means no limit), got {number}"
        )
    return number


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid int value: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="complaint-analyzer",
        description="Analyze service-record workbook rows one at a time with an LLM.",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config/rca.yaml"),
        help="Path to the YAML analysis configuration (default: config/rca.yaml).",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Name for this run's output directory (default: a UTC timestamp).",
    )
    parser.add_argument(
        "--limit",
        type=_limit_value,
        default=None,
        help="Override dataset.limit. Use 0 for no limit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select records and render prompts without calling the model.",
    )
    parser.add_argument(
        "--no-echo",
        action="store_true",
        help="Write run.log without mirroring it to stdout.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to a .env file holding credentials (default: ./.env).",
    )
    parser.add_argument(
        "--backend",
        choices=("api", "harness"),
        default="api",
        help="Completion backend (default: api).",
    )
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument(
        "--prepare",
        action="store_true",
        help="Export requests for a harness-backed run.",
    )
    phase.add_argument(
        "--finalize",
        action="store_true",
        help="Validate harness responses and finish a prepared run.",
    )
    phase.add_argument(
        "--check",
        action="store_true",
        help="Validate harness responses without writing final artifacts.",
    )
    phase.add_argument(
        "--publish-response",
        type=Path,
        metavar="CANDIDATE",
        help="Validate and atomically publish one worker response.",
    )
    parser.add_argument(
        "--batch-size",
        type=_positive_int,
        default=10,
        help="Records per persisted harness assignment (default: 10).",
    )
    parser.add_argument(
        "--assignment-id",
        default=None,
        help="Persisted assignment that owns a --publish-response candidate.",
    )
    parser.add_argument(
        "--harness-model",
        default="copilot-harness",
        help="Stable model identity recorded for harness requests.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def _dry_run(settings, analysis, selection, log: RunLog) -> int:
    log.event(
        "dryrun.selection",
        total_rows=selection.total_rows,
        matched=selection.matched_rows,
        selected=len(selection.records),
    )
    for item in selection.skipped:
        log.warning("dryrun.skipped", source_row=item.source_row, reason=item.reason)

    for record in selection.records:
        request = runner.build_request(
            record,
            analysis=analysis,
            settings=settings,
            model="(dry-run)",
        )
        log.event(
            "dryrun.record",
            record_id=record.record_id,
            source_row=record.source_row,
            prompt_chars=sum(len(message.content) for message in request.messages),
            fingerprint=request.fingerprint()[:12],
        )
    log.event("dryrun.done", records=len(selection.records))
    return EXIT_OK


async def _execute(
    args: argparse.Namespace,
    settings,
    credentials: Credentials | None,
    analysis,
    selection,
    workbook,
    log: RunLog,
    run_paths: RunPaths,
    run_id: str,
    *,
    model: str,
    backend: str,
    transport: ChatClient | None = None,
) -> int:
    if transport is None:
        stack = build(settings, credentials, run_paths, log)
    else:
        stack = build(settings, credentials, run_paths, log, transport=transport)
    try:
        report = await runner.run(
            selection,
            analysis=analysis,
            settings=settings,
            client=stack.client,
            model=model,
            run_paths=run_paths,
            run_id=run_id,
            log=log,
            cache=stack.cache,
        )
    finally:
        await stack.aclose()

    fallbacks = getattr(stack.transport, "response_format_fallbacks", 0)
    if fallbacks:
        log.warning(
            "transport.json_mode_unsupported",
            fallbacks=fallbacks,
            detail="endpoint rejected response_format; retried without it",
        )

    written = write_workbook(
        run_paths.output_workbook_path,
        source_columns=workbook.columns,
        result_columns=analysis.output_columns,
        rows=runner.output_rows(report),
        rows_by_id=selection.rows_by_id,
    )

    runner.write_manifest(
        run_paths,
        report=report,
        settings=settings,
        selection=selection,
        analysis=analysis,
        model=model,
        config_path=str(args.config),
        backend=backend,
    )

    log.event(
        "run.written",
        workbook=str(run_paths.output_workbook_path),
        rows=written,
        results=str(run_paths.results_path),
        manifest=str(run_paths.manifest_path),
    )
    return EXIT_OK if report.failed == 0 else EXIT_PARTIAL


def _validate_mode(args: argparse.Namespace) -> None:
    harness_phases = (args.prepare, args.finalize, args.check, args.publish_response is not None)
    if args.dry_run:
        if any(harness_phases):
            raise ConfigError("--dry-run cannot be combined with a harness phase")
        return
    if args.backend == "api":
        if any(harness_phases):
            raise ConfigError("harness phases require --backend harness")
        return
    if not any(harness_phases):
        raise ConfigError(
            "--backend harness requires exactly one of --prepare, --check, "
            "--publish-response, or --finalize"
        )
    if (args.finalize or args.check or args.publish_response is not None) and not args.run_id:
        raise ConfigError("this harness phase requires --run-id")
    if args.publish_response is not None and not args.assignment_id:
        raise ConfigError("--publish-response requires --assignment-id")
    if args.publish_response is None and args.assignment_id:
        raise ConfigError("--assignment-id requires --publish-response")


def _harness_requests(selection, *, analysis, settings, model: str):
    return [
        runner.build_request(record, analysis=analysis, settings=settings, model=model)
        for record in selection.records
    ]


def _reset_incomplete_finalization(run_paths: RunPaths) -> None:
    """Remove only known final artifacts when no completion manifest exists."""
    for path in (
        run_paths.manifest_path,
        run_paths.results_path,
        run_paths.output_workbook_path,
    ):
        if path.is_file():
            path.unlink()
    if run_paths.calls_dir.is_dir():
        shutil.rmtree(run_paths.calls_dir)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        # argparse has already explained itself on stderr. Usage errors are a
        # configuration problem; --help and --version keep exiting normally.
        if exc.code in (0, None):
            raise
        return EXIT_CONFIG

    log: RunLog | None = None

    try:
        _validate_mode(args)
        settings = load_settings(args.config)
        if args.limit is not None:
            effective_limit = None if args.limit == 0 else args.limit
            settings = settings.model_copy(
                update={
                    "dataset": settings.dataset.model_copy(
                        update={"limit": effective_limit}
                    )
                }
            )
        analysis = get_analysis(settings.analysis.name)
        analysis.prompt(settings.analysis.version)  # Fail now, not after the workbook loads.

        workbook = load_sheet(settings.dataset.path, settings.dataset.sheet)
        selection = select(workbook, settings.dataset)

        run_id = args.run_id or default_run_id()
        credentials = None
        transport = None
        harness_requests = None
        model = "(dry-run)"

        if args.backend == "api" and not args.dry_run:
            # Resolve credentials before creating output so a missing key leaves no
            # empty API run directory behind.
            credentials = load_credentials(args.env_file)
            model = credentials.model
            run_paths = RunPaths.create(settings.output.runs_dir, run_id)
        elif args.backend == "harness" and (
            args.finalize or args.check or args.publish_response is not None
        ):
            model = args.harness_model
            try:
                run_paths = RunPaths.open_existing(settings.output.runs_dir, run_id)
            except FileNotFoundError as exc:
                missing = settings.output.runs_dir / run_id
                raise ConfigError(f"prepared harness run not found: {missing}") from exc
            if args.finalize and run_paths.manifest_path.exists():
                final_artifacts = (
                    run_paths.results_path.is_file(),
                    run_paths.output_workbook_path.is_file(),
                    run_paths.calls_dir.is_dir(),
                )
                try:
                    existing_manifest = json.loads(
                        run_paths.manifest_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError):
                    existing_manifest = {}
                completion_marker = isinstance(existing_manifest, dict) and (
                    existing_manifest.get("finalized") is True
                    or all(
                        key in existing_manifest
                        for key in ("run_id", "selection", "results")
                    )
                )
                if completion_marker and all(final_artifacts):
                    raise ConfigError(
                        "harness run is already finalized: " + str(run_paths.manifest_path)
                    )
            if args.finalize or args.check:
                harness_requests = _harness_requests(
                    selection, analysis=analysis, settings=settings, model=model
                )
        elif args.backend == "harness" and args.prepare:
            model = args.harness_model
            try:
                run_paths = RunPaths.create_new(settings.output.runs_dir, run_id)
            except FileExistsError as exc:
                raise ConfigError(f"run directory already exists: {exc.filename}") from exc
        else:
            run_paths = RunPaths.create(settings.output.runs_dir, run_id)

        secrets = [credentials.api_key.get_secret_value()] if credentials is not None else []
        log = RunLog(run_paths.run_log_path, echo=not args.no_echo, secrets=secrets)

        for item in selection.skipped:
            log.warning("selection.skipped", source_row=item.source_row, reason=item.reason)
        if not selection.records:
            log.warning("selection.empty", matched=selection.matched_rows)
            return EXIT_OK

        if args.dry_run:
            return _dry_run(settings, analysis, selection, log)

        if args.backend == "harness" and args.finalize:
            transport = load_exchange_client(
                run_paths,
                harness_requests,
                model=model,
                analysis=analysis,
            )
            _reset_incomplete_finalization(run_paths)

        if args.backend == "harness" and args.check:
            inspection = inspect_exchange(
                run_paths,
                harness_requests,
                model=model,
                analysis=analysis,
            )
            print(json.dumps(inspection.as_json(), ensure_ascii=False, indent=2))
            return EXIT_OK if inspection.ready else EXIT_PARTIAL

        if args.backend == "harness" and args.publish_response is not None:
            destination = publish_response(
                run_paths,
                args.publish_response,
                assignment_id=args.assignment_id,
                model=model,
                analysis=analysis,
            )
            print(destination)
            return EXIT_OK

        if args.backend == "harness" and args.prepare:
            requests = _harness_requests(
                selection, analysis=analysis, settings=settings, model=model
            )
            prepare_exchange(
                run_paths,
                requests,
                config_path=str(args.config),
                model=model,
                batch_size=args.batch_size,
                effective_limit=settings.dataset.limit,
            )
            log.event(
                "harness.prepared",
                run_id=run_id,
                records=len(requests),
                responses=str(run_paths.exchange_responses_dir),
            )
            return EXIT_OK

        return asyncio.run(
            _execute(
                args,
                settings,
                credentials,
                analysis,
                selection,
                workbook,
                log,
                run_paths,
                run_id,
                model=model,
                backend=args.backend,
                transport=transport,
            )
        )
    except (ConfigError, AnalysisError, DataError) as exc:
        message = f"error: {exc}"
        if isinstance(exc, AnalysisError):
            message += f"\navailable analyses: {', '.join(available())}"
        print(message, file=sys.stderr)
        if log is not None:
            log.error("run.aborted", error=str(exc))
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        if log is not None:
            log.warning("run.interrupted")
        return EXIT_INTERRUPTED
    finally:
        if log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
