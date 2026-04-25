"""
ResponseFormatter: consistent structure for concierge responses.
"""
from typing import Any

DEFAULT_DISCLAIMER = "Информация носит ознакомительный характер и не заменяет консультацию врача."


def format_concierge_response(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ensures required response sections and disclaimer.
    Optional: insights (list), strength_metabolism_block (str), axis (str).
    """
    p = dict(payload or {})
    p.setdefault("description", "")
    p.setdefault("hypotheses", [])
    p.setdefault("exam_recommendations", [])
    p.setdefault("nutrition_advice", [])
    p.setdefault("activity_advice", [])
    p.setdefault("red_flags", [])
    p.setdefault("insights", [])
    p.setdefault("strength_metabolism_block", None)
    p.setdefault("axis", None)
    p["disclaimer"] = p.get("disclaimer") or DEFAULT_DISCLAIMER
    return p

