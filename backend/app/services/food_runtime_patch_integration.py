from __future__ import annotations

from copy import deepcopy
from typing import Any


class FoodRuntimePatchIntegration:
    """
    Runtime patch applicator for FoodConsultationEngine-style logic.

    Expects patched_config like:
    {
      "zone_weight_boosts": {...},
      "cause_score_boosts": {...},
      "cause_score_reductions": {...},
      "urgent_threshold_changes": {...},
      "care_level_changes": {...},
      "recurrent_logic_changes": {...}
    }
    """

    def __init__(self, runtime_patch_config: dict[str, Any] | None = None) -> None:
        self.runtime_patch_config = deepcopy(runtime_patch_config or {})

    # ============================================================
    # ZONE PATCHES
    # ============================================================

    def apply_zone_weight_boosts(
        self,
        *,
        zone_scores: dict[str, int],
        normalized_text: str,
        trigger_groups: list[str],
    ) -> dict[str, int]:
        patched = deepcopy(zone_scores)
        boosts = self.runtime_patch_config.get("zone_weight_boosts", {}) or {}

        for zone_name, zone_rules in boosts.items():
            if zone_name not in patched:
                patched[zone_name] = 0

            if not isinstance(zone_rules, dict):
                continue

            for key, payload in zone_rules.items():
                if not isinstance(payload, dict):
                    continue

                delta = int(payload.get("delta", 0))

                # trigger pseudo-key
                if key.startswith("__trigger__:"):
                    trigger_group = key.split(":", 1)[1]
                    if trigger_group in trigger_groups:
                        patched[zone_name] += delta
                    continue

                # phrase match
                if key in normalized_text:
                    patched[zone_name] += delta

        return patched

    # ============================================================
    # CAUSE PATCHES
    # ============================================================

    def apply_cause_score_boosts(
        self,
        *,
        cause_scores: dict[str, int],
        normalized_text: str,
        recurrent: bool,
    ) -> dict[str, int]:
        patched = deepcopy(cause_scores)
        boosts = self.runtime_patch_config.get("cause_score_boosts", {}) or {}

        for cause_id, rules in boosts.items():
            if not isinstance(rules, dict):
                continue
            if cause_id not in patched:
                patched[cause_id] = 0

            matched_count = 0

            for evidence_key, payload in rules.items():
                if not isinstance(payload, dict):
                    continue

                require_combination = bool(payload.get("require_combination", False))
                delta = int(payload.get("delta", 0))

                if evidence_key in normalized_text:
                    matched_count += 1

                if not require_combination and evidence_key in normalized_text:
                    patched[cause_id] += delta

            # If combination required, apply only when 2+ matched
            if matched_count >= 2:
                for evidence_key, payload in rules.items():
                    if not isinstance(payload, dict):
                        continue
                    if bool(payload.get("require_combination", False)):
                        if evidence_key in normalized_text:
                            patched[cause_id] += int(payload.get("delta", 0))

        # recurrent bonus patch
        if recurrent:
            recurrent_logic = self.runtime_patch_config.get("recurrent_logic_changes", {}) or {}
            for cause_id, cause_patch in recurrent_logic.items():
                if not isinstance(cause_patch, dict):
                    continue
                bonus = int(cause_patch.get("recurrent_bonus_delta", 0))
                if cause_id in patched:
                    patched[cause_id] += bonus

        return patched

    def apply_cause_score_reductions(
        self,
        *,
        cause_scores: dict[str, int],
        active_context_flags: list[str],
    ) -> dict[str, int]:
        patched = deepcopy(cause_scores)
        reductions = self.runtime_patch_config.get("cause_score_reductions", {}) or {}

        for cause_id, rules in reductions.items():
            if cause_id not in patched:
                continue
            if not isinstance(rules, dict):
                continue

            global_rule = rules.get("__global__")
            if not isinstance(global_rule, dict):
                continue

            delta = int(global_rule.get("delta", 0))
            reduce_when = list(global_rule.get("reduce_when", []))

            if not reduce_when:
                patched[cause_id] += delta
                continue

            # apply reduction if any condition is active
            if any(flag in active_context_flags for flag in reduce_when):
                patched[cause_id] += delta

        return patched

    # ============================================================
    # URGENT PATCHES
    # ============================================================

    def apply_urgent_threshold_changes(
        self,
        *,
        matched_red_flags: list[str],
    ) -> dict[str, Any]:
        urgent_cfg = self.runtime_patch_config.get("urgent_threshold_changes", {}) or {}
        global_cfg = urgent_cfg.get("global", {}) if isinstance(urgent_cfg, dict) else {}

        result = {
            "matched_red_flags": matched_red_flags,
            "decrease_urgent_bias": bool(global_cfg.get("decrease_urgent_bias", False)),
            "require_more_specific_red_flags": bool(global_cfg.get("require_more_specific_red_flags", False)),
            "require_stronger_red_flag_combinations": bool(global_cfg.get("require_stronger_red_flag_combinations", False)),
            "review_red_flags": list(global_cfg.get("review_red_flags", [])),
        }
        return result

    def should_soften_urgent_route(
        self,
        *,
        matched_red_flags: list[str],
    ) -> bool:
        urgent_cfg = self.apply_urgent_threshold_changes(matched_red_flags=matched_red_flags)

        if not urgent_cfg["decrease_urgent_bias"]:
            return False

        if not urgent_cfg["require_more_specific_red_flags"] and not urgent_cfg["require_stronger_red_flag_combinations"]:
            return False

        reviewed = urgent_cfg["review_red_flags"]
        matched_reviewed = [x for x in matched_red_flags if x in reviewed] if reviewed else matched_red_flags

        if urgent_cfg["require_stronger_red_flag_combinations"]:
            return len(matched_reviewed) < 2

        if urgent_cfg["require_more_specific_red_flags"]:
            generic_flags = {"температура", "сильная боль", "рвота"}
            return all(flag in generic_flags for flag in matched_reviewed)

        return False

    # ============================================================
    # CARE LEVEL PATCHES
    # ============================================================

    def apply_care_level_changes(
        self,
        *,
        care_level: str,
        recurrent: bool,
        confidence_level: str,
        repeated_pattern: bool,
    ) -> str:
        patched_level = care_level
        cfg = self.runtime_patch_config.get("care_level_changes", {}) or {}

        # routine_doctor threshold patch
        routine_cfg = cfg.get("routine_doctor_threshold", {}) or {}
        lower_cfg = routine_cfg.get("lower_threshold_for_recurrent_cases", {}) or {}

        if lower_cfg:
            if (
                bool(lower_cfg.get("if_recurrent", False))
                and recurrent
                and lower_cfg.get("increase_care_level_to") == "routine_doctor"
            ):
                conditions = set(lower_cfg.get("conditions", []))
                active_conditions = set()

                if confidence_level in {"low", "medium"}:
                    active_conditions.add("low_or_medium_specificity")
                if repeated_pattern:
                    active_conditions.add("repeated_pattern")

                if conditions.intersection(active_conditions):
                    if patched_level == "home":
                        patched_level = "routine_doctor"

        urgent_cfg = cfg.get("urgent_threshold", {}) or {}
        if urgent_cfg:
            if urgent_cfg.get("increase_urgent_bias_for"):
                # this branch is just reserved for future stricter signal routing
                pass

        emergency_cfg = cfg.get("emergency_threshold", {}) or {}
        if emergency_cfg:
            # reserved for future force_emergency integration
            pass

        return patched_level

    # ============================================================
    # PIPELINE HELPERS
    # ============================================================

    def build_active_context_flags(
        self,
        *,
        zone: str,
        ranked_causes: list[str],
    ) -> list[str]:
        flags: list[str] = []

        if zone == "upper_gi_zone":
            flags.append("есть явные GI-признаки")
        if zone == "bowel_zone":
            flags.append("есть bowel symptoms")
        if zone == "right_upper_abdominal_zone":
            flags.append("есть RUQ symptoms")

        if "reflux_pattern" in ranked_causes:
            flags.append("есть clear reflux")
        if "biliary_pattern" in ranked_causes:
            flags.append("есть clear biliary")
        if any(c in ranked_causes for c in ["dairy_lactose_pattern", "fodmap_fermentation_pattern", "ibs_pattern_if_recurrent"]):
            flags.append("есть clear bowel pattern")
        if any(c in ranked_causes for c in ["sugar_glucose_pattern"]):
            flags.append("есть glucose clues")

        return flags

    def apply_full_runtime_patch(
        self,
        *,
        normalized_text: str,
        trigger_groups: list[str],
        zone_scores: dict[str, int],
        cause_scores: dict[str, int],
        matched_red_flags: list[str],
        recurrent: bool,
        care_level: str,
        confidence_level: str,
        repeated_pattern: bool,
        zone: str,
        ranked_causes: list[str],
    ) -> dict[str, Any]:
        patched_zone_scores = self.apply_zone_weight_boosts(
            zone_scores=zone_scores,
            normalized_text=normalized_text,
            trigger_groups=trigger_groups,
        )

        patched_cause_scores = self.apply_cause_score_boosts(
            cause_scores=cause_scores,
            normalized_text=normalized_text,
            recurrent=recurrent,
        )

        active_context_flags = self.build_active_context_flags(
            zone=zone,
            ranked_causes=ranked_causes,
        )

        patched_cause_scores = self.apply_cause_score_reductions(
            cause_scores=patched_cause_scores,
            active_context_flags=active_context_flags,
        )

        softened_urgent = self.should_soften_urgent_route(
            matched_red_flags=matched_red_flags,
        )

        patched_care_level = self.apply_care_level_changes(
            care_level=care_level,
            recurrent=recurrent,
            confidence_level=confidence_level,
            repeated_pattern=repeated_pattern,
        )

        return {
            "zone_scores": patched_zone_scores,
            "cause_scores": patched_cause_scores,
            "soften_urgent_route": softened_urgent,
            "care_level": patched_care_level,
            "active_context_flags": active_context_flags,
        }


def print_runtime_patch_result(result: dict[str, Any]) -> None:
    print("\n================ RUNTIME PATCH RESULT ================")
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    from app.services.food_consultation_engine import FoodConsultationEngine
    from app.services.food_failure_analyzer import FoodFailureAnalyzer
    from app.services.food_patch_applier import FoodPatchApplier
    from app.services.food_patch_generator import FoodPatchGenerator
    from app.services.food_regression_scoreboard import FoodRegressionScoreboard
    from app.services.food_tuning_advisor import FoodTuningAdvisor

    engine = FoodConsultationEngine()

    scoreboard_result = FoodRegressionScoreboard(engine).run()
    analysis = FoodFailureAnalyzer().analyze(scoreboard_result)
    advice = FoodTuningAdvisor().advise(analysis)
    patch_result = FoodPatchGenerator().generate(advice)
    apply_result = FoodPatchApplier().apply(base_config={}, patch_result=patch_result)

    runtime = FoodRuntimePatchIntegration(apply_result.patched_config)

    demo = runtime.apply_full_runtime_patch(
        normalized_text="после жирного тянет справа под ребром и горечь во рту",
        trigger_groups=["fatty_fried"],
        zone_scores={
            "right_upper_abdominal_zone": 8,
            "upper_gi_zone": 7,
            "bowel_zone": 0,
            "systemic_zone": 1,
        },
        cause_scores={
            "biliary_pattern": 12,
            "fatty_food_overload": 11,
            "functional_dyspepsia": 7,
            "postprandial_vascular_pattern": 6,
        },
        matched_red_flags=[],
        recurrent=True,
        care_level="home",
        confidence_level="medium",
        repeated_pattern=True,
        zone="right_upper_abdominal_zone",
        ranked_causes=["biliary_pattern", "fatty_food_overload", "functional_dyspepsia"],
    )

    print_runtime_patch_result(demo)
