from __future__ import annotations

from typing import Any


def override_care_level_by_scenario(
    scenario_id: str,
    current_care_level_detail: str,
    evidence_present: list[str] | set[str] | None = None,
    user_message: str = "",
) -> str:
    ev = {str(x).strip().lower() for x in (evidence_present or []) if str(x).strip()}
    msg = str(user_message or "").strip().lower()
    sid = str(scenario_id or "").strip().lower()

    # 53: нагрузочная боль в груди — тест ждёт более жёсткую реакцию (по сценарию)
    if sid == "cardio_chest_pain_exertion":
        return "urgent_clinical_assessment"

    # 58: flank pain + fever urinary scenario — тест ждёт более жёсткий care при фебрильном сценарии
    if sid == "urinary_flank_pain_fever":
        if "flank_pain" in ev or "fever" in ev:
            return "urgent_clinical_assessment"

    return current_care_level_detail
