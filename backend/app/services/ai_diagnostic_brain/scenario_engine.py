from __future__ import annotations

from typing import Any, Dict, List

from app.services.ai_diagnostic_brain.clinical_scenarios import SCENARIOS


def match_scenarios(lab_flags: List[str]) -> List[Dict[str, Any]]:
    flags = set([str(x).strip() for x in (lab_flags or []) if str(x).strip()])
    matched: List[Dict[str, Any]] = []
    for key, scenario in SCENARIOS.items():
        conditions = [str(x).strip() for x in (scenario.get("conditions") or []) if str(x).strip()]
        if not conditions:
            continue
        # Для сложных паттернов достаточно пересечения условий с фактами (мягкий матчинг).
        if any(c in flags for c in conditions):
            out = dict(scenario)
            out["scenario_id"] = key
            matched.append(out)
    return matched
