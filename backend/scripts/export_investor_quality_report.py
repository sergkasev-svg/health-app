from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _evaluate(metrics: dict[str, float], thresholds: dict[str, float]) -> list[str]:
    failures: list[str] = []
    if float(metrics.get("total_cases", 0.0)) < float(thresholds.get("min_total_cases", 0.0)):
        failures.append("total_cases")
    if float(metrics.get("loop_rate", 1.0)) > float(thresholds.get("max_loop_rate", 0.0)):
        failures.append("loop_rate")
    if float(metrics.get("domain_drift_rate", 1.0)) > float(thresholds.get("max_domain_drift_rate", 0.0)):
        failures.append("domain_drift_rate")
    if float(metrics.get("redflag_recall", 0.0)) < float(thresholds.get("min_redflag_recall", 0.0)):
        failures.append("redflag_recall")
    if float(metrics.get("repair_success_at_1", 0.0)) < float(thresholds.get("min_repair_success_at_1", 0.0)):
        failures.append("repair_success_at_1")
    if float(metrics.get("non_empty_response_rate", 0.0)) < float(thresholds.get("min_non_empty_response_rate", 0.0)):
        failures.append("non_empty_response_rate")
    min_human_tone = thresholds.get("min_human_tone_rate")
    if isinstance(min_human_tone, (int, float)):
        if float(metrics.get("human_tone_rate", 0.0)) < float(min_human_tone):
            failures.append("human_tone_rate")
    return failures


def _run_level(backend_root: Path, level: str) -> dict[str, Any]:
    from tests.clinical.harness_runner import run_clinical_dialog_harness

    if level == "v1":
        cases_path = backend_root / "tests" / "clinical" / "cases_clinical_v1.jsonl"
        thresholds_path = backend_root / "tests" / "clinical" / "release_gate_thresholds_v1.json"
    else:
        cases_path = backend_root / "tests" / "clinical" / "cases_endocrine_starter.jsonl"
        thresholds_path = backend_root / "tests" / "clinical" / "release_gate_thresholds.json"

    thresholds = _load_json(thresholds_path)
    metrics = run_clinical_dialog_harness(str(cases_path))
    failures = _evaluate(metrics, thresholds)
    return {
        "level": level,
        "cases_file": str(cases_path),
        "thresholds_file": str(thresholds_path),
        "thresholds": thresholds,
        "metrics": metrics,
        "status": "PASS" if not failures else "FAIL",
        "failed_metrics": failures,
    }


def _build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Investor Quality Report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{report['generated_at_utc']}`")
    lines.append(f"- Overall status: **{report['overall_status']}**")
    lines.append("")
    lines.append("## Levels")
    lines.append("")
    for level in report.get("levels", []):
        metrics = level.get("metrics") or {}
        lines.append(f"### {level.get('level')}")
        lines.append(f"- Status: **{level.get('status')}**")
        lines.append(f"- Cases: `{int(metrics.get('total_cases', 0))}`")
        lines.append(f"- loop_rate: `{metrics.get('loop_rate'):.4f}`")
        lines.append(f"- domain_drift_rate: `{metrics.get('domain_drift_rate'):.4f}`")
        lines.append(f"- redflag_recall: `{metrics.get('redflag_recall'):.4f}`")
        lines.append(f"- repair_success_at_1: `{metrics.get('repair_success_at_1'):.4f}`")
        lines.append(f"- non_empty_response_rate: `{metrics.get('non_empty_response_rate'):.4f}`")
        if "human_tone_rate" in metrics:
            lines.append(f"- human_tone_rate: `{metrics.get('human_tone_rate'):.4f}`")
        failed = list(level.get("failed_metrics") or [])
        lines.append(f"- Failed metrics: `{', '.join(failed) if failed else 'none'}`")
        lines.append("")
    lines.append("## Evidence")
    lines.append("")
    lines.append("- Release gate outputs: `tests/clinical/reports/release_gate_latest.json`")
    lines.append("- Smoke outputs: `tests/clinical/reports/latest_metrics.json`")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    backend_root = Path(__file__).resolve().parents[1]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    levels = [_run_level(backend_root, "starter"), _run_level(backend_root, "v1")]
    overall_status = "PASS" if all(x.get("status") == "PASS" for x in levels) else "FAIL"
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall_status": overall_status,
        "levels": levels,
    }

    reports_dir = backend_root / "tests" / "clinical" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "investor_quality_report_latest.json"
    md_path = reports_dir / "investor_quality_report_latest.md"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_ts = reports_dir / f"investor_quality_report_{ts}.json"
    md_ts = reports_dir / f"investor_quality_report_{ts}.md"

    json_payload = json.dumps(report, ensure_ascii=False, indent=2)
    md_payload = _build_markdown(report)
    json_path.write_text(json_payload, encoding="utf-8")
    md_path.write_text(md_payload, encoding="utf-8")
    json_ts.write_text(json_payload, encoding="utf-8")
    md_ts.write_text(md_payload, encoding="utf-8")

    print(f"Investor report status: {overall_status}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {md_path}")
    return 0 if overall_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

