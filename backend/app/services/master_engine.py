"""Master Engine: гипотезы → план → ответ + upsell."""
from typing import Any, Dict, List

from .hypothesis_engine import build_hypotheses
from .plan_engine import build_plan
from .sales_engine import maybe_upsell


def run_master_engine(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload:
    {
      "lab_markers": {...},
      "symptoms": [...],
      "profile": {...}
    }
    """
    hypotheses = build_hypotheses(payload)
    plan = build_plan(payload, hypotheses)

    base_text = _render_response(hypotheses, plan)
    upsell_text = maybe_upsell(payload, hypotheses)

    return {
        "text": base_text + ("\n\n" + upsell_text if upsell_text else ""),
        "hypotheses": hypotheses,
        "plan": plan
    }


def _render_response(hypotheses: List[dict], plan: dict) -> str:
    lines = []

    lines.append("🧠 Что происходит")
    for h in hypotheses[:3]:
        lines.append(f"- {h['label']}")

    lines.append("\n⚡ Что это значит")
    for h in hypotheses[:3]:
        lines.append(f"- {h['meaning']}")

    lines.append("\n🚀 Что делать")
    for step in plan["priority_1"]:
        lines.append(f"- {step}")

    lines.append("\n🧪 Что проверить")
    for t in plan["tests"]:
        lines.append(f"- {t}")

    lines.append("\n⚠️ Важно")
    lines.append("Это не диагноз. Нужна очная оценка врача.")

    return "\n".join(lines)
