from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.services.food_self_tuning_pipeline import FoodSelfTuningPipeline


def _convert(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {k: _convert(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_convert(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _convert(v) for k, v in dict(value.__dict__).items()}
    return value


def _map_failed_cases(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        case_id = str(row.get("id", ""))
        if case_id:
            out[case_id] = row
    return out


def _top_changed_failed_cases(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
    limit: int = 20,
) -> list[dict[str, Any]]:
    before = _map_failed_cases(before_rows)
    after = _map_failed_cases(after_rows)
    improved_ids = sorted(set(before.keys()) - set(after.keys()))
    regressed_ids = sorted(set(after.keys()) - set(before.keys()))
    unchanged_ids = sorted(set(before.keys()) & set(after.keys()))

    out: list[dict[str, Any]] = []
    for cid in improved_ids[:limit]:
        out.append({"case_id": cid, "status": "improved", "before": before.get(cid), "after": None})
    for cid in regressed_ids[:limit]:
        out.append({"case_id": cid, "status": "regressed", "before": None, "after": after.get(cid)})
    for cid in unchanged_ids[: max(0, limit - len(out))]:
        out.append({"case_id": cid, "status": "unchanged_failed", "before": before.get(cid), "after": after.get(cid)})
    return out[:limit]


def _top_high_priority_deltas(applied_rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    high = [x for x in (applied_rows or []) if str(x.get("priority", "")).lower() == "high"]
    return high[:limit]


def build_self_tuning_report(limit: int = 20) -> dict[str, Any]:
    pipeline = FoodSelfTuningPipeline()
    result = pipeline.run()

    base = _convert(result.base_scoreboard)
    patched = _convert(result.patched_scoreboard)
    patch_apply = _convert(result.patch_apply_result)

    report = {
        "comparison": _convert(result.comparison),
        "top_changed_failed_cases": _top_changed_failed_cases(
            before_rows=list(base.get("failed_cases", []) or []),
            after_rows=list(patched.get("failed_cases", []) or []),
            limit=limit,
        ),
        "top_applied_high_priority_deltas": _top_high_priority_deltas(
            applied_rows=list(patch_apply.get("applied", []) or []),
            limit=limit,
        ),
        "summary": {
            "before_overall": base.get("overall", {}),
            "after_overall": patched.get("overall", {}),
            "patch_apply_summary": patch_apply.get("summary", {}),
        },
    }
    return report


def save_self_tuning_report(
    report: dict[str, Any],
    *,
    output_dir: str | Path = "./food_training_artifacts",
    json_name: str = "food_self_tuning_report.json",
    md_name: str = "food_self_tuning_report.md",
) -> dict[str, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / json_name
    md_path = out_dir / md_name

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    comparison = report.get("comparison", {}).get("overall", {})
    lines = [
        "# Food Self-Tuning Report",
        "",
        "## Overall Delta",
        f"- pass_rate_delta: {comparison.get('pass_rate_delta', 0)}",
        f"- zone_accuracy_delta: {comparison.get('zone_accuracy_delta', 0)}",
        f"- cause_accuracy_delta: {comparison.get('cause_accuracy_delta', 0)}",
        f"- care_accuracy_delta: {comparison.get('care_accuracy_delta', 0)}",
        "",
        "## Top Changed Failed Cases",
    ]
    for row in report.get("top_changed_failed_cases", []):
        lines.append(f"- {row.get('case_id')}: {row.get('status')}")
    lines.append("")
    lines.append("## Top Applied High-Priority Deltas")
    for row in report.get("top_applied_high_priority_deltas", []):
        lines.append(f"- {row.get('path')} ({row.get('op')})")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    return {"json_path": json_path, "md_path": md_path}


if __name__ == "__main__":
    report = build_self_tuning_report(limit=20)
    paths = save_self_tuning_report(report)
    print("json_path:", paths["json_path"])
    print("md_path:", paths["md_path"])
