from __future__ import annotations

import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _evaluate(metrics: dict[str, float], thresholds: dict[str, float]) -> list[str]:
    failures: list[str] = []
    if float(metrics.get("total_cases", 0.0)) < float(thresholds.get("min_total_cases", 0.0)):
        failures.append(
            f"total_cases={metrics.get('total_cases')} < min_total_cases={thresholds.get('min_total_cases')}"
        )
    if float(metrics.get("loop_rate", 1.0)) > float(thresholds.get("max_loop_rate", 0.0)):
        failures.append(f"loop_rate={metrics.get('loop_rate')} > max_loop_rate={thresholds.get('max_loop_rate')}")
    if float(metrics.get("domain_drift_rate", 1.0)) > float(thresholds.get("max_domain_drift_rate", 0.0)):
        failures.append(
            "domain_drift_rate="
            f"{metrics.get('domain_drift_rate')} > max_domain_drift_rate={thresholds.get('max_domain_drift_rate')}"
        )
    if float(metrics.get("redflag_recall", 0.0)) < float(thresholds.get("min_redflag_recall", 0.0)):
        failures.append(
            f"redflag_recall={metrics.get('redflag_recall')} < min_redflag_recall={thresholds.get('min_redflag_recall')}"
        )
    if float(metrics.get("repair_success_at_1", 0.0)) < float(thresholds.get("min_repair_success_at_1", 0.0)):
        failures.append(
            "repair_success_at_1="
            f"{metrics.get('repair_success_at_1')} < min_repair_success_at_1={thresholds.get('min_repair_success_at_1')}"
        )
    if float(metrics.get("non_empty_response_rate", 0.0)) < float(thresholds.get("min_non_empty_response_rate", 0.0)):
        failures.append(
            "non_empty_response_rate="
            f"{metrics.get('non_empty_response_rate')} < min_non_empty_response_rate={thresholds.get('min_non_empty_response_rate')}"
        )
    if float(metrics.get("human_tone_rate", 0.0)) < float(thresholds.get("min_human_tone_rate", 0.0)):
        failures.append(
            "human_tone_rate="
            f"{metrics.get('human_tone_rate')} < min_human_tone_rate={thresholds.get('min_human_tone_rate')}"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run clinical release gate")
    parser.add_argument(
        "--level",
        choices=["starter", "v1", "v1-ci"],
        default="starter",
        help=(
            "Gate level: starter (35 cases), v1 (full expanded clinical pack), "
            "or v1-ci (expect-focused lightweight pack for CI)."
        ),
    )
    args = parser.parse_args()

    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from tests.clinical.harness_runner import run_clinical_dialog_harness

    if args.level == "v1":
        cases_path = backend_root / "tests" / "clinical" / "cases_clinical_v1.jsonl"
        thresholds_path = backend_root / "tests" / "clinical" / "release_gate_thresholds_v1.json"
    elif args.level == "v1-ci":
        cases_path = backend_root / "tests" / "clinical" / "cases_clinical_v1_ci_expect.jsonl"
        thresholds_path = backend_root / "tests" / "clinical" / "release_gate_thresholds_v1_ci.json"
    else:
        cases_path = backend_root / "tests" / "clinical" / "cases_endocrine_starter.jsonl"
        thresholds_path = backend_root / "tests" / "clinical" / "release_gate_thresholds.json"
    reports_dir = backend_root / "tests" / "clinical" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    thresholds = _load_json(thresholds_path)
    metrics = run_clinical_dialog_harness(str(cases_path))
    failures = _evaluate(metrics, thresholds)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cases_file": str(cases_path),
        "thresholds_file": str(thresholds_path),
        "gate_level": args.level,
        "thresholds": thresholds,
        "metrics": metrics,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }
    out_name = "release_gate_latest.json" if args.level in ("starter", "v1") else "release_gate_v1_ci_latest.json"
    out_path = reports_dir / out_name
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if failures:
        print("Clinical release gate: FAIL")
        for item in failures:
            print(f"- {item}")
        print(f"Report: {out_path}")
        return 1

    print("Clinical release gate: PASS")
    print(json.dumps(metrics, ensure_ascii=False))
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

