from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass
class PatchApplyResult:
    original_config: dict[str, Any]
    patched_config: dict[str, Any]
    applied: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    summary: dict[str, Any]


class FoodPatchApplier:
    """
    Applies patch packages from FoodPatchGenerator to a runtime config dict.

    Expected config structure (flexible, missing branches are auto-created):
    {
        "zone_weight_boosts": {},
        "cause_score_boosts": {},
        "cause_score_reductions": {},
        "urgent_threshold_changes": {},
        "care_level_changes": {},
        "recurrent_logic_changes": {},
    }
    """

    DEFAULT_CONFIG = {
        "zone_weight_boosts": {},
        "cause_score_boosts": {},
        "cause_score_reductions": {},
        "urgent_threshold_changes": {},
        "care_level_changes": {},
        "recurrent_logic_changes": {},
    }

    def apply(
        self,
        base_config: dict[str, Any] | None,
        patch_result: Any,
    ) -> PatchApplyResult:
        original_config = deepcopy(base_config or {})
        patched_config = self._normalize_base_config(base_config or {})
        deltas = self._extract_patch_deltas(patch_result)

        applied: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for delta in deltas:
            ok, reason = self._apply_delta(patched_config, delta)
            record = {
                "path": delta.get("path"),
                "op": delta.get("op"),
                "value": delta.get("value"),
                "priority": delta.get("priority"),
                "reason": reason,
            }
            if ok:
                applied.append(record)
            else:
                skipped.append(record)

        summary = {
            "patch_deltas_in": len(deltas),
            "applied_count": len(applied),
            "skipped_count": len(skipped),
        }

        return PatchApplyResult(
            original_config=original_config,
            patched_config=patched_config,
            applied=applied,
            skipped=skipped,
            summary=summary,
        )

    def _normalize_base_config(self, base_config: dict[str, Any]) -> dict[str, Any]:
        cfg = deepcopy(self.DEFAULT_CONFIG)
        for key, value in (base_config or {}).items():
            cfg[key] = deepcopy(value)
        return cfg

    def _extract_patch_deltas(self, patch_result: Any) -> list[dict[str, Any]]:
        if hasattr(patch_result, "patch_deltas"):
            raw = getattr(patch_result, "patch_deltas", [])
            return [self._to_dict(x) for x in raw]

        if isinstance(patch_result, dict):
            if "patch_deltas" in patch_result:
                return [self._to_dict(x) for x in patch_result.get("patch_deltas", [])]

        return []

    def _to_dict(self, obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        return {
            "path": getattr(obj, "path", None),
            "op": getattr(obj, "op", None),
            "value": getattr(obj, "value", None),
            "rationale": getattr(obj, "rationale", None),
            "priority": getattr(obj, "priority", None),
        }

    def _apply_delta(self, config: dict[str, Any], delta: dict[str, Any]) -> tuple[bool, str]:
        path = delta.get("path")
        op = delta.get("op")
        value = delta.get("value")

        if not path or not op:
            return False, "missing path or op"

        parts = str(path).split(".")
        if not parts:
            return False, "invalid path"

        root = parts[0]
        if root not in config:
            config[root] = {}

        try:
            if op == "upsert":
                self._upsert_path(config, parts, value)
                return True, "upsert applied"

            if op == "merge":
                self._merge_path(config, parts, value)
                return True, "merge applied"

            if op == "append":
                self._append_path(config, parts, value)
                return True, "append applied"

            return False, f"unsupported op: {op}"
        except Exception as exc:
            return False, f"apply error: {exc}"

    def _upsert_path(self, config: dict[str, Any], parts: list[str], value: Any) -> None:
        target = config
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]

        leaf = parts[-1]

        if isinstance(value, dict) and isinstance(target.get(leaf), dict):
            target[leaf] = self._deep_merge_dicts(target[leaf], value)
        else:
            target[leaf] = deepcopy(value)

    def _merge_path(self, config: dict[str, Any], parts: list[str], value: Any) -> None:
        target = config
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]

        leaf = parts[-1]
        current = target.get(leaf, {})

        if not isinstance(current, dict):
            current = {}

        if not isinstance(value, dict):
            raise ValueError("merge op requires dict value")

        target[leaf] = self._deep_merge_dicts(current, value)

    def _append_path(self, config: dict[str, Any], parts: list[str], value: Any) -> None:
        target = config
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]

        leaf = parts[-1]
        current = target.get(leaf)

        if current is None:
            target[leaf] = [deepcopy(value)]
            return

        if not isinstance(current, list):
            target[leaf] = [current, deepcopy(value)]
            return

        current.append(deepcopy(value))

    def _deep_merge_dicts(self, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(a)
        for key, value in b.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge_dicts(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result


def print_patch_apply_result(result: PatchApplyResult) -> None:
    print("\n================ APPLY SUMMARY ================")
    for k, v in result.summary.items():
        print(f"{k}: {v}")

    print("\n=================== APPLIED ===================")
    if not result.applied:
        print("No applied deltas")
    else:
        for item in result.applied:
            print(item)

    print("\n=================== SKIPPED ===================")
    if not result.skipped:
        print("No skipped deltas")
    else:
        for item in result.skipped:
            print(item)

    print("\n=============== PATCHED CONFIG ================")
    print(result.patched_config)


if __name__ == "__main__":
    from app.services.food_consultation_engine import FoodConsultationEngine
    from app.services.food_failure_analyzer import FoodFailureAnalyzer
    from app.services.food_patch_generator import FoodPatchGenerator
    from app.services.food_regression_scoreboard import FoodRegressionScoreboard
    from app.services.food_tuning_advisor import FoodTuningAdvisor

    engine = FoodConsultationEngine()

    scoreboard_result = FoodRegressionScoreboard(engine).run()
    analysis = FoodFailureAnalyzer().analyze(scoreboard_result)
    advice = FoodTuningAdvisor().advise(analysis)
    patch_result = FoodPatchGenerator().generate(advice)

    applier = FoodPatchApplier()
    apply_result = applier.apply(base_config={}, patch_result=patch_result)

    print_patch_apply_result(apply_result)
