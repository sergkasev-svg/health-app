from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from app.services.food_failure_analyzer import FoodFailureAnalyzer
from app.services.food_patch_generator import FoodPatchGenerator
from app.services.food_regression_scoreboard import FoodRegressionScoreboard
from app.services.food_tuning_advisor import FoodTuningAdvisor


class FoodPatchExporter:
    """Exports patch payloads to JSON files."""

    def __init__(self, output_dir: str | Path = "./food_training_artifacts") -> None:
        self.output_dir = Path(output_dir)

    def export(
        self,
        *,
        patch_result: Any,
        patch_filename: str = "patch.json",
        high_priority_filename: str = "high_priority_patch.json",
    ) -> dict[str, Path]:
        payload = self._to_patch_payload(patch_result)
        deltas = list(payload.get("patch_deltas", []))
        high_deltas = [d for d in deltas if str(d.get("priority", "")).lower() == "high"]

        grouped_high = self._group_deltas(high_deltas)
        high_payload = {
            "summary": {
                "patch_deltas_out": len(high_deltas),
                "zone_weight_boosts": len(grouped_high.get("zone_weight_boosts", [])),
                "cause_score_boosts": len(grouped_high.get("cause_score_boosts", [])),
                "cause_score_reductions": len(grouped_high.get("cause_score_reductions", [])),
                "urgent_threshold_changes": len(grouped_high.get("urgent_threshold_changes", [])),
                "care_level_changes": len(grouped_high.get("care_level_changes", [])),
                "recurrent_logic_changes": len(grouped_high.get("recurrent_logic_changes", [])),
            },
            "patch_deltas": high_deltas,
            "grouped_patch": grouped_high,
        }

        self.output_dir.mkdir(parents=True, exist_ok=True)
        patch_path = self.output_dir / patch_filename
        high_path = self.output_dir / high_priority_filename
        self._write_json(patch_path, payload)
        self._write_json(high_path, high_payload)
        return {"patch_path": patch_path, "high_priority_patch_path": high_path}

    def _to_patch_payload(self, patch_result: Any) -> dict[str, Any]:
        if isinstance(patch_result, dict):
            return patch_result
        if hasattr(patch_result, "summary") and hasattr(patch_result, "patch_deltas"):
            grouped = getattr(patch_result, "grouped_patch", None)
            payload = {
                "summary": self._convert(getattr(patch_result, "summary", {})),
                "patch_deltas": self._convert(getattr(patch_result, "patch_deltas", [])),
                "grouped_patch": self._convert(grouped) if grouped is not None else {},
            }
            if not payload["grouped_patch"]:
                payload["grouped_patch"] = self._group_deltas(payload["patch_deltas"])
            return payload
        return {"summary": {}, "patch_deltas": [], "grouped_patch": {}}

    def _group_deltas(self, patch_deltas: list[dict[str, Any]]) -> dict[str, Any]:
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
            path = str(delta.get("path", ""))
            root = path.split(".", 1)[0] if path else "unclassified"
            payload = {
                "path": path,
                "op": delta.get("op"),
                "value": delta.get("value"),
                "rationale": delta.get("rationale"),
                "priority": delta.get("priority"),
            }
            grouped.setdefault(root, [])
            grouped[root].append(payload)
        return grouped

    def _convert(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, list):
            return [self._convert(v) for v in value]
        if isinstance(value, dict):
            return {k: self._convert(v) for k, v in value.items()}
        return value

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_patch_export(output_dir: str | Path = "./food_training_artifacts") -> dict[str, Path]:
    from app.services.food_consultation_engine import FoodConsultationEngine

    engine = FoodConsultationEngine()
    scoreboard = FoodRegressionScoreboard(engine).run()
    analysis = FoodFailureAnalyzer().analyze(scoreboard)
    advice = FoodTuningAdvisor().advise(analysis)
    patch_result = FoodPatchGenerator().generate(advice)

    exporter = FoodPatchExporter(output_dir=output_dir)
    return exporter.export(patch_result=patch_result)


if __name__ == "__main__":
    out = run_patch_export()
    print("patch_path:", out["patch_path"])
    print("high_priority_patch_path:", out["high_priority_patch_path"])
