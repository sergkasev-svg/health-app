from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ============================================================
# OPTIONAL IMPORTS FROM YOUR FOOD STACK
# ============================================================

try:
    from app.services.food_consultation_engine import (
        FoodConsultationEngine,
        FoodRoutingContext,
        TriggerMemoryState,
    )
except Exception:
    try:
        from food_consultation_engine import (  # type: ignore
            FoodConsultationEngine,
            FoodRoutingContext,
            TriggerMemoryState,
        )
    except Exception as exc:  # pragma: no cover
        FoodConsultationEngine = None  # type: ignore
        FoodRoutingContext = None  # type: ignore
        TriggerMemoryState = None  # type: ignore
        _FOOD_IMPORT_ERROR = exc
    else:
        _FOOD_IMPORT_ERROR = None
else:
    _FOOD_IMPORT_ERROR = None


# ============================================================
# USER-FACING / ORCHESTRATOR DATA CONTRACTS
# ============================================================


@dataclass
class FoodBranchInput:
    user_text: str
    user_id: str | None = None
    recurrent: bool = False
    debug: bool = False
    ask_followups: bool = True
    doctor_safe: bool = True
    memory_state: Any | None = None
    food_journal_entries: list[dict[str, Any]] = field(default_factory=list)
    extra_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class FoodBranchOutput:
    matched: bool
    relevance_score: float
    branch_name: str
    patient_safe_text: str
    doctor_safe_json: dict[str, Any]
    care_level: str
    followup_questions: list[str]
    machine_payload: dict[str, Any]
    memory_state: Any | None = None
    errors: list[str] = field(default_factory=list)


# ============================================================
# SIMPLE FOOD-BRANCH RELEVANCE FILTER
# ============================================================


class FoodBranchRelevanceFilter:
    """
    Lightweight detector:
    decides whether complaint is likely food/post-meal related.

    Goal:
    - high recall for obvious food cases
    - avoid stealing clearly non-food complaints
    """

    FOOD_TRIGGER_WORDS = [
        "после еды",
        "после приема пищи",
        "после приема пищи",
        "после приема еды",
        "через час после еды",
        "через полчаса после еды",
        "после ужина",
        "после обеда",
        "после завтрака",
        "после перекуса",
        "после жирного",
        "после жирной еды",
        "после жареного",
        "после жареной еды",
        "после молока",
        "после творога",
        "после сыра",
        "после вина",
        "после сладкого",
        "после десерта",
        "после мороженого",
        "после шашлыка",
        "после бобовых",
        "после лука",
        "после чеснока",
        "съел",
        "съела",
        "поел",
        "поела",
        "объелся",
        "объелась",
        "переел",
        "переела",
        "после картошки",
        "после еды мутит",
    ]

    FOOD_OBJECT_WORDS = [
        "еда",
        "прием пищи",
        "прием еды",
        "жирное",
        "жирная еда",
        "жареное",
        "жареная еда",
        "молоко",
        "молочное",
        "творог",
        "сыр",
        "вино",
        "копчености",
        "копчености",
        "сладкое",
        "торт",
        "десерт",
        "мороженое",
        "семечки",
        "орехи",
        "шашлык",
        "бургер",
        "пицца",
        "лук",
        "чеснок",
        "бобовые",
        "фасоль",
        "сок",
        "мед",
        "мед",
        "алкоголь",
    ]

    POSTMEAL_SYMPTOMS = [
        "тошнит",
        "подташнивает",
        "мутит",
        "тяжесть",
        "отрыжка",
        "изжога",
        "жжение",
        "горечь во рту",
        "вздутие",
        "урчание",
        "газы",
        "понос",
        "диарея",
        "жидкий стул",
        "слабость",
        "сонливость",
        "головная боль",
        "головокружение",
        "болит справа под ребром",
        "тянет справа под ребром",
        "тянет справа",
        "справа под ребром",
        "правое подреберье",
    ]

    NON_FOOD_BLOCKERS = [
        "кашель",
        "насморк",
        "боль в горле",
        "сыпь без связи с едой",
        "травма",
        "ушиб",
        "порез",
        "ожог",
        "болит зуб",
        "плохо вижу",
        "болит ухо",
    ]

    def score(self, text: str) -> float:
        normalized = self._normalize(text)

        if not normalized:
            return 0.0

        blocker_hits = sum(1 for x in self.NON_FOOD_BLOCKERS if x in normalized)
        trigger_hits = sum(1 for x in self.FOOD_TRIGGER_WORDS if x in normalized)
        object_hits = sum(1 for x in self.FOOD_OBJECT_WORDS if x in normalized)
        symptom_hits = sum(1 for x in self.POSTMEAL_SYMPTOMS if x in normalized)
        has_after_marker = any(x in normalized for x in ["после еды", "после", "через час", "через полчаса"])
        has_ruq_marker = any(x in normalized for x in ["справа под ребром", "тянет справа", "правое подреберье", "горечь во рту"])
        has_fatty_marker = any(x in normalized for x in ["жирн", "жарен"])

        score = 0.0
        score += trigger_hits * 0.28
        score += object_hits * 0.10
        score += symptom_hits * 0.08
        score -= blocker_hits * 0.25
        # Synergy bonuses for typical post-meal narratives.
        if trigger_hits > 0 and symptom_hits > 0:
            score += 0.18
        if has_after_marker and object_hits > 0 and symptom_hits > 0:
            score += 0.20
        if has_ruq_marker and has_fatty_marker:
            score += 0.18

        score = max(0.0, min(score, 1.0))
        return round(score, 3)

    def matches(self, text: str, threshold: float = 0.33) -> tuple[bool, float]:
        score = self.score(text)
        return score >= threshold, score

    @staticmethod
    def _normalize(text: str) -> str:
        text = (text or "").lower().strip().replace("ё", "е")
        for ch in [",", ".", "!", "?", ":", ";", "(", ")", "[", "]", "{", "}", "\"", "'"]:
            text = text.replace(ch, " ")
        while "  " in text:
            text = text.replace("  ", " ")
        return text.strip()


# ============================================================
# MAIN BRANCH INTEGRATION
# ============================================================


class ZaZFoodBranchIntegration:
    """
    Final integration layer for ZaZdorovie orchestrator.

    Usage pattern:
        branch = ZaZFoodBranchIntegration()
        result = branch.handle(FoodBranchInput(...))

    Result is stable, orchestrator-friendly, and split into:
        - patient_safe_text
        - doctor_safe_json
        - machine_payload
    """

    BRANCH_NAME = "food_postmeal_branch"

    def __init__(
        self,
        *,
        food_engine: Any | None = None,
        relevance_filter: FoodBranchRelevanceFilter | None = None,
        relevance_threshold: float = 0.33,
    ) -> None:
        self.relevance_filter = relevance_filter or FoodBranchRelevanceFilter()
        self.relevance_threshold = relevance_threshold

        if food_engine is not None:
            self.food_engine = food_engine
        else:
            if FoodConsultationEngine is None:
                self.food_engine = None
            else:
                self.food_engine = FoodConsultationEngine()

    def handle(self, payload: FoodBranchInput) -> FoodBranchOutput:
        matched, relevance_score = self.relevance_filter.matches(
            payload.user_text,
            threshold=self.relevance_threshold,
        )

        if not matched:
            return FoodBranchOutput(
                matched=False,
                relevance_score=relevance_score,
                branch_name=self.BRANCH_NAME,
                patient_safe_text="",
                doctor_safe_json={},
                care_level="",
                followup_questions=[],
                machine_payload={
                    "branch": self.BRANCH_NAME,
                    "matched": False,
                    "relevance_score": relevance_score,
                    "reason": "food relevance below threshold",
                },
                memory_state=payload.memory_state,
                errors=[],
            )

        if self.food_engine is None:
            return FoodBranchOutput(
                matched=True,
                relevance_score=relevance_score,
                branch_name=self.BRANCH_NAME,
                patient_safe_text="",
                doctor_safe_json={},
                care_level="",
                followup_questions=[],
                machine_payload={
                    "branch": self.BRANCH_NAME,
                    "matched": True,
                    "relevance_score": relevance_score,
                },
                memory_state=payload.memory_state,
                errors=[f"Food engine unavailable: {_FOOD_IMPORT_ERROR}"],
            )

        try:
            routing_context = self._build_food_context(payload)
            result = self.food_engine.consult(
                payload.user_text,
                context=routing_context,
                memory_state=payload.memory_state or self._make_memory_state(),
                food_journal_entries=payload.food_journal_entries,
            )

            patient_view = result.get("patient_view", {}) or {}
            doctor_view = result.get("doctor_view", {}) or {}
            machine_view = result.get("machine_view", {}) or {}
            memory_state = result.get("memory_state")

            patient_safe_text = str(patient_view.get("text", "")).strip()
            care_level = str(patient_view.get("care_level", "")).strip()
            followup_questions = list(doctor_view.get("followup_questions", []) or [])

            machine_payload = {
                "branch": self.BRANCH_NAME,
                "matched": True,
                "relevance_score": relevance_score,
                "zone": doctor_view.get("zone"),
                "cluster": doctor_view.get("cluster"),
                "ranked_causes": doctor_view.get("ranked_causes", []),
                "confidence": doctor_view.get("confidence", {}),
                "care_level": doctor_view.get("care_level", {}),
                "severity": doctor_view.get("severity", {}),
                "timeline": doctor_view.get("timeline", {}),
                "lab_bridge": doctor_view.get("lab_bridge", {}),
                "memory_summary": doctor_view.get("memory_summary", {}),
                "machine_view": machine_view,
            }

            return FoodBranchOutput(
                matched=True,
                relevance_score=relevance_score,
                branch_name=self.BRANCH_NAME,
                patient_safe_text=patient_safe_text,
                doctor_safe_json=doctor_view,
                care_level=care_level,
                followup_questions=followup_questions[:3],
                machine_payload=machine_payload,
                memory_state=memory_state,
                errors=[],
            )

        except Exception as exc:
            return FoodBranchOutput(
                matched=True,
                relevance_score=relevance_score,
                branch_name=self.BRANCH_NAME,
                patient_safe_text="",
                doctor_safe_json={},
                care_level="",
                followup_questions=[],
                machine_payload={
                    "branch": self.BRANCH_NAME,
                    "matched": True,
                    "relevance_score": relevance_score,
                    "error": repr(exc),
                },
                memory_state=payload.memory_state,
                errors=[repr(exc)],
            )

    def _build_food_context(self, payload: FoodBranchInput) -> Any:
        if FoodRoutingContext is None:
            return None

        return FoodRoutingContext(
            recurrent=payload.recurrent,
            debug=payload.debug,
            ask_followups=payload.ask_followups,
            doctor_safe=payload.doctor_safe,
        )

    def _make_memory_state(self) -> Any | None:
        if TriggerMemoryState is None:
            return None
        return TriggerMemoryState()


# ============================================================
# OPTIONAL ORCHESTRATOR ADAPTER
# ============================================================


class ZaZFoodOrchestratorAdapter:
    """
    Thin adapter so this branch can be called from a generic orchestrator.

    Expected generic input:
    {
        "text": "...",
        "user_id": "...",
        "recurrent": bool,
        "debug": bool,
        "food_journal_entries": [...],
        "branch_memory": ...
    }

    Returns:
    {
        "matched": bool,
        "branch": "food_postmeal_branch",
        "patient_safe_text": "...",
        "doctor_safe_json": {...},
        "care_level": "...",
        "followup_questions": [...],
        "branch_memory": ...,
        "machine_payload": {...},
        "errors": [...]
    }
    """

    def __init__(self, branch: ZaZFoodBranchIntegration | None = None) -> None:
        self.branch = branch or ZaZFoodBranchIntegration()

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        branch_input = FoodBranchInput(
            user_text=str(request.get("text", "")),
            user_id=request.get("user_id"),
            recurrent=bool(request.get("recurrent", False)),
            debug=bool(request.get("debug", False)),
            ask_followups=bool(request.get("ask_followups", True)),
            doctor_safe=bool(request.get("doctor_safe", True)),
            memory_state=request.get("branch_memory"),
            food_journal_entries=list(request.get("food_journal_entries", []) or []),
            extra_context=dict(request.get("extra_context", {}) or {}),
        )

        out = self.branch.handle(branch_input)

        return {
            "matched": out.matched,
            "branch": out.branch_name,
            "relevance_score": out.relevance_score,
            "patient_safe_text": out.patient_safe_text,
            "doctor_safe_json": out.doctor_safe_json,
            "care_level": out.care_level,
            "followup_questions": out.followup_questions,
            "branch_memory": out.memory_state,
            "machine_payload": out.machine_payload,
            "errors": out.errors,
        }


# ============================================================
# EXAMPLE: DIRECT USAGE
# ============================================================


def example_direct_usage() -> None:
    branch = ZaZFoodBranchIntegration()

    result = branch.handle(
        FoodBranchInput(
            user_text="После жирной еды через час мутит, тянет справа под ребром и горечь во рту. Такое уже повторялось.",
            recurrent=True,
            debug=True,
            ask_followups=True,
            doctor_safe=True,
            food_journal_entries=[
                {"food_items": ["жирная еда"], "symptoms": ["тошнота", "горечь"]},
                {"food_items": ["жареное"], "symptoms": ["тошнота", "тяжесть справа"]},
                {"food_items": ["жирная еда"], "symptoms": ["тошнота", "горечь"]},
            ],
        )
    )

    print("MATCHED:", result.matched)
    print("RELEVANCE:", result.relevance_score)
    print("CARE:", result.care_level)
    print("PATIENT TEXT:")
    print(result.patient_safe_text)
    print("FOLLOWUPS:", result.followup_questions)
    print("DOCTOR JSON:", result.doctor_safe_json)
    print("MACHINE:", result.machine_payload)
    print("ERRORS:", result.errors)


# ============================================================
# EXAMPLE: ORCHESTRATOR USAGE
# ============================================================


def example_orchestrator_usage() -> None:
    adapter = ZaZFoodOrchestratorAdapter()

    request = {
        "text": "После молока и мороженого раздуло живот, урчит и жидкий стул. Такое уже бывало.",
        "user_id": "user_123",
        "recurrent": True,
        "debug": True,
        "doctor_safe": True,
        "ask_followups": True,
        "food_journal_entries": [
            {"food_items": ["молоко"], "symptoms": ["вздутие", "понос"]},
            {"food_items": ["мороженое"], "symptoms": ["урчание", "жидкий стул"]},
        ],
        "branch_memory": None,
    }

    response = adapter.run(request)
    print(response)


if __name__ == "__main__":
    example_direct_usage()
