from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.services.food_self_tuning_pipeline import FoodSelfTuningPipeline


class FoodTrainingConsole:
    """
    One-command training / evaluation console for the food module.

    Features:
      - runs full self-tuning pipeline
      - prints before/after metrics
      - prints top failures
      - prints top tuning suggestions
      - prints patch summary
      - optionally saves artifacts to disk
    """

    def __init__(self, output_dir: str | Path = "./food_training_artifacts") -> None:
        self.output_dir = Path(output_dir)

    def run(
        self,
        *,
        save_artifacts: bool = True,
        print_top_failed_cases: int = 20,
        print_top_suggestions: int = 15,
        quiet: bool = False,
    ) -> dict[str, Any]:
        pipeline = FoodSelfTuningPipeline()
        result = pipeline.run()

        base_scoreboard_dict = self._obj_to_dict(result.base_scoreboard)
        patched_scoreboard_dict = self._obj_to_dict(result.patched_scoreboard)
        failure_analysis_dict = self._obj_to_dict(result.failure_analysis)
        tuning_advice_dict = self._obj_to_dict(result.tuning_advice)
        patch_apply_dict = self._obj_to_dict(result.patch_apply_result)

        if quiet:
            self._print_header("OVERALL")
            print("baseline:", base_scoreboard_dict.get("overall", {}))
            print("patched:", patched_scoreboard_dict.get("overall", {}))
            self._print_header("DELTA")
            self._print_dict(result.comparison.get("overall", {}))
            self._print_header("PATCH SUMMARY")
            self._print_dict(patch_apply_dict.get("summary", {}))
            if save_artifacts:
                self._save_artifacts(
                    result=result,
                    base_scoreboard_dict=base_scoreboard_dict,
                    patched_scoreboard_dict=patched_scoreboard_dict,
                    failure_analysis_dict=failure_analysis_dict,
                    tuning_advice_dict=tuning_advice_dict,
                    patch_apply_dict=patch_apply_dict,
                )
            return {
                "base_scoreboard": base_scoreboard_dict,
                "patched_scoreboard": patched_scoreboard_dict,
                "comparison": result.comparison,
                "failure_analysis": failure_analysis_dict,
                "tuning_advice": tuning_advice_dict,
                "patch_apply_result": patch_apply_dict,
            }

        self._print_header("BASELINE OVERALL")
        self._print_dict(base_scoreboard_dict.get("overall", {}))

        self._print_header("PATCHED OVERALL")
        self._print_dict(patched_scoreboard_dict.get("overall", {}))

        self._print_header("BEFORE / AFTER DELTA")
        self._print_dict(result.comparison.get("overall", {}))

        self._print_header("TIERS DELTA")
        for tier_name, tier_payload in result.comparison.get("tiers", {}).items():
            print(f"\n--- {tier_name.upper()} ---")
            self._print_dict(tier_payload)

        self._print_header("COMMON FAILURES BEFORE PATCH")
        common_failures_before = base_scoreboard_dict.get("common_failures", [])
        self._print_list_of_dicts(common_failures_before[:10])

        self._print_header("COMMON FAILURES AFTER PATCH")
        common_failures_after = patched_scoreboard_dict.get("common_failures", [])
        self._print_list_of_dicts(common_failures_after[:10])

        self._print_header("TOP FAILED CASES BEFORE PATCH")
        failed_cases_before = base_scoreboard_dict.get("failed_cases", [])
        self._print_failed_cases(failed_cases_before[:print_top_failed_cases])

        self._print_header("TOP FAILED CASES AFTER PATCH")
        failed_cases_after = patched_scoreboard_dict.get("failed_cases", [])
        self._print_failed_cases(failed_cases_after[:print_top_failed_cases])

        self._print_header("FAILURE ANALYSIS")
        self._print_dict(failure_analysis_dict.get("summary", {}))

        print("\nZone confusions:")
        self._print_list_of_dicts(failure_analysis_dict.get("zone_confusions", [])[:10])

        print("\nUnderestimated causes:")
        self._print_list_of_dicts(failure_analysis_dict.get("underestimated_causes", [])[:10])

        print("\nOverestimated causes:")
        self._print_list_of_dicts(failure_analysis_dict.get("overestimated_causes", [])[:10])

        print("\nCare level issues:")
        self._print_list_of_dicts(failure_analysis_dict.get("care_level_issues", [])[:10])

        print("\nHypotheses:")
        for item in failure_analysis_dict.get("hypotheses", []):
            print("-", item)

        self._print_header("TOP TUNING SUGGESTIONS")
        suggestions = tuning_advice_dict.get("suggestions", [])
        for idx, suggestion in enumerate(suggestions[:print_top_suggestions], start=1):
            print(f"\n--- Suggestion #{idx} ---")
            self._print_dict(suggestion)

        self._print_header("PATCH SUMMARY")
        self._print_dict(patch_apply_dict.get("summary", {}))

        print("\nApplied patch deltas:")
        self._print_list_of_dicts(patch_apply_dict.get("applied", [])[:20])

        if save_artifacts:
            self._save_artifacts(
                result=result,
                base_scoreboard_dict=base_scoreboard_dict,
                patched_scoreboard_dict=patched_scoreboard_dict,
                failure_analysis_dict=failure_analysis_dict,
                tuning_advice_dict=tuning_advice_dict,
                patch_apply_dict=patch_apply_dict,
            )

        return {
            "base_scoreboard": base_scoreboard_dict,
            "patched_scoreboard": patched_scoreboard_dict,
            "comparison": result.comparison,
            "failure_analysis": failure_analysis_dict,
            "tuning_advice": tuning_advice_dict,
            "patch_apply_result": patch_apply_dict,
        }

    def _save_artifacts(
        self,
        *,
        result: Any,
        base_scoreboard_dict: dict[str, Any],
        patched_scoreboard_dict: dict[str, Any],
        failure_analysis_dict: dict[str, Any],
        tuning_advice_dict: dict[str, Any],
        patch_apply_dict: dict[str, Any],
    ) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._write_json(self.output_dir / "scoreboard_before.json", base_scoreboard_dict)
        self._write_json(self.output_dir / "scoreboard_after.json", patched_scoreboard_dict)
        self._write_json(self.output_dir / "comparison.json", result.comparison)
        self._write_json(self.output_dir / "failure_analysis.json", failure_analysis_dict)
        self._write_json(self.output_dir / "tuning_advice.json", tuning_advice_dict)
        self._write_json(self.output_dir / "patch_apply_result.json", patch_apply_dict)
        self._write_json(
            self.output_dir / "patched_config.json",
            patch_apply_dict.get("patched_config", {}),
        )

        print(f"\nArtifacts saved to: {self.output_dir.resolve()}")

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _obj_to_dict(self, obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if is_dataclass(obj):
            return asdict(obj)
        result: dict[str, Any] = {}
        for attr in [
            "overall",
            "tiers",
            "common_failures",
            "failed_cases",
            "summary",
            "zone_confusions",
            "underestimated_causes",
            "overestimated_causes",
            "care_level_issues",
            "hypotheses",
            "suggestions",
            "patch_deltas",
            "grouped_patch",
            "original_config",
            "patched_config",
            "applied",
            "skipped",
            "comparison",
        ]:
            if hasattr(obj, attr):
                result[attr] = self._convert(getattr(obj, attr))
        return result

    def _convert(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, list):
            return [self._convert(x) for x in value]
        if isinstance(value, dict):
            return {k: self._convert(v) for k, v in value.items()}
        return value

    def _print_header(self, title: str) -> None:
        print(f"\n{'=' * 18} {title} {'=' * 18}")

    def _print_dict(self, payload: dict[str, Any]) -> None:
        if not payload:
            print("empty")
            return
        for k, v in payload.items():
            print(f"{k}: {v}")

    def _print_list_of_dicts(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            print("empty")
            return
        for row in rows:
            print(row)

    def _print_failed_cases(self, failed_cases: list[dict[str, Any]]) -> None:
        if not failed_cases:
            print("No failed cases")
            return

        for row in failed_cases:
            print("\n---")
            print("id:", row.get("id"))
            print("tier:", row.get("tier"))
            print("text:", row.get("text"))
            print("zone_ok:", row.get("zone_ok"))
            print("cause_ok:", row.get("cause_ok"))
            print("care_ok:", row.get("care_ok"))
            print("expected_zone:", row.get("expected_zone"))
            print("actual_zone:", row.get("actual_zone"))
            print("expected_causes_any:", row.get("expected_causes_any"))
            print("actual_ranked_causes:", row.get("actual_ranked_causes"))
            print("expected_care_any:", row.get("expected_care_any"))
            print("actual_care:", row.get("actual_care"))


if __name__ == "__main__":
    console = FoodTrainingConsole(output_dir="./food_training_artifacts")
    console.run(
        save_artifacts=True,
        print_top_failed_cases=20,
        print_top_suggestions=15,
    )
