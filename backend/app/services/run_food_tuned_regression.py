from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.food_self_tuning_pipeline import FoodSelfTuningPipeline


@dataclass
class TunedRegressionSummary:
    before: dict[str, Any]
    after: dict[str, Any]
    delta: dict[str, Any]
    top_changes: dict[str, Any]


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _index_failures(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for row in rows or []:
        key = str(row.get("failure_type", "unknown"))
        out[key] = int(row.get("count", 0))
    return out


def _failure_delta(
    before_rows: list[dict[str, Any]],
    after_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    before = _index_failures(before_rows)
    after = _index_failures(after_rows)
    keys = sorted(set(before.keys()) | set(after.keys()))
    deltas: list[dict[str, Any]] = []
    for key in keys:
        b = before.get(key, 0)
        a = after.get(key, 0)
        deltas.append(
            {
                "failure_type": key,
                "before": b,
                "after": a,
                "delta": a - b,
            }
        )
    deltas.sort(key=lambda x: abs(int(x["delta"])), reverse=True)
    return deltas


def run_tuned_regression() -> TunedRegressionSummary:
    pipeline = FoodSelfTuningPipeline()
    result = pipeline.run()

    before = _to_dict(result.base_scoreboard)
    after = _to_dict(result.patched_scoreboard)
    comparison = result.comparison

    top_fail_changes = _failure_delta(
        before_rows=list(before.get("common_failures", []) or []),
        after_rows=list(after.get("common_failures", []) or []),
    )
    top_failed_case_delta = {
        "failed_cases_before": len(list(before.get("failed_cases", []) or [])),
        "failed_cases_after": len(list(after.get("failed_cases", []) or [])),
        "failed_cases_delta": len(list(after.get("failed_cases", []) or [])) - len(list(before.get("failed_cases", []) or [])),
    }

    return TunedRegressionSummary(
        before=before.get("overall", {}),
        after=after.get("overall", {}),
        delta=comparison.get("overall", {}),
        top_changes={
            "failure_type_delta_top10": top_fail_changes[:10],
            "failed_cases_delta": top_failed_case_delta,
            "tier_delta": comparison.get("tiers", {}),
        },
    )


def print_tuned_regression(summary: TunedRegressionSummary) -> None:
    print("\n================ BEFORE =================")
    for k, v in summary.before.items():
        print(f"{k}: {v}")

    print("\n================ AFTER ==================")
    for k, v in summary.after.items():
        print(f"{k}: {v}")

    print("\n================ DELTA ==================")
    for k, v in summary.delta.items():
        print(f"{k}: {v}")

    print("\n=========== TOP CHANGES (ZONE/CAUSE/CARE) ===========")
    for row in summary.top_changes.get("failure_type_delta_top10", []):
        print(row)

    print("\n=========== FAILED CASES DELTA ===========")
    print(summary.top_changes.get("failed_cases_delta", {}))

    print("\n=========== TIER DELTA ===========")
    for tier, payload in summary.top_changes.get("tier_delta", {}).items():
        print(f"{tier}: {payload}")


if __name__ == "__main__":
    summary = run_tuned_regression()
    print_tuned_regression(summary)
    print("\njson_summary:", asdict(summary))
