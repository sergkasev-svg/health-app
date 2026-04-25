from __future__ import annotations

import argparse
from dataclasses import asdict

from app.services.complaint_scenario_audit import (
    run_complaint_scenario_audit,
    save_complaint_scenario_audit_report,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run complaint scenario audit (300+ cases, 100-point completeness score).")
    parser.add_argument("--count", type=int, default=300, help="Target number of complaint scenarios (minimum effective = 300).")
    parser.add_argument("--threshold", type=float, default=70.0, help="Pass threshold in 100-point system.")
    parser.add_argument("--output-dir", type=str, default="./quality_artifacts", help="Directory for report artifacts.")
    parser.add_argument("--strict", action="store_true", help="Use stricter scoring mode (domain match and anti-generic penalties).")
    parser.add_argument("--quiet", action="store_true", help="Print only compact summary.")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    result = run_complaint_scenario_audit(
        target_count=max(300, int(args.count or 300)),
        low_score_threshold=float(args.threshold or 70.0),
        strict_mode=bool(args.strict),
    )
    paths = save_complaint_scenario_audit_report(
        result,
        output_dir=args.output_dir,
    )

    if args.quiet:
        print(
            " | ".join(
                [
                    f"cases={result.summary.get('cases_total')}",
                    f"avg={result.summary.get('average_score_100')}",
                    f"pass_rate={result.summary.get('pass_rate')}%",
                    f"failed={result.summary.get('failed_count')}",
                    f"strict={result.summary.get('strict_mode')}",
                    f"next_reminder_at={result.reminder.get('after_run', {}).get('next_reminder_at', '')}",
                    f"report={paths.get('json')}",
                ]
            )
        )
        return

    print("\n================ COMPLAINT SCENARIO AUDIT ================")
    for k, v in result.summary.items():
        print(f"{k}: {v}")

    print("\n================ SCORE DISTRIBUTION ================")
    for k, v in result.score_distribution.items():
        print(f"{k}: {v}")

    print("\n================ TOP PROBLEMS ================")
    for row in result.top_problems:
        print(row)

    print("\n================ LOW SCORE CASES (TOP 10) ================")
    for row in result.low_score_cases[:10]:
        print(
            {
                "case_id": row.get("case_id"),
                "score_100": row.get("score_100"),
                "complaint_name": row.get("complaint_name"),
                "problem_tags": row.get("problem_tags"),
                "fix_suggestions": row.get("fix_suggestions"),
            }
        )

    print("\n================ REMINDER ================")
    print(result.reminder)

    print("\n================ ARTIFACTS ================")
    for key, path in paths.items():
        print(f"{key}: {path}")

    print("\njson_summary:", asdict(result))


if __name__ == "__main__":
    main()

