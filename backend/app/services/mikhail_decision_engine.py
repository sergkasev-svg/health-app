"""
Decision engine («мозг Михаила»): управляет порядком ответа:
симптомы/анализы → уточнение → гипотезы → триаж → ответ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.knowledge.filters.diagnosis_filter import is_relevant_diagnosis


# --- Red flags (явные признаки срочной помощи) ---
RED_FLAGS = [
    "боль в груди",
    "одышка в покое",
    "потеря сознания",
    "обморок",
    "кровь в рвоте",
    "чёрный стул",
    "черный стул",
    "кровь в стуле",
    "перекос лица",
    "слабость в руке",
    "слабость в ноге",
    "судороги",
    "очень сильная боль в животе",
    "сильная боль в животе",
    "сатурация низкая",
    "температура с выраженным ухудшением",
    "выраженное ухудшение состояния",
]

EMERGENCY_FINAL_MESSAGE = (
    "Есть признаки, при которых нужна срочная медицинская помощь. "
    "Не откладывайте обращение. Срочно звоните 103/112 или обратитесь за неотложной помощью."
)

EMERGENCY_ADVICE = [
    "Вызовите скорую (103 или 112).",
    "Не оставайтесь одни до приезда помощи.",
    "Если прописаны лекарства (например, нитроглицерин) — примите по инструкции.",
]


@dataclass
class DecisionInput:
    user_text: str = ""
    symptoms: List[str] = field(default_factory=list)
    lab_rows: List[Dict[str, Any]] = field(default_factory=list)
    structured_lab_report: Optional[Dict[str, Any]] = None
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    user_profile: Dict[str, Any] = field(default_factory=dict)
    red_flags: List[str] = field(default_factory=list)
    uploaded_files: List[Dict[str, Any]] = field(default_factory=list)
    conversation_context: Optional[Dict[str, Any]] = None


@dataclass
class DecisionOutput:
    state: str = "needs_more_data"
    urgency: str = "low"
    questions: List[str] = field(default_factory=list)
    likely_hypotheses: List[str] = field(default_factory=list)
    recommended_labs: List[str] = field(default_factory=list)
    self_care: List[str] = field(default_factory=list)
    doctor_advice: List[str] = field(default_factory=list)
    emergency_advice: List[str] = field(default_factory=list)
    final_user_message: str = ""
    debug: Dict[str, Any] = field(default_factory=dict)


def has_minimum_clinical_data(input_data: DecisionInput) -> bool:
    """Минимально достаточные данные: 2+ симптома, или структурированные анализы, или 1 симптом + лаб. паттерн."""
    symptoms = [s for s in (input_data.symptoms or []) if str(s).strip()]
    lab_report = input_data.structured_lab_report or {}
    lab_blocks = (lab_report.get("blocks") or []) if isinstance(lab_report, dict) else []
    has_structured_labs = bool(lab_blocks and len(lab_blocks) > 0)
    user_text_ok = len((input_data.user_text or "").strip()) >= 10
    # 2+ осмысленных симптома (или один длинный текст с описанием)
    symptom_count = len(symptoms) if symptoms else (1 if user_text_ok else 0)
    if symptom_count >= 2:
        return True
    if has_structured_labs:
        return True
    if symptom_count >= 1 and (input_data.lab_rows or lab_blocks):
        return True
    return False


def should_request_labs(input_data: DecisionInput) -> Tuple[bool, List[str]]:
    """
    Нужны ли анализы. Возвращает (need_labs, list of lab names).
    Не более 5 анализов, только по делу.
    """
    labs: List[str] = []
    has_labs = bool(input_data.lab_rows or (input_data.structured_lab_report or {}).get("blocks"))
    hypotheses = input_data.hypotheses or []
    symptoms_text = " ".join(str(x).lower() for x in (input_data.symptoms or [])) + " " + (input_data.user_text or "").lower()
    report = input_data.structured_lab_report or {}
    topics = (report.get("hidden_debug") or report.get("debug") or {}).get("topics") or []
    supports = (report.get("hidden_debug") or report.get("debug") or {}).get("supports") or []

    if has_labs and topics:
        # Уже есть анализы и паттерн — доп. анализы по паттерну
        if "iron_deficiency" in topics or "anemia_pattern" in topics:
            labs = ["Ферритин", "Сывороточное железо", "ОЖСС или трансферрин"]
        elif "thyroid_hypo" in topics or "thyroid_hyper" in topics:
            labs = ["TSH", "Свободный T4", "Анти-ТПО по назначению врача"]
        elif "infection_pattern" in topics or "inflammation_pattern" in topics:
            labs = ["СРБ", "ОАК"]
        if labs:
            return (True, labs[:5])

    if not has_labs and (hypotheses or "слабость" in symptoms_text or "утомляемость" in symptoms_text or "головокружение" in symptoms_text):
        # Жалобы есть, гипотезы слабые, лабораторий нет
        if any(h.get("name", "").lower().find("желез") >= 0 or h.get("name", "").lower().find("анемия") >= 0 for h in hypotheses):
            return (True, ["Ферритин", "Сывороточное железо", "ОЖСС или трансферрин"][:5])
        if any(h.get("name", "").lower().find("щитовид") >= 0 or h.get("name", "").lower().find("гипотиреоз") >= 0 for h in hypotheses):
            return (True, ["TSH", "Свободный T4", "Анти-ТПО по назначению врача"][:5])
        if "слабость" in symptoms_text or "утомляемость" in symptoms_text:
            return (True, ["ОАК (гемоглобин, эритроциты, MCH)", "Ферритин при подозрении на дефицит железа"][:5])
        if "жажда" in symptoms_text or "сахар" in symptoms_text or "вес" in symptoms_text:
            return (True, ["Глюкоза крови", "HbA1c по назначению врача"][:5])
        if "температура" in symptoms_text or "воспаление" in symptoms_text:
            return (True, ["СРБ", "ОАК", "Общий анализ мочи при симптомах ИМП"][:5])

    return (False, [])


def select_probable_hypotheses(input_data: DecisionInput) -> List[Dict[str, Any]]:
    """
    Отобрать до 3 гипотез, пропустить через diagnosis_filter.
    Пользователю показывать максимум 2. Формулировки: «возможная причина», «может соответствовать».
    """
    raw = list(input_data.hypotheses or [])
    symptoms = list(input_data.symptoms or [])
    context = {"symptoms": symptoms}
    filtered: List[Dict[str, Any]] = []
    for h in raw:
        name = h.get("name") or h.get("title") or ""
        prob = float(h.get("probability") or h.get("score") or 0.5)
        if is_relevant_diagnosis(name, prob, context):
            filtered.append(h)
    filtered = filtered[:3]
    # Для отображения — не более 2
    return filtered


def decide_care_path(
    input_data: DecisionInput,
    probable_hypotheses: List[Dict[str, Any]],
    lab_report: Optional[Dict[str, Any]],
) -> str:
    """
    self_care / doctor_soon по правилам.
    """
    if input_data.red_flags:
        return "emergency"
    report = lab_report or input_data.structured_lab_report or {}
    severity = (report.get("severity") or "normal").lower()
    topics = (report.get("hidden_debug") or report.get("debug") or {}).get("topics") or []
    if severity == "urgent":
        return "emergency"
    if "thyroid_hypo" in topics or "thyroid_hyper" in topics:
        return "doctor_soon"
    if "iron_deficiency" in topics or "anemia_pattern" in topics:
        return "doctor_soon"
    if "infection_pattern" in topics:
        return "doctor_soon"
    if "possible_allergy" in topics and not any(x in topics for x in ("iron_deficiency", "infection_pattern")):
        return "self_care"
    if severity == "mild" and not topics and not probable_hypotheses:
        return "self_care"
    if probable_hypotheses or topics:
        return "doctor_soon"
    return "self_care"


def build_final_user_message(decision_output: DecisionOutput) -> str:
    """
    Собрать финальное сообщение пользователю: коротко, без повторов, до 900–1200 символов.
    """
    state = decision_output.state or "needs_more_data"
    if state == "emergency":
        parts = [EMERGENCY_FINAL_MESSAGE]
        if decision_output.emergency_advice:
            parts.append("")
            for a in decision_output.emergency_advice[:3]:
                parts.append(f"• {a}")
        return "\n".join(parts).strip()

    parts: List[str] = []
    if decision_output.final_user_message and state in ("request_labs", "needs_more_data"):
        return decision_output.final_user_message.strip()[:1200]

    # Обычный ответ: структура по блокам
    if decision_output.likely_hypotheses:
        parts.append("Коротко")
        for h in decision_output.likely_hypotheses[:2]:
            parts.append(f"• {h}")
        parts.append("")
    if decision_output.questions:
        parts.append("Что стоит уточнить")
        for q in decision_output.questions[:3]:
            parts.append(f"• {q}")
        parts.append("")
    if decision_output.recommended_labs:
        parts.append("Что можно сдать")
        for lab in decision_output.recommended_labs[:5]:
            parts.append(f"• {lab}")
        parts.append("")
    if decision_output.self_care:
        parts.append("Что можно сделать сейчас")
        for s in decision_output.self_care[:3]:
            parts.append(f"• {s}")
        parts.append("")
    if decision_output.doctor_advice:
        parts.append("Когда к врачу")
        for d in decision_output.doctor_advice[:3]:
            parts.append(f"• {d}")
        parts.append("")
    parts.append("Когда срочно к врачу")
    parts.append("• Сильная боль в груди, одышка в покое, потеря сознания, кровь в стуле/рвоте, перекос лица, слабость в руке/ноге — звоните 103/112.")
    text = "\n".join(parts).strip()
    return text[:1200] if len(text) > 1200 else text


class MikhailDecisionEngine:
    """Движок принятия решений: порядок emergency → данные → анализы → гипотезы → ответ."""

    def evaluate(self, input_data: DecisionInput) -> DecisionOutput:
        debug: Dict[str, Any] = {}
        # STEP A. Emergency
        red_flags = list(input_data.red_flags or []) or self._detect_red_flags(input_data)
        if red_flags:
            return self._make_emergency_output(red_flags, debug)

        # STEP B. Достаточность данных
        if not self._has_minimum_clinical_data(input_data):
            questions = self._build_questions(input_data, max_n=3)
            return DecisionOutput(
                state="needs_more_data",
                urgency="low",
                questions=questions[:3],
                likely_hypotheses=[],
                recommended_labs=[],
                self_care=[],
                doctor_advice=[],
                emergency_advice=[],
                final_user_message=self._message_needs_more_data(questions[:3]),
                debug=debug,
            )

        # STEP C. Нужны ли анализы
        need_labs, recommended_labs = self._should_request_labs(input_data)
        if need_labs and not (input_data.lab_rows or (input_data.structured_lab_report or {}).get("blocks")):
            return DecisionOutput(
                state="request_labs",
                urgency="low",
                questions=self._build_questions(input_data, max_n=2)[:2],
                likely_hypotheses=[],
                recommended_labs=recommended_labs[:5],
                self_care=[],
                doctor_advice=["Покажите результаты анализов врачу для интерпретации."],
                emergency_advice=[],
                final_user_message=self._message_request_labs(recommended_labs[:5]),
                debug=debug,
            )

        # STEP D. Гипотезы
        probable = self._select_probable_hypotheses(input_data)
        likely_str = []
        for h in probable[:2]:
            name = (h.get("name") or h.get("title") or "").strip()
            if name:
                likely_str.append(f"Возможная причина: {name}.")
        if not likely_str and input_data.structured_lab_report:
            topics = (input_data.structured_lab_report.get("hidden_debug") or {}).get("topics") or []
            if "iron_deficiency" in topics or "anemia_pattern" in topics:
                likely_str.append("По анализу возможен дефицит железа. Нужна консультация врача.")
            if "thyroid_hypo" in topics:
                likely_str.append("По анализу возможен гипотиреоз. Нужна консультация врача и контроль свободного T4.")
            if "thyroid_hyper" in topics:
                likely_str.append("По анализу возможна гиперфункция щитовидной железы. Нужна консультация врача.")
            if "possible_allergy" in topics:
                likely_str.append("Небольшое повышение эозинофилов может быть связано с аллергией. Уточните с врачом.")

        # STEP E. Care path и ответ
        care_path = self._decide_care_path(input_data, probable, input_data.structured_lab_report)
        if care_path == "emergency":
            return self._make_emergency_output(self._detect_red_flags(input_data), debug)

        state = "probable_diagnosis" if likely_str else "self_care"
        if care_path == "doctor_soon":
            state = "doctor_soon"
        self_care = self._build_self_care(input_data, probable, care_path)
        doctor_advice = self._build_doctor_advice(input_data, care_path)

        out = DecisionOutput(
            state=state,
            urgency="high" if care_path == "doctor_soon" else "low",
            questions=[],
            likely_hypotheses=likely_str[:2],
            recommended_labs=recommended_labs[:5] if need_labs else [],
            self_care=self_care[:3],
            doctor_advice=doctor_advice[:3],
            emergency_advice=[],
            final_user_message="",
            debug=debug,
        )
        out.final_user_message = build_final_user_message(out)
        return out

    def _detect_red_flags(self, input_data: DecisionInput) -> List[str]:
        text = ((input_data.user_text or "") + " " + " ".join(input_data.symptoms or [])).lower()
        found = [f for f in RED_FLAGS if f.lower() in text]
        return list(dict.fromkeys(found))

    def _make_emergency_output(self, red_flags: List[str], debug: Dict[str, Any]) -> DecisionOutput:
        return DecisionOutput(
            state="emergency",
            urgency="high",
            questions=[],
            likely_hypotheses=[],
            recommended_labs=[],
            self_care=[],
            doctor_advice=[],
            emergency_advice=EMERGENCY_ADVICE[:3],
            final_user_message=EMERGENCY_FINAL_MESSAGE,
            debug={**debug, "red_flags": red_flags},
        )

    def _has_minimum_clinical_data(self, input_data: DecisionInput) -> bool:
        return has_minimum_clinical_data(input_data)

    def _should_request_labs(self, input_data: DecisionInput) -> Tuple[bool, List[str]]:
        return should_request_labs(input_data)

    def _select_probable_hypotheses(self, input_data: DecisionInput) -> List[Dict[str, Any]]:
        return select_probable_hypotheses(input_data)

    def _decide_care_path(
        self,
        input_data: DecisionInput,
        probable_hypotheses: List[Dict[str, Any]],
        lab_report: Optional[Dict[str, Any]],
    ) -> str:
        return decide_care_path(input_data, probable_hypotheses, lab_report)

    def _build_questions(self, input_data: DecisionInput, max_n: int = 3) -> List[str]:
        questions = []
        report = input_data.structured_lab_report or {}
        topics = (report.get("hidden_debug") or report.get("debug") or {}).get("topics") or []
        if "iron_deficiency" in topics or "anemia_pattern" in topics:
            questions.extend(["Есть ли слабость или быстрая утомляемость?", "Бывает ли головокружение или одышка при нагрузке?"])
        if "possible_allergy" in topics:
            questions.append("Есть ли аллергия, зуд, сыпь, насморк или контакт с аллергенами?")
        if "thyroid_hypo" in topics:
            questions.append("Есть ли усталость, зябкость, сухость кожи, набор веса?")
        if "thyroid_hyper" in topics:
            questions.append("Есть ли сердцебиение, потливость, снижение веса, нервозность?")
        if not questions:
            questions = ["Как давно беспокоят симптомы?", "Что уже пробовали? Есть ли хронические болезни или приём лекарств?"]
        return list(dict.fromkeys(questions))[:max_n]

    def _message_needs_more_data(self, questions: List[str]) -> str:
        if not questions:
            return "Чтобы дать полезный ответ, опишите, пожалуйста, симптомы подробнее: как давно, что беспокоит, что уже пробовали."
        return "Чтобы ответить точнее, уточните:\n• " + "\n• ".join(questions[:3])

    def _message_request_labs(self, labs: List[str]) -> str:
        return "Для уточнения картины желательно сдать анализы:\n• " + "\n• ".join(labs[:5]) + "\n\nПокажите результаты врачу."

    def _build_self_care(
        self,
        input_data: DecisionInput,
        probable_hypotheses: List[Dict[str, Any]],
        care_path: str,
    ) -> List[str]:
        if care_path != "self_care":
            return []
        report = input_data.structured_lab_report or {}
        topics = (report.get("hidden_debug") or report.get("debug") or {}).get("topics") or []
        out = []
        if "iron_deficiency" in topics or "anemia_pattern" in topics:
            out.extend(["Добавить в питание продукты с железом: мясо, печень, бобовые, гречка.", "Не запивать еду чаем или кофе."])
        if "possible_allergy" in topics:
            out.append("Вспомнить, не было ли новых продуктов, лекарств или контакта с аллергенами.")
        if not out:
            out = ["Соблюдайте режим сна и питья.", "При сохранении симптомов обратитесь к врачу."]
        return out[:3]

    def _build_doctor_advice(self, input_data: DecisionInput, care_path: str) -> List[str]:
        if care_path == "self_care":
            return []
        return ["Рекомендуется очная консультация врача с результатами анализов и описанием симптомов."]
