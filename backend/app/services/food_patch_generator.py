from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PatchDelta:
    path: str
    op: str
    value: Any
    rationale: str
    priority: str


@dataclass
class FoodPatchResult:
    summary: dict[str, Any]
    patch_deltas: list[PatchDelta]
    grouped_patch: dict[str, Any]


class FoodPatchGenerator:
    """
    Converts FoodTuningAdvisor suggestions into a machine-readable patch package.

    Supported patch buckets:
      - zone_weight_boosts
      - cause_score_boosts
      - cause_score_reductions
      - urgent_threshold_changes
      - care_level_changes
      - recurrent_logic_changes
    """

    def generate(self, tuning_advice: Any) -> FoodPatchResult:
        suggestions = self._extract_suggestions(tuning_advice)

        patch_deltas: list[PatchDelta] = []

        for suggestion in suggestions:
            patch_deltas.extend(self._suggestion_to_patch_deltas(suggestion))

        grouped_patch = self._group_patch_deltas(patch_deltas)

        summary = {
            "suggestions_in": len(suggestions),
            "patch_deltas_out": len(patch_deltas),
            "zone_weight_boosts": len(grouped_patch.get("zone_weight_boosts", [])),
            "cause_score_boosts": len(grouped_patch.get("cause_score_boosts", [])),
            "cause_score_reductions": len(grouped_patch.get("cause_score_reductions", [])),
            "urgent_threshold_changes": len(grouped_patch.get("urgent_threshold_changes", [])),
            "care_level_changes": len(grouped_patch.get("care_level_changes", [])),
            "recurrent_logic_changes": len(grouped_patch.get("recurrent_logic_changes", [])),
        }

        return FoodPatchResult(
            summary=summary,
            patch_deltas=patch_deltas,
            grouped_patch=grouped_patch,
        )

    def to_jsonable(self, result: FoodPatchResult) -> dict[str, Any]:
        return {
            "summary": result.summary,
            "patch_deltas": [asdict(x) for x in result.patch_deltas],
            "grouped_patch": result.grouped_patch,
        }

    def _extract_suggestions(self, tuning_advice: Any) -> list[Any]:
        if hasattr(tuning_advice, "suggestions"):
            return list(getattr(tuning_advice, "suggestions", []))
        if isinstance(tuning_advice, dict):
            return list(tuning_advice.get("suggestions", []))
        return []

    def _suggestion_to_patch_deltas(self, suggestion: Any) -> list[PatchDelta]:
        priority = self._get_attr(suggestion, "priority", "medium")
        category = self._get_attr(suggestion, "category", "")
        target = self._get_attr(suggestion, "target", "")
        action = self._get_attr(suggestion, "action", "")
        rationale = self._get_attr(suggestion, "rationale", "")
        patch = self._get_attr(suggestion, "suggested_patch", {}) or {}

        deltas: list[PatchDelta] = []

        if category == "zone_routing" and action == "increase_zone_weight":
            for symptom in patch.get("boost_symptoms", []):
                deltas.append(
                    PatchDelta(
                        path=f"zone_weight_boosts.{target}.{symptom}",
                        op="upsert",
                        value={
                            "delta": 2,
                            "expected_zone": target,
                            "reduce_competition_from": patch.get("reduce_competition_from", []),
                        },
                        rationale=rationale,
                        priority=priority,
                    )
                )

            for trigger_group in patch.get("boost_trigger_groups", []):
                deltas.append(
                    PatchDelta(
                        path=f"zone_weight_boosts.{target}.__trigger__:{trigger_group}",
                        op="upsert",
                        value={
                            "delta": 2,
                            "expected_zone": target,
                        },
                        rationale=rationale,
                        priority=priority,
                    )
                )

        elif category == "cause_scoring" and action in {
            "increase_cause_weight",
            "increase_conditional_weight",
            "increase_recurrent_weight",
        }:
            cause = patch.get("cause", target)
            delta = patch.get("suggested_score_delta", 3)

            for evidence in patch.get("boost_evidence", []):
                deltas.append(
                    PatchDelta(
                        path=f"cause_score_boosts.{cause}.{evidence}",
                        op="upsert",
                        value={
                            "delta": delta,
                            "require_combination": patch.get("require_combination", False),
                        },
                        rationale=rationale,
                        priority=priority,
                    )
                )

            if "recurrent_bonus_delta" in patch:
                deltas.append(
                    PatchDelta(
                        path=f"recurrent_logic_changes.{cause}.recurrent_bonus_delta",
                        op="upsert",
                        value=patch["recurrent_bonus_delta"],
                        rationale=rationale,
                        priority=priority,
                    )
                )

        elif category == "cause_scoring" and action in {
            "decrease_fallback_weight",
            "narrow_trigger_scope",
        }:
            cause = patch.get("cause", target)
            delta = patch.get("suggested_score_delta", -2)

            deltas.append(
                PatchDelta(
                    path=f"cause_score_reductions.{cause}.__global__",
                    op="upsert",
                    value={
                        "delta": delta,
                        "reduce_when": patch.get("reduce_when", []),
                    },
                    rationale=rationale,
                    priority=priority,
                )
            )

        elif category == "urgent_routing":
            deltas.append(
                PatchDelta(
                    path="urgent_threshold_changes.global",
                    op="merge",
                    value=patch,
                    rationale=rationale,
                    priority=priority,
                )
            )

        elif category == "care_level":
            deltas.append(
                PatchDelta(
                    path=f"care_level_changes.{target}.{action}",
                    op="merge",
                    value=patch,
                    rationale=rationale,
                    priority=priority,
                )
            )

        else:
            deltas.append(
                PatchDelta(
                    path=f"unclassified.{target or 'unknown'}",
                    op="append",
                    value={
                        "category": category,
                        "action": action,
                        "patch": patch,
                    },
                    rationale=rationale,
                    priority=priority,
                )
            )

        return deltas

    def _group_patch_deltas(self, patch_deltas: list[PatchDelta]) -> dict[str, Any]:
        grouped: dict[str, Any] = {
            "zone_weight_boosts": [],
            "cause_score_boosts": [],
            "cause_score_reductions": [],
            "urgent_threshold_changes": [],
            "care_level_changes": [],
            "recurrent_logic_changes": [],
            "unclassified": [],
        }

        for delta in patch_deltas:
            root = delta.path.split(".", 1)[0]
            payload = {
                "path": delta.path,
                "op": delta.op,
                "value": delta.value,
                "rationale": delta.rationale,
                "priority": delta.priority,
            }
            if root in grouped:
                grouped[root].append(payload)
            else:
                grouped["unclassified"].append(payload)

        return grouped

    @staticmethod
    def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
        if hasattr(obj, name):
            return getattr(obj, name, default)
        if isinstance(obj, dict):
            return obj.get(name, default)
        return default


def print_patch_result(result: FoodPatchResult) -> None:
    print("\n================ PATCH SUMMARY ================")
    for k, v in result.summary.items():
        print(f"{k}: {v}")

    print("\n================ PATCH DELTAS =================")
    if not result.patch_deltas:
        print("No patch deltas")
    else:
        for idx, delta in enumerate(result.patch_deltas, start=1):
            print(f"\n--- Delta #{idx} ---")
            print("path:", delta.path)
            print("op:", delta.op)
            print("value:", delta.value)
            print("priority:", delta.priority)
            print("rationale:", delta.rationale)

    print("\n=============== GROUPED PATCH =================")
    for group_name, items in result.grouped_patch.items():
        print(f"\n[{group_name}]")
        if not items:
            print("  - empty")
        else:
            for item in items:
                print(" ", item)


if __name__ == "__main__":
    from app.services.food_consultation_engine import FoodConsultationEngine
    from app.services.food_failure_analyzer import FoodFailureAnalyzer
    from app.services.food_regression_scoreboard import FoodRegressionScoreboard
    from app.services.food_tuning_advisor import FoodTuningAdvisor

    engine = FoodConsultationEngine()

    scoreboard_result = FoodRegressionScoreboard(engine).run()
    analysis = FoodFailureAnalyzer().analyze(scoreboard_result)
    advice = FoodTuningAdvisor().advise(analysis)

    patch_result = FoodPatchGenerator().generate(advice)
    print_patch_result(patch_result)
