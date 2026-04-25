from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from app.services.food_consultation_engine import FoodConsultationEngine
from app.services.food_failure_analyzer import FoodFailureAnalyzer
from app.services.food_patch_applier import FoodPatchApplier
from app.services.food_patch_generator import FoodPatchGenerator
from app.services.food_regression_scoreboard import FoodRegressionScoreboard
from app.services.food_runtime_patch_integration import FoodRuntimePatchIntegration
from app.services.food_tuning_advisor import FoodTuningAdvisor


@dataclass
class SelfTuningRunResult:
    base_scoreboard: Any
    failure_analysis: Any
    tuning_advice: Any
    patch_result: Any
    patch_apply_result: Any
    patched_scoreboard: Any
    comparison: dict[str, Any]


class PatchedFoodConsultationEngine(FoodConsultationEngine):
    """
    Drop-in engine wrapper that applies runtime patch integration
    on top of the existing FoodConsultationEngine logic.

    Assumes the base engine exposes consult(), and that the returned
    doctor_view/machine_view contains zone/cause/care data.
    """

    def __init__(self, runtime_patch_config: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.runtime_patch = FoodRuntimePatchIntegration(runtime_patch_config or {})

    def consult(
        self,
        user_text: str,
        *,
        context: Any = None,
        memory_state: Any = None,
        food_journal_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        result = super().consult(
            user_text,
            context=context,
            memory_state=memory_state,
            food_journal_entries=food_journal_entries,
        )

        doctor_view = result.get("doctor_view", {}) or {}
        patient_view = result.get("patient_view", {}) or {}
        machine_view = result.get("machine_view", {}) or {}

        normalized = str(doctor_view.get("normalized_input", "") or machine_view.get("normalized_input", ""))
        zone = str(doctor_view.get("zone", "") or machine_view.get("zone", ""))
        trigger_groups = list(doctor_view.get("trigger_groups", []) or machine_view.get("trigger_groups", []))
        ranked_causes = list(doctor_view.get("ranked_causes", []) or machine_view.get("ranked_causes", []))
        cause_scores = dict(doctor_view.get("cause_scores", {}) or machine_view.get("cause_scores", {}))
        matched_red_flags = list(doctor_view.get("matched_red_flags", []) or machine_view.get("matched_red_flags", []))
        confidence = dict(doctor_view.get("confidence", {}) or {})
        confidence_level = str(confidence.get("level", "medium"))
        care_level_obj = doctor_view.get("care_level", {})
        current_care_level = (
            str(care_level_obj.get("level", "home"))
            if isinstance(care_level_obj, dict)
            else str(patient_view.get("care_level", "home"))
        )

        recurrent = bool(getattr(context, "recurrent", False)) if context is not None else False
        repeated_pattern = False
        memory_summary = doctor_view.get("memory_summary", {}) or machine_view.get("memory_summary", {})
        if isinstance(memory_summary, dict):
            repeated_pattern = bool(memory_summary.get("repeated_trigger_groups"))

        # lightweight zone_scores reconstruction for runtime boosting
        zone_scores = {zone: 10} if zone else {}

        patched = self.runtime_patch.apply_full_runtime_patch(
            normalized_text=normalized,
            trigger_groups=trigger_groups,
            zone_scores=zone_scores,
            cause_scores=cause_scores,
            matched_red_flags=matched_red_flags,
            recurrent=recurrent,
            care_level=current_care_level,
            confidence_level=confidence_level,
            repeated_pattern=repeated_pattern,
            zone=zone,
            ranked_causes=ranked_causes,
        )

        patched_cause_scores = dict(sorted(patched["cause_scores"].items(), key=lambda x: x[1], reverse=True))
        patched_ranked_causes = list(patched_cause_scores.keys())[:5]

        # soften urgent if configured
        if result.get("patient_view", {}).get("care_level") in {"urgent", "emergency"} and patched.get("soften_urgent_route"):
            patient_view["care_level"] = "routine_doctor"
            if isinstance(doctor_view.get("care_level"), dict):
                doctor_view["care_level"]["level"] = "routine_doctor"
                doctor_view["care_level"]["reason"] = "Runtime patch softened urgent routing."
                doctor_view["care_level"]["action_hint"] = "Нужна очная оценка, но без признаков обязательной немедленной эскалации."

        # apply patched care level
        patient_view["care_level"] = patched["care_level"]
        if isinstance(doctor_view.get("care_level"), dict):
            doctor_view["care_level"]["level"] = patched["care_level"]

        # replace ranked causes / cause scores
        doctor_view["cause_scores"] = patched_cause_scores
        doctor_view["ranked_causes"] = patched_ranked_causes
        machine_view["cause_scores"] = patched_cause_scores
        machine_view["ranked_causes"] = patched_ranked_causes

        # expose runtime patch debug
        machine_view["runtime_patch"] = {
            "active_context_flags": patched.get("active_context_flags", []),
            "soften_urgent_route": patched.get("soften_urgent_route", False),
            "patched_care_level": patched.get("care_level"),
        }

        result["doctor_view"] = doctor_view
        result["patient_view"] = patient_view
        result["machine_view"] = machine_view
        return result


class FoodSelfTuningPipeline:
    """
    Full self-tuning loop for the food engine.

    Steps:
      1. run baseline regression
      2. analyze failures
      3. build tuning advice
      4. generate patch package
      5. apply patch package to runtime config
      6. run patched regression
      7. compare before/after
    """

    def __init__(
        self,
        *,
        base_engine_factory: Callable[[], Any] | None = None,
        patched_engine_factory: Callable[[dict[str, Any]], Any] | None = None,
        base_runtime_config: dict[str, Any] | None = None,
    ) -> None:
        self.base_engine_factory = base_engine_factory or (lambda: FoodConsultationEngine())
        self.patched_engine_factory = patched_engine_factory or (lambda cfg: PatchedFoodConsultationEngine(cfg))
        self.base_runtime_config = deepcopy(base_runtime_config or {})

    def run(self) -> SelfTuningRunResult:
        # 1. Baseline
        base_engine = self.base_engine_factory()
        base_scoreboard = FoodRegressionScoreboard(base_engine).run()

        # 2. Failure analysis
        failure_analysis = FoodFailureAnalyzer().analyze(base_scoreboard)

        # 3. Tuning advice
        tuning_advice = FoodTuningAdvisor().advise(failure_analysis)

        # 4. Patch generation
        patch_result = FoodPatchGenerator().generate(tuning_advice)

        # 5. Patch apply
        patch_apply_result = FoodPatchApplier().apply(
            base_config=self.base_runtime_config,
            patch_result=patch_result,
        )

        # 6. Patched regression
        patched_engine = self.patched_engine_factory(patch_apply_result.patched_config)
        patched_scoreboard = FoodRegressionScoreboard(patched_engine).run()

        # 7. Compare
        comparison = self._compare_scoreboards(base_scoreboard, patched_scoreboard)

        return SelfTuningRunResult(
            base_scoreboard=base_scoreboard,
            failure_analysis=failure_analysis,
            tuning_advice=tuning_advice,
            patch_result=patch_result,
            patch_apply_result=patch_apply_result,
            patched_scoreboard=patched_scoreboard,
            comparison=comparison,
        )

    def _compare_scoreboards(self, before: Any, after: Any) -> dict[str, Any]:
        before_dict = self._scoreboard_to_dict(before)
        after_dict = self._scoreboard_to_dict(after)

        overall_before = before_dict.get("overall", {})
        overall_after = after_dict.get("overall", {})

        comparison = {
            "overall": {
                "pass_rate_before": overall_before.get("pass_rate", 0.0),
                "pass_rate_after": overall_after.get("pass_rate", 0.0),
                "pass_rate_delta": round(
                    float(overall_after.get("pass_rate", 0.0)) - float(overall_before.get("pass_rate", 0.0)),
                    1,
                ),
                "zone_accuracy_before": overall_before.get("zone_accuracy", 0.0),
                "zone_accuracy_after": overall_after.get("zone_accuracy", 0.0),
                "zone_accuracy_delta": round(
                    float(overall_after.get("zone_accuracy", 0.0)) - float(overall_before.get("zone_accuracy", 0.0)),
                    1,
                ),
                "cause_accuracy_before": overall_before.get("cause_accuracy", 0.0),
                "cause_accuracy_after": overall_after.get("cause_accuracy", 0.0),
                "cause_accuracy_delta": round(
                    float(overall_after.get("cause_accuracy", 0.0)) - float(overall_before.get("cause_accuracy", 0.0)),
                    1,
                ),
                "care_accuracy_before": overall_before.get("care_accuracy", 0.0),
                "care_accuracy_after": overall_after.get("care_accuracy", 0.0),
                "care_accuracy_delta": round(
                    float(overall_after.get("care_accuracy", 0.0)) - float(overall_before.get("care_accuracy", 0.0)),
                    1,
                ),
            },
            "tiers": self._compare_tiers(
                before_dict.get("tiers", {}),
                after_dict.get("tiers", {}),
            ),
        }
        return comparison

    def _compare_tiers(self, before_tiers: dict[str, Any], after_tiers: dict[str, Any]) -> dict[str, Any]:
        all_tiers = sorted(set(before_tiers.keys()) | set(after_tiers.keys()))
        out: dict[str, Any] = {}

        for tier in all_tiers:
            b = self._to_plain_dict(before_tiers.get(tier, {}))
            a = self._to_plain_dict(after_tiers.get(tier, {}))
            out[tier] = {
                "pass_rate_before": b.get("pass_rate", 0.0),
                "pass_rate_after": a.get("pass_rate", 0.0),
                "pass_rate_delta": round(float(a.get("pass_rate", 0.0)) - float(b.get("pass_rate", 0.0)), 1),
                "zone_accuracy_before": b.get("zone_accuracy", 0.0),
                "zone_accuracy_after": a.get("zone_accuracy", 0.0),
                "zone_accuracy_delta": round(float(a.get("zone_accuracy", 0.0)) - float(b.get("zone_accuracy", 0.0)), 1),
                "cause_accuracy_before": b.get("cause_accuracy", 0.0),
                "cause_accuracy_after": a.get("cause_accuracy", 0.0),
                "cause_accuracy_delta": round(float(a.get("cause_accuracy", 0.0)) - float(b.get("cause_accuracy", 0.0)), 1),
                "care_accuracy_before": b.get("care_accuracy", 0.0),
                "care_accuracy_after": a.get("care_accuracy", 0.0),
                "care_accuracy_delta": round(float(a.get("care_accuracy", 0.0)) - float(b.get("care_accuracy", 0.0)), 1),
            }

        return out

    def _scoreboard_to_dict(self, scoreboard: Any) -> dict[str, Any]:
        if isinstance(scoreboard, dict):
            return scoreboard
        return {
            "overall": self._to_plain_dict(getattr(scoreboard, "overall", {})),
            "tiers": self._to_plain_dict(getattr(scoreboard, "tiers", {})),
            "common_failures": getattr(scoreboard, "common_failures", []),
            "failed_cases": getattr(scoreboard, "failed_cases", []),
        }

    def _to_plain_dict(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return {}


def print_self_tuning_result(result: SelfTuningRunResult) -> None:
    print("\n================ BASELINE OVERALL ================")
    print(result.base_scoreboard.overall if hasattr(result.base_scoreboard, "overall") else result.base_scoreboard.get("overall"))

    print("\n================ PATCH SUMMARY ===================")
    patch_summary = result.patch_apply_result.summary if hasattr(result.patch_apply_result, "summary") else {}
    for k, v in patch_summary.items():
        print(f"{k}: {v}")

    print("\n================ COMPARISON ======================")
    for section, payload in result.comparison.items():
        print(f"\n[{section}]")
        if isinstance(payload, dict):
            for k, v in payload.items():
                print(f"{k}: {v}")
        else:
            print(payload)

    print("\n================ PATCHED OVERALL ================")
    print(result.patched_scoreboard.overall if hasattr(result.patched_scoreboard, "overall") else result.patched_scoreboard.get("overall"))


if __name__ == "__main__":
    pipeline = FoodSelfTuningPipeline()
    result = pipeline.run()
    print_self_tuning_result(result)
