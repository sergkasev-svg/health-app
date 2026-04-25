from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FoodRulesLoader:
    """
    Loads JSON configs for food symptom routing.
    Expected files:
      - food_symptom_super_master.json
      - patient_safe_templates.json
      - routing_rules.json
    """

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)

    def _load_json(self, filename: str) -> dict[str, Any]:
        path = self.base_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    def load_all(self) -> dict[str, Any]:
        return {
            "super_master": self._load_json("food_symptom_super_master.json"),
            "templates": self._load_json("patient_safe_templates.json"),
            "routing": self._load_json("routing_rules.json"),
        }

