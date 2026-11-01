"""Local file CLI; no network, live links, commands, or execution option."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import Thresholds, analyze
from .fixtures import write_fixtures
from .report import write_reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DroneHacks offline Flight Forensics & Replay; "
        "all outputs executed=False. No flight command interface."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("fixtures", help="Generate synthetic-only local parser fixtures")
    fixture.add_argument("--output", required=True, type=Path)
    report = commands.add_parser("report", help="Analyze local files after flight")
    report.add_argument("--px4", type=Path, help="Local PX4 .ulg file (PyULog)")
    report.add_argument("--jetson", type=Path, help="Local perception JSONL v1")
    report.add_argument(
        "--alignment", type=Path, help="Hash-bound paired-clock evidence descriptor"
    )
    report.add_argument("--output", type=Path, required=True, help="Local report directory")
    report.add_argument("--depth-coverage-min", type=float, default=0.5)
    report.add_argument("--invalid-depth-ratio-max", type=float, default=0.5)
    report.add_argument("--line-confidence-min", type=float, default=0.3)
    report.add_argument("--latency-ms-max", type=float, default=100)
    report.add_argument("--saturation-abs-min", type=float, default=0.95)
    bundle_fixture = commands.add_parser(
        "integration-fixtures", help="Generate deterministic sensor replay bundle"
    )
    bundle_fixture.add_argument("--output", required=True, type=Path)
    bundle_fixture.add_argument(
        "--scenario", choices=("consistent", "adverse"), default="consistent"
    )
    integration = commands.add_parser(
        "integration", help="Audit sensor bundle into an exclusive sealed run"
    )
    integration.add_argument("--bundle", required=True, type=Path)
    integration.add_argument("--output-root", required=True, type=Path)
    integration.add_argument("--run-id")
    preflight = commands.add_parser(
        "preflight", help="Static OS/package metadata; no hardware probes"
    )
    preflight.add_argument("--output-root", required=True, type=Path)
    preflight.add_argument("--run-id")
    preflight.add_argument(
        "--environment",
        choices=("desktop", "jetson_orin_nano", "replay", "sitl", "unknown"),
        default="replay",
    )
    verify = commands.add_parser("verify", help="Read-only evidence seal verification")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "integration-fixtures":
            from .integration_fixtures import write_bundle

            write_bundle(args.output, args.scenario)
            print(
                json.dumps(
                    {
                        "synthetic_only": True,
                        "output": str(args.output),
                        "executed": False,
                        "authority": "NONE",
                    }
                )
            )
            return 0
        if args.command in {"preflight", "integration"}:
            from .recorder import record_run

            if args.command == "integration":
                from .integration import audit_bundle, integration_reports

                if args.output_root.resolve().is_relative_to(args.bundle.resolve()):
                    raise ValueError("Run output must be outside the read-only input bundle")
                summary, sources = audit_bundle(args.bundle)
                reports = integration_reports(summary)
            else:
                from .platform_manifest import preflight, preflight_reports

                summary = preflight(args.output_root, args.environment)
                sources = {}
                reports = preflight_reports(summary)
            directory = record_run(args.output_root, summary, sources, reports, args.run_id)
            print(
                json.dumps(
                    {
                        "directory": str(directory),
                        "executed": False,
                        "authority": "NONE",
                        "hardware_validation": "unknown",
                    }
                )
            )
            return 2 if args.command == "integration" and summary["findings"] else 0
        if args.command == "verify":
            from .recorder import verify_run

            print(json.dumps(verify_run(args.directory)))
            return 0
        if args.command == "fixtures":
            write_fixtures(args.output)
            print(
                json.dumps({"synthetic_only": True, "output": str(args.output), "executed": False})
            )
            return 0
        thresholds = Thresholds(
            args.depth_coverage_min,
            args.invalid_depth_ratio_max,
            args.line_confidence_min,
            args.latency_ms_max,
            args.saturation_abs_min,
        )
        analysis = analyze(args.px4, args.jetson, args.alignment, thresholds)
        summary = write_reports(analysis, args.output)
        incomplete = any(not source["complete"] for source in summary["sources"].values())
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "executed": False,
                    "alignment": summary["alignment"]["status"],
                    "finding_counts": summary["finding_counts"],
                    "incomplete": incomplete,
                }
            )
        )
        return 2 if incomplete else 0
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error), "executed": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
