"""Portable command-line entry point for the Streamlit application."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from src.startup import StartupCheckError, StartupReport, run_startup_checks


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STREAMLIT_APP = PROJECT_ROOT / "app" / "main.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start the BIM Agent evacuation-door review service.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=_valid_port, default=8501)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="start Streamlit without opening a local browser",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate configuration and runtime assets, then exit",
    )
    return parser


def build_streamlit_command(
    *,
    host: str,
    port: int,
    no_browser: bool,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(STREAMLIT_APP),
        "--server.address",
        host,
        "--server.port",
        str(port),
        "--server.headless",
        str(no_browser).lower(),
        "--server.maxUploadSize",
        "250",
        "--browser.gatherUsageStats",
        "false",
    ]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_startup_checks(PROJECT_ROOT)
    except StartupCheckError as exc:
        print(f"Startup check failed: {exc}", file=sys.stderr)
        return 2
    _print_report(report)
    if args.check:
        return 0

    url = f"http://{args.host}:{args.port}"
    print(f"Starting BIM Agent at {url}", flush=True)
    try:
        completed = subprocess.run(
            build_streamlit_command(
                host=args.host,
                port=args.port,
                no_browser=args.no_browser,
            ),
            cwd=PROJECT_ROOT,
            check=False,
        )
    except KeyboardInterrupt:
        return 130
    return completed.returncode


def _print_report(report: StartupReport) -> None:
    print(
        "Startup check passed: "
        f"Python {report.python_version}; "
        f"{len(report.document_ids)} indexed documents; "
        f"embedding={report.embedding_model}; "
        f"eval={report.eval_fixture.name}"
    )


def _valid_port(raw_value: str) -> int:
    value = int(raw_value)
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
