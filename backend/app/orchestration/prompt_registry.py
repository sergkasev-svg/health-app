from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PromptRegistry:
    project_root: Path

    @classmethod
    def from_default_paths(cls) -> "PromptRegistry":
        backend_dir = Path(__file__).resolve().parents[2]
        return cls(project_root=backend_dir.parent)

    @property
    def _templates_dir(self) -> Path:
        return self.project_root / "medical_knowledge" / "labs" / "templates"

    @property
    def _rules_dir(self) -> Path:
        return self.project_root / "medical_knowledge" / "labs" / "rules"

    def _read_text(self, path: Path) -> str:
        try:
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
        return ""

    def _read_json_text(self, path: Path) -> str:
        # Keep raw JSON text for prompt injection.
        return self._read_text(path)

    def get_intake_normalizer_prompt(self) -> str:
        return (
            "Ты Intake Normalizer. Нормализуй вход в структуру: chief_complaint/history/uploaded_files. "
            "Не диагностируй, не ставь гипотезы, только извлекай факты."
        )

    def get_adaptive_question_prompt(self) -> str:
        return self._read_text(self._templates_dir / "adaptive_medical_question_engine_prompt.txt")

    def get_lab_parser_prompt(self) -> str:
        return self._read_text(self._templates_dir / "lab_result_parser_prompt.txt")

    def get_retrieval_ranking_prompt(self) -> str:
        return self._read_text(self._templates_dir / "medical_retrieval_ranking_prompt.txt")

    def get_reasoning_prompt(self) -> str:
        return self._read_text(self._templates_dir / "diagnostic_reasoning_engine_prompt.txt")

    def get_evidence_weighting_prompt(self) -> str:
        return self._read_text(self._templates_dir / "clinical_evidence_weighting_prompt.txt")

    def get_safety_prompt(self) -> str:
        return self._read_text(self._templates_dir / "clinical_safety_guardrail_prompt.txt")

    def get_answer_generator_prompt(self) -> str:
        return self._read_text(self._templates_dir / "system_prompt_medical.txt")

    def get_output_template_json(self) -> str:
        return self._read_json_text(self._rules_dir / "medical_output_template.json")

    def get_medical_core_json(self) -> str:
        return self._read_json_text(self._rules_dir / "medical_core_v1.json")
