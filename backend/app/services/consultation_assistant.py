"""
Консультационный ассистент: уточняющие вопросы, запрос анализов, рекомендации.
Поиск в офлайн- и онлайн-справочниках; при отсутствии сети — только офлайн.
Кэш ответов для релевантности и быстрой реакции на похожие вопросы.
Без искусственной задержки: ответ сразу по готовности (целевая пауза не более 2 сек).
"""
import asyncio
import json
import logging
import re
import time
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

from app.config import get_settings
from app.services.offline_search import search_offline, search_offline_with_formats
from app.services.knowledge_base import search_scenario_context
from app.services.clinical_profiles import format_profiles_for_prompt, search_clinical_profiles
from app.services.complaint_reference import complaint_meta as build_complaint_meta
from app.services.complaint_reference import get_prioritized_complaints
from app.services.complaint_reference import search_complaint_reference
from app.services.clinical_intent_semantics import format_intent_hint_for_prompt
from app.services.top_complaints_20 import match_top20, format_top20_for_prompt
from app.services.consultation_contracts import (
    CONSULTATION_JSON_SCHEMA,
    ConsultationStructuredOutput,
)
from app.services.consultation_orchestrator import (
    MAX_CLARIFICATION_ROUNDS,
    build_consultation_state,
    count_assistant_clarification_rounds,
    run_stateful_triage,
)
from app.services.medical_question_engine import suggest_clarifying_questions
from app.services.medical_relevance_filter import filter_response_by_relevance
from app.services.quality_autolearn import detect_topics, get_conflicting_topics, topic_keywords
from app.services.report import build_consultation_final_report, DISCLAIMER_TEXT
from app.services.routing_control import get_routing_control_config
from app.services.specialty_detection import detect_specialty
from app.services.strict_topic_protocol import search_strict_topic_protocol
from app.services.learned_responses import get_learned_responses, save_learned_response
from app.services.offtopic_humor import would_ask_clarifying_instead_of_joke
from app.services.symptom_parser import parse_symptoms
from app.services.nutrition_engine import analyze_nutrition
from app.services.diagnostic_ranking_engine import build_diagnostic_assessment
from app.services.mikhail_decision_engine import (
    DecisionInput,
    DecisionOutput,
    MikhailDecisionEngine,
)
from app.services.clinical_orchestrator import (
    ClinicalOrchestrator,
    OrchestratorInput,
    OrchestratorOutput,
)
from app.services.lab_interpreter import analyze_labs
from app.services.labs_layer_lookup import build_labs_layer_context
from app.services.food_triggers_lookup import build_food_trigger_context
from app.services.multidisciplinary_prompt_lookup import build_multidisciplinary_context
from app.services.symptom_cause_lookup import build_symptom_cause_context
from app.services.symptom_severity_lookup import build_symptom_severity_context
from app.services.reasoning_graph_lookup import build_reasoning_graph_context
from app.services.relevance_funnel import apply_relevance_funnel, scrub_text_with_funnel
from app.services.master_knowledge_loader import get_master_knowledge_for_prompt
from app.services.red_flag_screening import (
    ambulance_offer_flow_payload,
    is_emergency_call_intent,
    screen_user_input,
    wrap_immediate_emergency_message,
)
from app.services.medication_lookup import route_medication_lookup
from app.services.mikhail_warm_dialog_retriever import (
    format_warm_dialog_examples_block,
    medication_handbook_policy_snippet,
)
from app.services.scenario_pack_loader import load_all_scenario_packs
from app.services.user_store import (
    get_or_create_named_lab_case,
    get_mikhail_conversation_prefs,
    get_response_cache,
    save_mikhail_conversation_prefs,
    save_consultation_state,
    save_to_response_cache,
)
from app.services.voice_medical_input import extract_symptoms_nutrition_activity_intent
from app.services.medical_core_guidance import apply_medical_core_guidance
from app.services.medical_core_selector import MedicalCoreSelector, SelectorResult
from app.services.medical_core_case_memory import (
    attach_selector_state,
    read_selector_state,
    selector_followup_question,
)
from app.services.medical_core_followup_state import (
    FollowupState,
    attach_followup_state,
    prime_followup_state,
)
from app.services.medical_core_followup_gate import decide_followup_turn
from app.services.medical_core_followup_gate_v2 import evaluate_followup_turn
from app.services.medical_core_confidence_gate import run_confidence_gate
from app.services.medical_core_safe_summary_renderer import render_safe_summary_bundle
from app.services.integration_bridge import build_bridge_complaint_protocol
from app.reasoning.medical_reasoning_engine import (
    build_medical_reasoning_output,
    render_short_answer_from_reasoning,
)
try:
    from app.medical_core.compat import suggest_medical_core_entries
except Exception:  # optional add-only overlay
    suggest_medical_core_entries = None

try:
    from app.medical_core.engine import MedicalCoreEngine
except Exception:  # optional add-only overlay
    MedicalCoreEngine = None

MIN_RESPONSE_DELAY_SEC = 0.0  # Базовый fallback; целевая медицинская пауза задаётся _resolve_min_delay_sec.
CONFIDENCE_SLOT_QUESTION = {
    "duration": "Как давно это началось: часы, дни или недели?",
    "location": "Где именно сейчас основной дискомфорт?",
    "character": "Какая по характеру боль/симптом: давит, колет, жжет, пульсирует?",
    "severity": "Оцените выраженность по шкале от 1 до 10.",
    "temperature": "Есть температура сейчас? Если есть, укажите значение.",
    "trigger": "С чем вы связываете начало: нагрузка, еда, стресс, жара, травма?",
    "breath": "Есть одышка или ощущение нехватки воздуха?",
    "bleeding": "Есть кровотечение сейчас, и продолжается ли оно?",
    "stool": "Есть изменения стула: диарея, запор, кровь, черный стул?",
    "urination": "Есть боль, жжение или учащение при мочеиспускании?",
    "vomiting": "Есть тошнота или рвота сейчас?",
    "pregnancy": "Есть вероятность беременности или задержка цикла?",
    "neuro": "Есть онемение, слабость, перекос лица или трудности с речью?",
}


@lru_cache(maxsize=1)
def _get_scenario_coverage_snapshot() -> dict[str, Any]:
    packs = load_all_scenario_packs()
    by_category: dict[str, int] = {}
    for pack in packs:
        key = str(getattr(pack, "category", "") or "").strip() or "unknown"
        by_category[key] = int(by_category.get(key, 0)) + 1
    category_counts = dict(sorted(by_category.items(), key=lambda kv: kv[0]))
    category_names = list(category_counts.keys())
    focus_categories = [x for x in ("women_health", "pediatric", "ent") if x in category_counts]
    ranking_calibration: dict[str, Any] = {}
    try:
        from app.services.scenario_router import get_scenario_ranking_calibration

        cfg = get_scenario_ranking_calibration() or {}
        if isinstance(cfg, dict):
            ranking_calibration = {
                "branch_bonus": dict(cfg.get("branch_bonus") or {}),
                "context_weights": dict(cfg.get("context_weights") or {}),
            }
    except Exception:
        ranking_calibration = {}
    return {
        "scenario_count": len(packs),
        "category_counts": category_counts,
        "categories": category_names,
        "phase2_focus_categories_present": focus_categories,
        "ranking_calibration": ranking_calibration,
    }


async def _ensure_min_delay(start_time: float, min_sec: float = MIN_RESPONSE_DELAY_SEC) -> None:
    """При min_sec > 0 гарантирует паузу не менее min_sec с момента start_time перед ответом."""
    if min_sec <= 0:
        return
    elapsed = time.monotonic() - start_time
    if elapsed < min_sec:
        await asyncio.sleep(min_sec - elapsed)


def _resolve_min_delay_sec(user_message: str, response_text: str = "") -> float:
    text = f"{user_message or ''} {response_text or ''}".lower()
    urgent_markers = (
        "боль в груди",
        "не хватает воздуха",
        "задыха",
        "кров",
        "потеря сознания",
        "онем",
        "перекос",
        "судорог",
        "сильная боль",
        "высокая температура",
        "срочно",
        "103",
        "112",
    )
    if any(m in text for m in urgent_markers):
        return 0.55
    if len((response_text or "").strip()) > 700:
        return 1.75
    return 1.35


def _protocol_from_medical_core_entry(entry: dict[str, Any]) -> dict[str, Any]:
    follow_up = entry.get("follow_up") or {}
    triage = entry.get("triage") or {}
    care = entry.get("care") or {}
    return {
        "id": str(entry.get("entry_id") or "").strip() or "medical_core_overlay",
        "complaint": str(entry.get("name") or "").strip(),
        "name": str(entry.get("name") or "").strip(),
        "category": str(entry.get("category") or "Общая медицина").strip(),
        "description": str(entry.get("description") or "").strip(),
        "anamnesis_questions": [str(x).strip() for x in (follow_up.get("must_ask") or []) if str(x).strip()],
        "red_flags": [str(x).strip() for x in (triage.get("red_flags") or []) if str(x).strip()],
        "suggested_labs": [str(x).strip() for x in (care.get("tests") or []) if str(x).strip()],
        "nutrition_recommendations": [str(x).strip() for x in (care.get("nutrition") or []) if str(x).strip()],
        "physical_exercise_prevention_rehabilitation": [
            str(x).strip() for x in (care.get("activity") or []) if str(x).strip()
        ],
        "likely_causes": [str(x).strip() for x in (entry.get("symptoms") or []) if str(x).strip()],
        "source": "medical_core_overlay",
        "urgency_level": str(triage.get("recommended_care_level") or "").strip(),
    }


def _build_medical_core_enrichment(user_message: str, limit: int = 3) -> dict[str, Any]:
    if not suggest_medical_core_entries:
        return {}
    try:
        state = SimpleNamespace(chief_complaint=user_message or "", history=SimpleNamespace(symptoms=[], location=""))
        entries = suggest_medical_core_entries(state, limit=limit) or []
        entries = [x for x in entries if isinstance(x, dict)]
    except Exception:
        return {}

    if not entries:
        return {}

    primary = next((x for x in entries if str(x.get("type") or "") == "complaint"), entries[0])
    follow_up = primary.get("follow_up") or {}
    triage = primary.get("triage") or {}
    must_ask = [str(x).strip() for x in (follow_up.get("must_ask") or []) if str(x).strip()]
    red_flag_questions = [str(x).strip() for x in (follow_up.get("red_flag_questions") or []) if str(x).strip()]
    red_flags = [str(x).strip() for x in (triage.get("red_flags") or []) if str(x).strip()]
    care_level = str(triage.get("recommended_care_level") or "").strip()

    candidate_diseases: list[str] = []
    if MedicalCoreEngine is not None and str(primary.get("type") or "") == "complaint":
        try:
            engine = MedicalCoreEngine()
            plan = engine.complaint_plan(str(primary.get("entry_id") or ""))
            for d in (plan.get("candidate_diseases") or [])[:5]:
                if isinstance(d, dict):
                    label = str(d.get("name") or d.get("label") or d.get("entry_id") or "").strip()
                else:
                    label = str(d or "").strip()
                if label:
                    candidate_diseases.append(label)
        except Exception:
            pass

    return {
        "entries": entries[:limit],
        "primary": primary,
        "must_ask": must_ask,
        "red_flag_questions": red_flag_questions,
        "red_flags": red_flags,
        "care_level": care_level,
        "candidate_diseases": candidate_diseases,
        "source": "medical_core_overlay",
    }


CONCLUSION_MARKER = "[CONCLUSION]"
MAX_QUESTIONS_PER_TURN = 1
# Синхрон с consultation_orchestrator.MAX_CLARIFICATION_ROUNDS — не более стольких «раундов» с вопросами подряд.
MAX_FOLLOWUP_ROUNDS = MAX_CLARIFICATION_ROUNDS
logger = logging.getLogger(__name__)

# Встроенный промпт (fallback, если файл не найден)
_SYSTEM_PROMPT_FALLBACK = """Ты — врач в приложении «За Здоровье». Цель: собрать анамнез, поставить рабочую гипотезу и дать рекомендации.

Стиль: лаконичный, профессиональный, по-медицински сдержанный. Не повторяй вопрос пользователя (ни на первом, ни на последующих ответах) — сразу к ответу. Формат ответа — обязательно нумерованный список: «По симптомам могу сделать следующий вывод:» 1. Вывод. 2. Вывод. 3. Гипотеза. 4. Доп. вопрос и анализы (если нужно). 5. Лечение сразу. 6. Лечение аккуратно (если нужны доп. данные). 7. Профилактика. В конце — дисклеймер. При любой жалобе давать конкретные рекомендации (что делать), в т.ч. при жалобах на еду/питание (семечки, переедание) — покой желудку, ограничить жирное, питьё. Не подставлять чужой сценарий.

Вопросы — только необходимые и достаточные. Опирайся на контекст справочников.

Порядок: 1) КРАСНЫЕ ФЛАГИ; 2) Severity GREEN/YELLOW/RED; 3) при недостатке данных — 1–3 уточняющих вопроса; 4) при достаточных данных — вывод и рекомендации.

Правила: отвечай по делу, на русском. В конце дисклеймер: """ + DISCLAIMER_TEXT + """."""

_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "consultation_system.txt"
_METABOLIC_ADDON_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "metabolic_add_on.txt"
_CLINICAL_CORE_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "clinical_core_prompt.txt"
_ULTRA_SHORT_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "mikhail_ultra_short_system_prompt.txt"
_ULTRA_SHORT_PROMPT_FILE_FALLBACK = Path(__file__).resolve().parents[3] / "prompts" / "mikhail_ultra_short_system_prompt.txt"
_REASONING_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "medical_reasoning_engine.txt"
_FINAL_SHORT_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "final_answer_short_mode.txt"
_MEDICATION_SEARCH_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "medication_search_engine_prompt.txt"
_CONCIERGE_MEDICATION_PATCH_FILE = Path(__file__).resolve().parent.parent / "prompts" / "concierge_medication_system_patch.txt"
_DIALOGUE_STYLE_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "mikhail_dialogue_style.txt"
_CHARACTER_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "mikhail_character_prompt.txt"
_ORCHESTRATOR_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "mikhail_conversational_orchestrator.txt"
_COMBINED_MIKHAIL_PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "mikhail_combined_system_prompt.txt"
_SHARED_RULES_FILE = Path(__file__).resolve().parents[3] / "medical_knowledge" / "shared" / "shared_rules.json"
_METABOLIC_ADDON_FALLBACK = """
[METABOLIC ADD-ON MODE]
Use this mode only when request context is related to organic acids, amino acids, fatty acids,
mitochondrial function, vitamin-dependent cofactors, dysbiosis markers, or mass-spectrometry lab panels.

Language rule:
- Всегда отвечай только на русском языке.

Operate as a metabolic interpretation extension to the existing protocol:
1) Summary of findings
2) Pathway interpretation
3) Cofactor assessment
4) Differential metabolic hypotheses
5) Nutritional support considerations
6) Further diagnostic recommendations
7) Medical disclaimer

Safety:
- Never provide definitive diagnosis.
- Never prescribe medication.
- Avoid unrelated diseases.
- If data is insufficient, explicitly ask for additional metabolic data.
- Always include: "This is metabolic interpretation and does not replace physician diagnosis."
""".strip()

_METABOLIC_KEYS = (
    "органическ",
    "аминокис",
    "жирн",
    "метабол",
    "митохонд",
    "цикл кребс",
    "трикарбон",
    "ацидеми",
    "ацидур",
    "масс-спектр",
    "масс спектр",
    "гх-мс",
    "gc-ms",
    "лактат",
    "пируват",
    "сукцинат",
    "фумарат",
    "малат",
    "цитрат",
    "метилмалон",
    "оксалат",
    "кофактор",
    "витамин b2",
    "витамин b3",
    "витамин b6",
    "витамин b12",
    "селени",
    "цинк",
    "креатинин",
    "ммоль/моль",
)
RED_FLAG_KEYWORDS = [
    "боль в груди",
    "давит в груди",
    "не хватает воздуха",
    "трудно дышать",
    "потерял сознание",
    "обморок",
    "кровь в рвоте",
    "черный стул",
    "судороги",
]

def _get_system_prompt() -> str:
    """Загружает системный промпт из файла или возвращает встроенный."""
    try:
        if _PROMPT_FILE.exists():
            text = _PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return _SYSTEM_PROMPT_FALLBACK


def _get_ultra_short_prompt_layer() -> str:
    try:
        if _ULTRA_SHORT_PROMPT_FILE.exists():
            text = _ULTRA_SHORT_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        if _ULTRA_SHORT_PROMPT_FILE_FALLBACK.exists():
            text = _ULTRA_SHORT_PROMPT_FILE_FALLBACK.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_shared_rules_layer() -> str:
    try:
        if _SHARED_RULES_FILE.exists():
            payload = json.loads(_SHARED_RULES_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return json.dumps(payload, ensure_ascii=False)
    except Exception:
        pass
    return ""


def _get_reasoning_prompt_layer() -> str:
    try:
        if _REASONING_PROMPT_FILE.exists():
            text = _REASONING_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_final_short_prompt_layer() -> str:
    try:
        if _FINAL_SHORT_PROMPT_FILE.exists():
            text = _FINAL_SHORT_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_medication_search_prompt_layer() -> str:
    try:
        if _MEDICATION_SEARCH_PROMPT_FILE.exists():
            text = _MEDICATION_SEARCH_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_concierge_medication_patch_layer() -> str:
    try:
        if _CONCIERGE_MEDICATION_PATCH_FILE.exists():
            text = _CONCIERGE_MEDICATION_PATCH_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_dialogue_style_layer() -> str:
    """Режим человеческого диалога: взаимные вопросы, длинный разговор, опора на справочники и learned."""
    try:
        if _DIALOGUE_STYLE_PROMPT_FILE.exists():
            text = _DIALOGUE_STYLE_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_mikhail_combined_prompt_layer() -> str:
    """Финальный объединённый character + orchestrator (приоритет над раздельными файлами)."""
    try:
        if _COMBINED_MIKHAIL_PROMPT_FILE.exists():
            text = _COMBINED_MIKHAIL_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_character_prompt_layer() -> str:
    combined = _get_mikhail_combined_prompt_layer()
    if combined:
        return combined
    try:
        if _CHARACTER_PROMPT_FILE.exists():
            text = _CHARACTER_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_orchestrator_prompt_layer() -> str:
    """Runtime conversational orchestration policy for Mikhail."""
    if _get_mikhail_combined_prompt_layer():
        return ""
    try:
        if _ORCHESTRATOR_PROMPT_FILE.exists():
            text = _ORCHESTRATOR_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _get_metabolic_addon_prompt() -> str:
    """Loads optional metabolic add-on prompt as a safe extension."""
    try:
        if _METABOLIC_ADDON_PROMPT_FILE.exists():
            text = _METABOLIC_ADDON_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return _METABOLIC_ADDON_FALLBACK


def _get_clinical_core_prompt() -> str:
    """Ядро формата ответа: паттерн → что значит → что делать → что проверить → важно. Для метаболического контекста."""
    try:
        if _CLINICAL_CORE_PROMPT_FILE.exists():
            text = _CLINICAL_CORE_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    return ""


def _is_metabolic_context(
    user_message: str,
    document_context: str = "",
    chat_history: Optional[list] = None,
) -> bool:
    """
    Enables metabolic add-on only for relevant contexts.
    Keeps existing behavior unchanged for non-metabolic requests.
    """
    parts = [str(user_message or ""), str(document_context or "")]
    for m in (chat_history or [])[-10:]:
        if isinstance(m, dict):
            parts.append(str(m.get("content") or ""))
    low = "\n".join(parts).lower()
    return any(k in low for k in _METABOLIC_KEYS)


def _extract_json_object(text: str) -> Optional[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    candidates = [raw]
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def _is_audio_check_phrase(text: str) -> bool:
    t = str(text or "").lower()
    if not t.strip():
        return False
    keys = (
        "ты меня слышишь",
        "вы меня слышите",
        "меня слышно",
        "слышишь 1 2 3",
        "раз два три",
        "проверка микрофона",
        "проверка связи",
        "алло",
    )
    return any(k in t for k in keys)


def _is_periodontal_query(text: str) -> bool:
    t = str(text or "").lower()
    if not t.strip():
        return False
    oral = ("пародонт", "десн", "кровоточ", "зуб", "полост", "стоматолог")
    # «или» слишком широко (ложные срабатывания в обычной речи)
    compare = ("разниц", "чем отличается", "как лечить", "объясни", "в чем разница")
    return any(k in t for k in oral) and any(k in t for k in compare)


def _is_oral_health_feedback_query(text: str, chat_history: list[dict[str, Any]] | None = None) -> bool:
    t = str(text or "").lower()
    if not t.strip():
        return False
    if any(k in t for k in ("пародонт", "пародонтит", "пародонтоз")):
        return True
    has_feedback = any(k in t for k in ("не в тему", "не по теме", "болезни полости рта", "полости рта"))
    if not has_feedback:
        return False
    history_blob = " ".join(str((x or {}).get("content") or "").lower() for x in (chat_history or []) if isinstance(x, dict))
    return any(k in history_blob for k in ("пародонт", "десн", "полости рта", "пародонтит", "пародонтоз"))


def _periodontal_quick_response() -> str:
    return (
        "Пародонтит и пародонтоз — это не одно и то же.\n\n"
        "Пародонтит чаще связан с воспалением тканей вокруг зуба (налет/бактерии):\n"
        "- десны кровят, отекают, могут болеть;\n"
        "- может появляться подвижность зубов при запущенном процессе.\n\n"
        "Пародонтоз обычно идет без выраженного воспаления:\n"
        "- десна постепенно \"уходит\", оголяются шейки зубов;\n"
        "- чаще меньше крови и отека, больше чувствительность и дискомфорт.\n\n"
        "Что делать в обоих случаях:\n"
        "1) Очный осмотр у пародонтолога (это ключевое).\n"
        "2) Профгигиена и удаление зубного налета/камня.\n"
        "3) Домашняя гигиена: мягкая щетка, чистка 2 раза в день, межзубные ершики/нить.\n"
        "4) При воспалении — местное лечение по схеме врача.\n\n"
        "Если есть сильная боль, гной, выраженный отек или температура — лучше обратиться срочно."
    )


def _compact_lines(text: str, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        s = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
        if s and s not in lines:
            lines.append(s)
        if len(lines) >= limit:
            break
    return lines


_NO_FEVER_DENIAL_MARKERS: tuple[str, ...] = (
    "температуры нет",
    "нет температуры",
    "температуры не было",
    "не было температуры",
    "температуре не было",
    "температур не было",
    "температур нет",
    "без температуры",
    "температура не повышена",
    "не температур",
    "жара нет",
    "жара не было",
    "без жара",
    "лихорадки нет",
    "озноба нет",
    "озноба не было",
    "озноб не было",
    "азноба нет",
    "азноба не было",
    "холода не было",
)


def _dialog_user_text_blob_lower(
    user_message: str,
    chat_history: list[dict[str, Any]] | None,
    *,
    max_user_turns: int = 14,
) -> str:
    parts: list[str] = []
    for m in (chat_history or [])[-max_user_turns:]:
        if str((m or {}).get("role") or "").strip().lower() != "user":
            continue
        c = str((m or {}).get("content") or "").strip().lower()
        if c:
            parts.append(c)
    um = str(user_message or "").strip().lower()
    if um:
        parts.append(um)
    return "\n".join(parts)


def _user_denies_fever(blob: str) -> bool:
    t = (blob or "").strip().lower()
    if not t:
        return False
    return any(k in t for k in _NO_FEVER_DENIAL_MARKERS)


_RESPIRATORY_DENIAL_MARKERS: tuple[str, ...] = (
    "нет кашля",
    "не кашляю",
    "ни о кашляю",
    "ни про кашель",
    "кашля нет",
    "не про кашель",
    "ни о кашле",
    "горло не болит",
    "не про горло",
    "ни о горле",
    "нет насморка",
    "насморка нет",
    "без насморка",
    "без кашля",
    "не одышк",
    "одышки нет",
    "нет одышки",
)

_RESPIRATORY_STRONG_POSITIVE_MARKERS: tuple[str, ...] = (
    "у меня кашель",
    "появился кашель",
    "сухой кашель",
    "влажный кашель",
    "кашель с",
    "больно глотать",
    "насморк есть",
    "есть насморк",
    "ангина",
    "тонзиллит",
    "красное горло",
)

_RESPIRATORY_POSITIVE_HINTS: tuple[str, ...] = (
    "кашель",
    "насморк",
    "боль в горле",
    "горло болит",
    "заложен нос",
    "сопли",
    "мокрота",
    "мокрот",
    "простуд",
    "бронхит",
    "пневмон",
    "сипение",
    "хрипы",
)


def _respiratory_positive_present(text: str) -> bool:
    tl = (text or "").strip().lower()
    if not tl:
        return False
    if any(d in tl for d in _RESPIRATORY_DENIAL_MARKERS):
        return any(s in tl for s in _RESPIRATORY_STRONG_POSITIVE_MARKERS)
    return any(h in tl for h in _RESPIRATORY_POSITIVE_HINTS)


def _filter_repeat_followups(
    questions: list[str],
    *,
    user_message: str,
    chat_history: list[dict[str, Any]] | None = None,
) -> list[str]:
    src = (user_message or "").strip().lower()
    for m in (chat_history or [])[-8:]:
        if str((m or {}).get("role") or "").strip().lower() != "user":
            continue
        src += "\n" + str((m or {}).get("content") or "").strip().lower()
    recent_asst = [
        str((m or {}).get("content") or "").lower()
        for m in (chat_history or [])[-14:]
        if str((m or {}).get("role") or "").strip().lower() == "assistant"
    ]
    asked_join = "\n".join(recent_asst)
    out: list[str] = []
    seen: set[str] = set()
    has_no_fever_context = _user_denies_fever(src)
    has_respiratory_denial = any(k in src for k in _RESPIRATORY_DENIAL_MARKERS)
    has_constitutional_focus = any(
        k in src
        for k in (
            "только устал",
            "просто устал",
            "я про устал",
            "про усталость",
            "не инфекц",
            "не орви",
            "не похоже на инфекц",
            "не похоже на орви",
            "не говорил про кашель",
            "не говорил про горло",
        )
    )
    for q in questions or []:
        qq = str(q or "").strip()
        if not qq:
            continue
        ql = qq.lower()
        if ql in seen:
            continue
        seen.add(ql)
        # Do not repeat already answered milk/lactose trigger questions.
        if any(k in ql for k in ("молоко", "кефир", "молоч", "реакция")) and any(
            k in src for k in ("после кефира", "после молока", "на кефир", "на молоко", "кефир пуч", "пучит после")
        ):
            continue
        # Do not repeat onset-timing question if user already gave timing.
        if any(k in ql for k in ("через сколько", "когда начинается", "время после еды")) and any(
            k in src for k in ("через ", "после ", "в течение дня", "в течение")
        ):
            continue
        # Do not ask about pain if user explicitly denied pain.
        if any(k in ql for k in ("боль", "болит живот", "боль в животе")) and any(
            k in src for k in ("боли нет", "без боли", "не болит")
        ):
            continue
        # Do not ask fever/antipyretic questions when user already denies fever.
        if has_no_fever_context and any(
            k in ql
            for k in (
                "температур",
                "жаропонижа",
                "озноб",
                "лихорад",
                "сбивать температуру",
            )
        ):
            continue
        if (has_respiratory_denial or has_constitutional_focus) and any(
            k in ql
            for k in (
                "кашл",
                "горл",
                "насморк",
                "сопл",
                "мокрот",
                "одыш",
                "бронх",
                "орви",
                "фарингит",
                "ангин",
                "тонзиллит",
                "трахеит",
                "пневмон",
            )
        ):
            continue
        # Headache food-trigger flow: don't re-ask already answered trigger questions.
        if any(k in ql for k in ("шоколад", "вино", "копчен")) and any(
            k in src for k in ("шоколад", "вино", "копчен")
        ):
            continue
        if any(k in ql for k in ("сыр", "творог", "вид сыра", "какой сыр")) and any(
            k in src for k in ("выдержан", "пармезан", "чеддер", "рокфор", "творог", "сыр")
        ):
            continue
        if any(k in ql for k in ("светобояз", "пульсир", "тошнот")) and any(
            k in src for k in ("свет раздражает", "светобоя", "пульсир", "тошнот", "тошнота")
        ):
            continue
        if any(k in src for k in ("уже говорил", "уже сказал", "выше говорил", "повторяешь", "по кругу", "бесконеч")):
            if any(
                k in ql
                for k in (
                    "температур",
                    "кашель",
                    "кашл",
                    "мокрот",
                    "одыш",
                    "десн",
                    "зуб",
                    "как давно",
                    "появились симптом",
                )
            ):
                continue
        if any(
            k in ql
            for k in (
                "как давно",
                "сколько длится",
                "когда появились",
                "появились симптомы",
                "давно ли",
                "сколько времени",
            )
        ) and any(
            k in src
            for k in (
                " день",
                " дня",
                " дней",
                " суток",
                " час",
                " недел",
                "месяц",
                "три дня",
                "3 дня",
                "третий день",
                "симптомы уже",
                "уже третий",
                "последние тр",
                "в течение",
                "уже отвечал",
            )
        ):
            continue
        q_alnum = re.sub(r"[^\w\sёа-я0-9]", "", ql)
        if len(q_alnum) >= 18:
            asked_flat = re.sub(r"[^\w\sёа-я0-9]", "", asked_join)
            if q_alnum in asked_flat or q_alnum[: min(48, len(q_alnum))] in asked_flat:
                continue
        out.append(qq)
    return out


def _food_trigger_block(food_trigger_context: Optional[dict[str, Any]]) -> str:
    ctx = food_trigger_context or {}
    def _food_name(item: dict[str, Any]) -> str:
        raw_id = str((item or {}).get("id") or "").strip().lower()
        aliases = [str(x).strip() for x in ((item or {}).get("aliases") or []) if str(x).strip()]
        ru_aliases = [x for x in aliases if re.search(r"[а-яё]", x, flags=re.IGNORECASE)]
        if ru_aliases:
            return ru_aliases[0]
        food_ru = {
            "cheese": "сыр",
            "cottage_cheese": "творог",
            "chocolate": "шоколад",
            "citrus": "цитрусовые",
            "wine": "вино",
            "coffee": "кофе",
            "fermented_foods": "ферментированные продукты",
            "nuts": "орехи",
            "beans": "бобовые",
            "kefir": "кефир",
            "protein_excess": "избыток белка",
            "carbonated_drinks": "газированные напитки",
        }
        if raw_id in food_ru:
            return food_ru[raw_id]
        return raw_id.replace("_", " ")

    def _compound_name(item: dict[str, Any]) -> str:
        raw_id = str((item or {}).get("id") or "").strip().lower()
        compound_ru = {
            "tyramine": "тирамин",
            "histamine": "гистамин",
            "glutamate": "глутамат",
            "lactose": "лактоза",
            "sulfites": "сульфиты",
            "fodmap": "ферментируемые углеводы (FODMAP)",
            "fermentation_byproducts": "продукты ферментации",
            "putrefaction_byproducts": "продукты белкового распада",
            "swallowed_air": "заглатывание воздуха",
        }
        if raw_id in compound_ru:
            return compound_ru[raw_id]
        return raw_id.replace("_", " ")

    foods = [_food_name(x or {}) for x in (ctx.get("matched_foods") or []) if _food_name(x or {})]
    compounds = [_compound_name(x or {}) for x in (ctx.get("matched_compounds") or []) if _compound_name(x or {})]
    questions = [str(x).strip() for x in (ctx.get("followup_questions") or []) if str(x).strip()]
    safe_steps = [str(x).strip() for x in (ctx.get("safe_recommendations") or []) if str(x).strip()]
    if not (foods or compounds):
        return ""
    reason_bits: list[str] = []
    if foods:
        reason_bits.append("продукт: " + ", ".join(foods[:3]))
    if compounds:
        reason_bits.append("вещества: " + ", ".join(compounds[:3]))
    lines = ["Что может быть триггером:", "- " + "; ".join(reason_bits)]
    if questions:
        lines.append("Какие вопросы нужно уточнить:")
        lines.extend(["- " + q for q in questions[:3]])
    if safe_steps:
        lines.append("Что можно сделать сейчас:")
        lines.extend(["- " + s for s in safe_steps[:2]])
    return "\n".join(lines).strip()


def _inject_food_trigger_block(
    response_text: str,
    food_trigger_context: Optional[dict[str, Any]],
    user_message: str = "",
) -> str:
    text = str(response_text or "").strip()
    msg = str(user_message or "").lower()
    has_food_keywords = any(
        k in msg
        for k in (
            "после еды",
            "после того как поем",
            "поел",
            "поем",
            "еда",
            "продукт",
            "сыр",
            "творог",
            "молоко",
            "кефир",
            "йогурт",
            "шоколад",
            "вино",
            "бобов",
            "фасоль",
            "газиров",
        )
    )
    # Important: show food-trigger block only when current user message
    # explicitly indicates food relation; do not leak prior-context matches.
    if not has_food_keywords:
        return text
    block = _food_trigger_block(food_trigger_context or {})
    if not text or not block:
        return text
    if "что может быть триггером" in text.lower():
        return text
    return text + "\n\n" + block


def _food_trigger_display_lists(food_trigger_context: Optional[dict[str, Any]]) -> tuple[list[str], list[str], list[str], list[str]]:
    ctx = food_trigger_context or {}
    food_map = {
        "cheese": "сыр",
        "cottage_cheese": "творог",
        "chocolate": "шоколад",
        "citrus": "цитрусовые",
        "wine": "вино",
        "coffee": "кофе",
        "fermented_foods": "ферментированные продукты",
        "nuts": "орехи",
        "beans": "бобовые",
        "kefir": "кефир",
        "protein_excess": "избыток белка",
        "carbonated_drinks": "газированные напитки",
    }
    compound_map = {
        "tyramine": "тирамин",
        "histamine": "гистамин",
        "glutamate": "глутамат",
        "lactose": "лактоза",
        "sulfites": "сульфиты",
        "fodmap": "ферментируемые углеводы (FODMAP)",
        "fermentation_byproducts": "продукты ферментации",
        "putrefaction_byproducts": "продукты белкового распада",
        "swallowed_air": "заглатывание воздуха",
    }
    food_ids: list[str] = []
    food_labels: list[str] = []
    for item in (ctx.get("matched_foods") or []):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip().lower()
        if not raw_id:
            continue
        aliases = [str(x).strip() for x in (item.get("aliases") or []) if str(x).strip()]
        ru_alias = next((x for x in aliases if re.search(r"[а-яё]", x, flags=re.IGNORECASE)), "")
        label = ru_alias or food_map.get(raw_id) or raw_id.replace("_", " ")
        food_ids.append(raw_id)
        food_labels.append(label)

    compound_ids: list[str] = []
    compound_labels: list[str] = []
    for item in (ctx.get("matched_compounds") or []):
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip().lower()
        if not raw_id:
            continue
        label = compound_map.get(raw_id) or raw_id.replace("_", " ")
        compound_ids.append(raw_id)
        compound_labels.append(label)
    return food_ids, food_labels, compound_ids, compound_labels


def _structured_output_instruction() -> str:
    return (
        "\n\nФормат ответа модели: верни СТРОГО JSON по заданной схеме. "
        "Поле patient_facing_response должно содержать готовый понятный ответ для пользователя на русском языке. "
        "Не добавляй markdown, пояснения, code fences или любой текст вне JSON."
    )


def _apply_orchestrator_rules(
    *,
    base_text: str,
    consultation_state: Any,
    has_lab_data: bool,
    force_questions: bool,
    followup_questions: list[str],
    user_message: str = "",
) -> str:
    text = str(base_text or "").strip()
    dialogue_meta = getattr(consultation_state, "dialogue_meta", {}) or {}
    labs_meta = getattr(consultation_state, "labs_meta", {}) or {}
    suggested_labs = list(getattr(consultation_state, "suggested_labs", []) or [])

    if force_questions and followup_questions and dialogue_meta.get("ask_one_by_one", True):
        question = str(followup_questions[0]).strip()
        text = (
            "Похоже на: нужно уточнить 1 ключевую деталь.\n"
            "Что уточнить: " + question + "\n"
            "Что делать сейчас: пока щадящий режим и наблюдение.\n"
            "Когда к врачу: при ухудшении, новых тревожных признаках или резком усилении симптомов.\n"
            + DISCLAIMER_TEXT
        )

    if (
        (not has_lab_data)
        and labs_meta.get("recommend_if_uncertain", True)
        and suggested_labs
        and not getattr(consultation_state, "can_conclude", False)
    ):
        low_src = (str(user_message or "") + " " + text).lower()
        is_trauma_context = any(
            k in low_src
            for k in (
                "травм",
                "упал",
                "паден",
                "ушиб",
                "растяж",
                "мениск",
                "связк",
                "голеностоп",
                "плеч",
                "спин",
                "не наступ",
                "распух",
                "отек",
            )
        )
        if is_trauma_context:
            return text.strip()
        lab_lines = "\n".join("- " + x for x in suggested_labs[:3])
        text += (
            "\n\nЧтобы повысить точность, можно загрузить анализы:\n"
            f"{lab_lines}\n"
            "Загрузите их во вкладке «Анализы», и мы продолжим этот же диалог с учетом документов."
        )
    return text.strip()


def _consultation_case_name(complaint: str) -> str:
    base = re.sub(r"\s+", " ", str(complaint or "").strip())
    if not base:
        base = "Консультация"
    return ("Диалог: " + base)[:72]


def _current_season_label() -> str:
    month = time.localtime().tm_mon
    if month in (12, 1, 2):
        return "зима"
    if month in (3, 4, 5):
        return "весна"
    if month in (6, 7, 8):
        return "лето"
    return "осень"


def _estimate_openai_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Rough estimated cost in USD using simple per-1M token tables.
    Values are configurable in code and should be treated as proxy analytics, not billing truth.
    """
    name = str(model or "").lower()
    pricing_per_million = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4.1": {"input": 2.00, "output": 8.00},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    rates = None
    for key, val in pricing_per_million.items():
        if key in name:
            rates = val
            break
    if not rates:
        return 0.0
    cost = (float(prompt_tokens or 0) / 1_000_000.0) * rates["input"] + (
        float(completion_tokens or 0) / 1_000_000.0
    ) * rates["output"]
    return round(cost, 6)


def _protocol_from_top20(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a complaint protocol from top-20/top-100 entry for weak complaints (no complaint_reference hit).
    Ensures anamnesis_questions, red_flags and suggested_labs are available for offline and state."""
    aliases = [str(x or "").strip() for x in (entry.get("aliases") or []) if str(x).strip()]
    complaint = aliases[0] if aliases else str(entry.get("symptom_cluster") or "жалоба")
    key_questions = [str(x).strip() for x in (entry.get("key_questions") or []) if str(x).strip()]
    red_flags = [str(x).strip() for x in (entry.get("red_flags") or []) if str(x).strip()]
    likely = entry.get("likely_causes") or []
    see_doctor = entry.get("see_doctor_if") or []
    description = (likely[0] if likely else "") or "Уточним симптомы для рекомендаций."
    suggested_labs: list[str] = []
    if see_doctor:
        suggested_labs.append("По показаниям: ОАК, биохимия — по назначению врача")
    return {
        "complaint": complaint,
        "description": description,
        "anamnesis_questions": key_questions[:6] or ["Что беспокоит, когда началось, что пробовали?"],
        "red_flags": red_flags[:8],
        "suggested_labs": suggested_labs,
        "seasonality": {"year_round": True},
        "_source_top20": True,
    }


def _merge_top20_into_protocol(complaint_protocol: dict[str, Any], top20_entry: dict[str, Any]) -> dict[str, Any]:
    """Strengthen complaint protocol with top-20 red_flags and anamnesis when both exist."""
    out = dict(complaint_protocol)
    existing_anamnesis = set(str(x or "").strip() for x in (out.get("anamnesis_questions") or []) if str(x).strip())
    key_questions = [str(x).strip() for x in (top20_entry.get("key_questions") or []) if str(x).strip()]
    for q in key_questions:
        if q and q not in existing_anamnesis:
            existing_anamnesis.add(q)
            out.setdefault("anamnesis_questions", []).append(q)
    out["anamnesis_questions"] = out.get("anamnesis_questions") or []
    existing_red = set(str(x or "").strip() for x in (out.get("red_flags") or []) if str(x).strip())
    for f in top20_entry.get("red_flags") or []:
        s = str(f or "").strip()
        if s and s not in existing_red:
            existing_red.add(s)
            out.setdefault("red_flags", []).append(s)
    out["red_flags"] = out.get("red_flags") or []
    if not out.get("suggested_labs") and (top20_entry.get("see_doctor_if") or []):
        out["suggested_labs"] = ["По показаниям: ОАК, биохимия — по назначению врача"]
    return out


def _should_use_offline_priority(
    *,
    complaint_protocol: Optional[dict[str, Any]],
    current_season: str,
    documents_count: int,
    chat_history: list,
) -> bool:
    routing_cfg = get_routing_control_config()
    if not bool(routing_cfg.get("offline_first_enabled")):
        return False
    if not isinstance(complaint_protocol, dict):
        return False
    if documents_count > 0:
        return False
    user_turns = sum(1 for m in (chat_history or []) if (m or {}).get("role") == "user")
    if user_turns > int(routing_cfg.get("max_offline_first_user_turns") or 1):
        return False
    if complaint_protocol.get("_source_top20"):
        return True
    prioritized = get_prioritized_complaints(
        limit=int(routing_cfg.get("top_complaints_limit") or 40),
        season=current_season,
        season_weight_multiplier=float(routing_cfg.get("season_weight_multiplier") or 1.0),
        demand_weight_multiplier=float(routing_cfg.get("demand_weight_multiplier") or 1.0),
    )
    names = {
        str(x.get("complaint") or "").strip().lower()
        for x in prioritized
        if str(x.get("complaint") or "").strip()
    }
    return str(complaint_protocol.get("complaint") or "").strip().lower() in names


def _build_offline_priority_response(
    *,
    complaint_protocol: dict[str, Any],
    season: str,
) -> tuple[str, str]:
    complaint = str(complaint_protocol.get("complaint") or "Жалоба").strip()
    desc = str(complaint_protocol.get("description") or "").strip()
    question = ""
    anamnesis = [str(x).strip() for x in (complaint_protocol.get("anamnesis_questions") or []) if str(x).strip()]
    if anamnesis:
        question = anamnesis[0]
    red_flags = [str(x).strip() for x in (complaint_protocol.get("red_flags") or []) if str(x).strip()]
    seasonality = complaint_protocol.get("seasonality") or {}
    peaks = [str(x).strip().lower() for x in (seasonality.get("peak_seasons") or []) if str(x).strip()]
    seasonal_note = ""
    if peaks:
        seasonal_note = " Сейчас " + season + ", для этой жалобы более характерны сезоны: " + ", ".join(peaks) + "."
    elif seasonality.get("year_round"):
        seasonal_note = " Эта жалоба встречается круглый год."
    when_urgent = "Если появятся красные флаги или резкое ухудшение, срочно звоните 103 или в местную службу спасения 112."
    if red_flags:
        when_urgent = "При появлении: " + "; ".join(red_flags[:5]) + " — срочно обратитесь за медпомощью (103 или 112)."
    response = (
        "Проблема: " + complaint + ".\n"
        "Почему: " + (desc or "Для более точного вывода сначала уточним один ключевой пункт.") + seasonal_note + "\n"
        "Что делать сегодня:\n"
        + ("- Ок. " + question + "\n" if question else "- Ключевые симптомы и их длительность.\n")
        + "Когда срочно:\n"
        + "- " + when_urgent + "\n"
        + DISCLAIMER_TEXT
    )
    return response, ("Частая жалоба: " + complaint + ". Сначала уточним один ключевой вопрос.").strip()


def _build_structured_payload(
    *,
    response_text: str,
    response_simple: Optional[str],
    effective_user_message: str,
    severity: str,
    red_flags_present: bool,
    follow_up_questions: list[str],
    clinical_profiles: list[dict[str, Any]],
    when_urgent: Optional[list[str]] = None,
    parsed_payload: Optional[dict[str, Any]] = None,
    preferred_labs: Optional[list[str]] = None,
    symptom_context: Optional[dict[str, Any]] = None,
    nutrition_context: Optional[dict[str, Any]] = None,
    lab_context: Optional[dict[str, Any]] = None,
    food_trigger_context: Optional[dict[str, Any]] = None,
    symptom_cause_context: Optional[dict[str, Any]] = None,
    symptom_severity_context: Optional[dict[str, Any]] = None,
    multidisciplinary_context: Optional[dict[str, Any]] = None,
    relevance_funnel_context: Optional[dict[str, Any]] = None,
    reasoning_context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    parsed = parsed_payload or _extract_json_object(response_text)
    hypotheses: list[dict[str, Any]] = []
    food_ids, food_labels, compound_ids, compound_labels = _food_trigger_display_lists(food_trigger_context)

    if parsed and isinstance(parsed.get("top_hypotheses"), list):
        for item in parsed.get("top_hypotheses")[:3]:
            if isinstance(item, dict) and item.get("name"):
                hypotheses.append(
                    {
                        "name": str(item.get("name") or "").strip(),
                        "likelihood": str(item.get("likelihood") or "possible").strip() or "possible",
                        "why_it_fits": [str(x).strip() for x in (item.get("why_it_fits") or []) if str(x).strip()],
                    }
                )

    if not hypotheses:
        labels = ["high", "moderate", "possible"]
        for idx, profile in enumerate(clinical_profiles[:3]):
            name = str((profile or {}).get("name") or "").strip()
            if not name:
                continue
            why = str((profile or {}).get("description") or "").strip()
            hypotheses.append(
                {
                    "name": name,
                    "likelihood": labels[idx] if idx < len(labels) else "possible",
                    "why_it_fits": [why] if why else [],
                }
            )

    if not hypotheses:
        cause_labels = [
            str(x).strip() for x in ((symptom_cause_context or {}).get("candidate_hypotheses") or []) if str(x).strip()
        ]
        for idx, label in enumerate(cause_labels[:3]):
            hypotheses.append(
                {
                    "name": label,
                    "likelihood": "possible" if idx else "moderate",
                    "why_it_fits": ["Из symptom_cause_graph как дополнительный слой гипотез."],
                }
            )

    recommended_labs: list[str] = []
    for item in preferred_labs or []:
        s = str(item or "").strip()
        if s and s not in recommended_labs:
            recommended_labs.append(s)

    for item in (lab_context or {}).get("suggested_tests", []) or []:
        s = str(item or "").strip()
        if s and s not in recommended_labs:
            recommended_labs.append(s)
    for item in (multidisciplinary_context or {}).get("recommended_tests", []) or []:
        s = str(item or "").strip()
        if s and s not in recommended_labs:
            recommended_labs.append(s)

    for profile in clinical_profiles[:2]:
        for item in (profile or {}).get("diagnostics") or []:
            s = str(item or "").strip()
            if s and s not in recommended_labs:
                recommended_labs.append(s)
            if len(recommended_labs) >= 5:
                break
        if len(recommended_labs) >= 5:
            break

    parsed_followups = parsed.get("follow_up_questions") if isinstance(parsed, dict) else None
    if isinstance(parsed_followups, list):
        follow_up_questions = (
            [str(x).strip() for x in parsed_followups if str(x).strip()][:MAX_QUESTIONS_PER_TURN] or follow_up_questions
        )

    parsed_missing = parsed.get("missing_information") if isinstance(parsed, dict) else None
    missing_information = (
        [str(x).strip() for x in parsed_missing if str(x).strip()][:3]
        if isinstance(parsed_missing, list)
        else list(follow_up_questions)
    )

    parsed_plan = parsed.get("care_plan_today") if isinstance(parsed, dict) else None
    care_plan_today = (
        [str(x).strip() for x in parsed_plan if str(x).strip()][:4]
        if isinstance(parsed_plan, list)
        else _compact_lines(response_text, limit=4)
    )

    parsed_urgent = parsed.get("when_urgent") if isinstance(parsed, dict) else None
    when_urgent = (
        [str(x).strip() for x in parsed_urgent if str(x).strip()][:4]
        if isinstance(parsed_urgent, list)
        else (when_urgent or [])
    )

    md_hyp = [str(x).strip() for x in ((multidisciplinary_context or {}).get("candidate_hypotheses") or []) if str(x).strip()]
    if md_hyp:
        existing = {str((h or {}).get("name") or "").strip().lower() for h in hypotheses if isinstance(h, dict)}
        for label in md_hyp[:3]:
            if label.lower() in existing:
                continue
            hypotheses.append(
                {
                    "name": label,
                    "likelihood": "possible",
                    "why_it_fits": ["Поддержано мультидисциплинарной выборкой по библиотеке документов."],
                }
            )
            existing.add(label.lower())

    md_questions = [str(x).strip() for x in ((multidisciplinary_context or {}).get("followup_questions") or []) if str(x).strip()]
    if md_questions:
        for q in md_questions:
            if q and q not in follow_up_questions:
                follow_up_questions.append(q)
    follow_up_questions = follow_up_questions[:MAX_QUESTIONS_PER_TURN]
    symptom_int_layer = dict((food_trigger_context or {}).get("symptom_intelligence_layer") or {})
    causal_layer = dict((food_trigger_context or {}).get("causal_engine_layer") or {})
    non_drug_layer = dict((food_trigger_context or {}).get("non_drug_engine_layer") or {})
    nutraceutical_layer = dict((food_trigger_context or {}).get("nutraceutical_engine_layer") or {})
    amino_layer = dict((food_trigger_context or {}).get("amino_engine_layer") or {})
    trigger_red_flags = [
        str(x).strip()
        for x in (
            ((food_trigger_context or {}).get("mcas_comorbid_layer") or {}).get("red_flags")
            or symptom_int_layer.get("red_flags")
            or []
        )
        if str(x).strip()
    ][:4]
    symptom_patterns = [
        str((x or {}).get("id") or "").strip()
        for x in (symptom_int_layer.get("detected_patterns") or [])
        if str((x or {}).get("id") or "").strip()
    ]
    symptom_clusters = [
        str((x or {}).get("id") or "").strip()
        for x in (symptom_int_layer.get("detected_clusters") or [])
        if str((x or {}).get("id") or "").strip()
    ]
    cause_model_dict = dict(causal_layer.get("cause_model") or {})
    cause_root = [str(x).strip() for x in (cause_model_dict.get("root_causes") or []) if str(x).strip()]
    amino_patterns = [
        str((x or {}).get("id") or "").strip()
        for x in (amino_layer.get("amino_patterns") or [])
        if str((x or {}).get("id") or "").strip()
    ]

    pattern_scores: dict[str, int] = {}
    for pid in symptom_patterns:
        pattern_scores[pid] = int(pattern_scores.get(pid, 0)) + 2
    for rid in cause_root:
        pattern_scores[rid] = int(pattern_scores.get(rid, 0)) + 2
    for ap in amino_patterns:
        pattern_scores[ap] = int(pattern_scores.get(ap, 0)) + 2
    if bool(non_drug_layer.get("detox_needed")):
        pattern_scores["detox_support_needed"] = int(pattern_scores.get("detox_support_needed", 0)) + 2
    if int(causal_layer.get("predisposition_score") or 0) >= 40:
        pattern_scores["predisposition_load"] = int(pattern_scores.get("predisposition_load", 0)) + 2
    if int(symptom_int_layer.get("system_count") or 0) >= 3:
        pattern_scores["multisystem_involvement"] = int(pattern_scores.get("multisystem_involvement", 0)) + 2

    score_values = list(pattern_scores.values())
    top_score = max(score_values) if score_values else 0
    evidence_count = (
        len(symptom_patterns)
        + len(cause_root)
        + len(amino_patterns)
        + (1 if bool(non_drug_layer.get("detox_needed")) else 0)
    )
    if top_score >= 6 or evidence_count >= 8:
        confidence = "high"
    elif top_score >= 3 or evidence_count >= 4:
        confidence = "moderate"
    else:
        confidence = "low"

    lab_ctx = dict(lab_context or {})
    thyroid_ctx = dict(lab_ctx.get("thyroid_context") or lab_ctx.get("thyroid_layer") or {})
    a1at_ctx = dict(lab_ctx.get("a1at_context") or lab_ctx.get("a1at_layer") or {})
    indexes_ctx = dict(lab_ctx.get("integral_indexes") or lab_ctx.get("indexes_context") or {})
    unified_engine_snapshot = {
        "version": "v1_compact",
        "coverage": _get_scenario_coverage_snapshot(),
        "pattern_scores": pattern_scores,
        "confidence": confidence,
        "symptom": {
            "clusters": symptom_clusters[:12],
            "patterns": symptom_patterns[:12],
            "system_count": int(symptom_int_layer.get("system_count") or 0),
        },
        "causal": {
            "cause_model": cause_model_dict,
            "trigger_detected": [str(x).strip() for x in (causal_layer.get("trigger_detected") or []) if str(x).strip()][:12],
            "predisposition_score": int(causal_layer.get("predisposition_score") or 0),
            "timeline": dict(causal_layer.get("timeline_engine") or {}),
        },
        "non_drug": {
            "plan": dict(non_drug_layer.get("non_drug_plan") or {}),
            "detox_needed": bool(non_drug_layer.get("detox_needed")),
            "diet": [str(x).strip() for x in (non_drug_layer.get("diet_recommendations") or []) if str(x).strip()][:8],
            "lifestyle": [str(x).strip() for x in (non_drug_layer.get("lifestyle_recommendations") or []) if str(x).strip()][:8],
        },
        "nutraceutical": {
            "options": [str(x).strip() for x in (nutraceutical_layer.get("nutraceutical_options") or []) if str(x).strip()][:16],
            "cautious_start": dict(nutraceutical_layer.get("cautious_medication_start") or {}),
            "doctor_only": [str(x).strip() for x in (nutraceutical_layer.get("doctor_only_options") or []) if str(x).strip()][:12],
        },
        "amino": {
            "patterns": amino_patterns[:8],
            "metabolic_state": str(amino_layer.get("metabolic_state") or "").strip(),
            "detox_status": str(amino_layer.get("detox_status") or "").strip(),
            "neuro_balance": str(amino_layer.get("neuro_balance") or "").strip(),
            "energy_status": str(amino_layer.get("energy_status") or "").strip(),
            "preanalytic_warnings": [str(x).strip() for x in (amino_layer.get("preanalytic_warnings") or []) if str(x).strip()][:4],
        },
        "thyroid": thyroid_ctx,
        "a1at": a1at_ctx,
        "indexes": indexes_ctx,
    }

    return {
        "severity": str((parsed or {}).get("severity") or severity).upper(),
        "red_flags_present": bool((parsed or {}).get("red_flags_present")) or red_flags_present,
        "chief_complaint": str((parsed or {}).get("chief_complaint") or effective_user_message).strip(),
        "missing_information": missing_information,
        "follow_up_questions": list(follow_up_questions),
        "top_hypotheses": hypotheses,
        "recommended_labs": recommended_labs,
        "care_plan_today": care_plan_today,
        "when_urgent": when_urgent,
        "patient_summary": str((parsed or {}).get("patient_summary") or response_simple or response_text).strip(),
        "patient_facing_response": str(
            (parsed or {}).get("patient_facing_response") or response_text or response_simple or ""
        ).strip(),
        "disclaimer": str((parsed or {}).get("disclaimer") or DISCLAIMER_TEXT).strip(),
        "trigger_candidates": food_labels[:5],
        "trigger_compounds": compound_labels[:5],
        "trigger_candidate_ids": food_ids[:5],
        "trigger_compound_ids": compound_ids[:5],
        "trigger_questions": [
            str(x).strip() for x in ((food_trigger_context or {}).get("followup_questions") or []) if str(x).strip()
        ][:MAX_QUESTIONS_PER_TURN],
        "trigger_red_flags": trigger_red_flags,
        "symptom_clusters_detected": [
            str((x or {}).get("id") or "").strip()
            for x in (symptom_int_layer.get("detected_clusters") or [])
            if str((x or {}).get("id") or "").strip()
        ][:10],
        "symptom_patterns_detected": [
            str((x or {}).get("id") or "").strip()
            for x in (symptom_int_layer.get("detected_patterns") or [])
            if str((x or {}).get("id") or "").strip()
        ][:8],
        "symptom_system_count": int(symptom_int_layer.get("system_count") or 0),
        "cause_model": dict(causal_layer.get("cause_model") or {}),
        "trigger_detected": [str(x).strip() for x in (causal_layer.get("trigger_detected") or []) if str(x).strip()][:12],
        "predisposition_score": int(causal_layer.get("predisposition_score") or 0),
        "timeline_engine": dict(causal_layer.get("timeline_engine") or {}),
        "non_drug_plan": dict(non_drug_layer.get("non_drug_plan") or {}),
        "diet_recommendations": [str(x).strip() for x in (non_drug_layer.get("diet_recommendations") or []) if str(x).strip()][:8],
        "lifestyle_recommendations": [str(x).strip() for x in (non_drug_layer.get("lifestyle_recommendations") or []) if str(x).strip()][:8],
        "detox_needed": bool(non_drug_layer.get("detox_needed")),
        "diet": [str(x).strip() for x in (non_drug_layer.get("diet") or []) if str(x).strip()][:8],
        "what_to_remove": [str(x).strip() for x in (non_drug_layer.get("what_to_remove") or []) if str(x).strip()][:12],
        "what_to_add": [str(x).strip() for x in (non_drug_layer.get("what_to_add") or []) if str(x).strip()][:12],
        "lifestyle": [str(x).strip() for x in (non_drug_layer.get("lifestyle") or []) if str(x).strip()][:8],
        "detox": [str(x).strip() for x in (non_drug_layer.get("detox") or []) if str(x).strip()][:8],
        "expected_effect": [str(x).strip() for x in (non_drug_layer.get("expected_effect") or []) if str(x).strip()][:6],
        "nutraceutical_options": [str(x).strip() for x in (nutraceutical_layer.get("nutraceutical_options") or []) if str(x).strip()][:16],
        "cautious_medication_start": dict(nutraceutical_layer.get("cautious_medication_start") or {}),
        "doctor_only_options": [str(x).strip() for x in (nutraceutical_layer.get("doctor_only_options") or []) if str(x).strip()][:12],
        "nutraceutical_followup_questions": [str(x).strip() for x in (nutraceutical_layer.get("followup_questions") or []) if str(x).strip()][:4],
        "amino_patterns": [
            str((x or {}).get("id") or "").strip()
            for x in (amino_layer.get("amino_patterns") or [])
            if str((x or {}).get("id") or "").strip()
        ][:8],
        "metabolic_state": str(amino_layer.get("metabolic_state") or "").strip(),
        "detox_status": str(amino_layer.get("detox_status") or "").strip(),
        "neuro_balance": str(amino_layer.get("neuro_balance") or "").strip(),
        "energy_status": str(amino_layer.get("energy_status") or "").strip(),
        "amino_preanalytic_warnings": [str(x).strip() for x in (amino_layer.get("preanalytic_warnings") or []) if str(x).strip()][:4],
        "unified_engine_snapshot": unified_engine_snapshot,
        "trigger_safe_steps": [
            str(x).strip() for x in ((food_trigger_context or {}).get("safe_recommendations") or []) if str(x).strip()
        ][:2],
        "expert_lenses": [str(x).strip() for x in ((multidisciplinary_context or {}).get("expert_lenses") or []) if str(x).strip()][:6],
        "specialist_routes": [str(x).strip() for x in ((multidisciplinary_context or {}).get("specialist_routes") or []) if str(x).strip()][:5],
        "nutrition_focus": [str(x).strip() for x in ((multidisciplinary_context or {}).get("nutrition_focus") or []) if str(x).strip()][:4],
        "activity_focus": [str(x).strip() for x in ((multidisciplinary_context or {}).get("activity_focus") or []) if str(x).strip()][:4],
        "symptom_cause_candidates": [
            str(x).strip() for x in ((symptom_cause_context or {}).get("candidate_hypotheses") or []) if str(x).strip()
        ][:5],
        "symptom_cause_differential": (symptom_cause_context or {}).get("differentials") or [],
        "symptom_severity": str((symptom_severity_context or {}).get("severity") or "").strip(),
        "symptom_severity_route": str((symptom_severity_context or {}).get("route") or "").strip(),
        "symptom_severity_red_flags": (symptom_severity_context or {}).get("red_flag_matches") or [],
        "relevance_funnel": relevance_funnel_context or {},
        "medical_reasoning": reasoning_context or {},
        "symptom_context": symptom_context or {},
        "nutrition_context": nutrition_context or {},
        "lab_context": lab_context or {},
        "multidisciplinary_context": multidisciplinary_context or {},
        "treatment_plan": dict((parsed or {}).get("treatment_plan") or {}),
        "safe_summary_renderer": dict((parsed or {}).get("safe_summary_renderer") or {}),
        "followup_ready_for_summary": bool((parsed or {}).get("followup_ready_for_summary")),
    }


def _build_context_string(
    profile: dict,
    documents_count: int,
    symptom_entries: list,
    vitals: Optional[dict] = None,
) -> str:
    parts = []
    if profile.get("date_of_birth"):
        parts.append("Дата рождения: " + str(profile.get("date_of_birth")))
    if profile.get("sex"):
        sex = str(profile.get("sex") or "").strip().lower()
        sex_label = "женский" if sex == "female" else "мужской" if sex == "male" else ""
        if sex_label:
            parts.append("Пол: " + sex_label)
    if profile.get("chronic_conditions"):
        parts.append("Хронические заболевания: " + ", ".join(profile.get("chronic_conditions", [])))
    if profile.get("allergies"):
        parts.append("Аллергии: " + ", ".join(profile.get("allergies", [])))
    if profile.get("family_history"):
        parts.append("Семейный анамнез: " + str(profile.get("family_history")))
    if vitals:
        vp = []
        if vitals.get("systolic") is not None and vitals.get("diastolic") is not None:
            vp.append(f"давление {vitals['systolic']}/{vitals['diastolic']}")
        if vitals.get("pulse") is not None:
            vp.append(f"пульс {vitals['pulse']}")
        if vitals.get("weight_kg") is not None:
            vp.append(f"вес {vitals['weight_kg']} кг")
        if vitals.get("height_cm") is not None:
            vp.append(f"рост {vitals['height_cm']} см")
        if vitals.get("hrv_rmssd") is not None:
            vp.append(f"HRV RMSSD {vitals['hrv_rmssd']} мс")
        if vitals.get("sleep_hours") is not None:
            vp.append(f"сон {vitals['sleep_hours']} ч")
        if vitals.get("sleep_quality"):
            vp.append(f"качество сна {vitals['sleep_quality']}")
        if vp:
            parts.append("[DEVICE]/объективные данные: " + ", ".join(vp))
    if documents_count:
        parts.append(
            f"Пользователь уже загружал документы с анализами: {documents_count} шт. "
            "Учитывай только если релевантны текущему запросу."
        )
    else:
        parts.append("Документов с анализами у пользователя пока нет.")
    if symptom_entries:
        recent = symptom_entries[-3:]
        parts.append(
            "Недавние записи о симптомах (учитывай только если относятся к текущей теме): "
            + " | ".join((e.get("text", "") or "")[:80] for e in recent)
        )
    return "\n".join(parts) if parts else "Дополнительный контекст не указан."


def _format_profile_age(profile: dict[str, Any]) -> str:
    dob_raw = str((profile or {}).get("date_of_birth") or "").strip()
    if not dob_raw:
        return ""
    try:
        birth = date.fromisoformat(dob_raw)
        today = date.today()
        years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        return str(years) if years > 0 else ""
    except Exception:
        return ""


def _format_profile_sex(profile: dict[str, Any]) -> str:
    sex = str((profile or {}).get("sex") or "").strip().lower()
    if sex in {"male", "m", "man", "м", "муж", "мужской"}:
        return "мужской"
    if sex in {"female", "f", "woman", "ж", "жен", "женский"}:
        return "женский"
    return ""


def _build_emergency_suspected_reason(user_message: str, structured_payload: Optional[dict[str, Any]]) -> str:
    hyp = ""
    if isinstance(structured_payload, dict):
        top = structured_payload.get("top_hypotheses") or []
        if isinstance(top, list):
            for item in top:
                if isinstance(item, dict) and str(item.get("name") or "").strip():
                    hyp = str(item.get("name")).strip()
                    break
    if hyp:
        return hyp
    msg = (user_message or "").lower()
    if any(k in msg for k in ("боль в груди", "давит в груди", "сильная боль в груди")):
        return "острый коронарный синдром"
    if any(k in msg for k in ("одыш", "не хватает воздуха", "трудно дышать")):
        return "острая дыхательная недостаточность"
    if any(k in msg for k in ("судорог", "потеря сознания", "обморок")):
        return "острое неврологическое состояние"
    return "острое состояние, требуется очная экстренная оценка"


def _summarize_for_report(chat_history: list, last_message: str, symptom_entries: list) -> str:
    parts = [last_message[:500] if last_message else ""]
    if symptom_entries:
        parts.append("Записи симптомов: " + " | ".join((e.get("text", "") or "")[:80] for e in symptom_entries[-3:]))
    return " ".join(parts)[:600]


def _relevant_simple_snippet(simple_text: str, user_message: str, max_len: int = 700) -> str:
    """Выбирает из simple-ответа наиболее релевантные фразы по словам пользователя."""
    text = re.sub(r"\s+", " ", (simple_text or "")).strip()
    if not text:
        return ""
    query_words = [w for w in re.findall(r"[а-яёa-z0-9]+", (user_message or "").lower()) if len(w) >= 4]
    if not query_words:
        return text[:max_len]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    picked: list[str] = []
    for s in sentences:
        sl = s.lower()
        if any(w in sl for w in query_words):
            picked.append(s.strip())
        if len(" ".join(picked)) >= max_len:
            break
    if not picked:
        return text[:max_len]
    return " ".join(picked)[:max_len]


def _extract_best_professional_block(professional_text: str, user_message: str) -> str:
    """
    Извлекает наиболее релевантный блок из professional-формата офлайн-справочника:
    блоки начинаются с 'Тема:'.
    """
    text = (professional_text or "").strip()
    if not text:
        return ""
    blocks = []
    current = []
    for line in text.splitlines():
        if line.strip().startswith("Тема:") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())
    if not blocks:
        return text[:800]

    query_words = [w for w in re.findall(r"[а-яёa-z0-9]+", (user_message or "").lower()) if len(w) >= 4]
    if not query_words:
        return blocks[0][:900]

    user_low = (user_message or "").lower()
    has_choking_context = any(k in user_low for k in ("поперх", "подавил", "задыха", "инород", "удуш", "не могу дышать"))
    has_burn_context = any(k in user_low for k in ("ожог", "обжег", "обжёг", "обвар"))

    def score(block: str) -> int:
        b = block.lower()
        # Жёстко исключаем нерелевантные блоки про инородное тело/ожог,
        # если пользователь это не упоминал.
        if ("инород" in b or "поперх" in b or "удуш" in b) and not has_choking_context:
            return -1000
        if "ожог" in b and not has_burn_context:
            return -1000
        return sum(1 for w in set(query_words) if w in b)

    best = max(blocks, key=score)
    return best[:900]


def _build_doctor_like_offline_reply(user_message: str, simple: str, professional: str) -> str:
    """
    Формирует более профессиональный ответ из офлайн-данных:
    краткая гипотеза, что делать сейчас, когда очно к врачу.
    """
    best_block = _extract_best_professional_block(professional, user_message)
    if not best_block and simple:
        return "По вашему описанию наиболее вероятно следующее:\n" + simple[:700]

    topic = ""
    brief = ""
    first_aid = ""
    when_doctor = ""
    urgent = ""
    treatment = ""
    for line in best_block.splitlines():
        s = line.strip()
        if s.startswith("Тема:"):
            topic = s.replace("Тема:", "").strip()
        elif s.startswith("Кратко:"):
            brief = s.replace("Кратко:", "").strip()
        elif s.startswith("Первая помощь:"):
            first_aid = s.replace("Первая помощь:", "").strip()
        elif s.startswith("Когда к врачу:"):
            when_doctor = s.replace("Когда к врачу:", "").strip()
        elif s.startswith("Срочно (103):"):
            urgent = s.replace("Срочно (103):", "").strip()
        elif s.startswith("Методы лечения:"):
            treatment = s.replace("Методы лечения:", "").strip()

    lines = []
    if topic:
        lines.append("Наиболее вероятный рабочий вариант сейчас: " + topic + ".")
    if brief:
        lines.append("Почему так: " + brief)
    if first_aid:
        lines.append("Что делать сейчас: " + first_aid)
    if treatment:
        lines.append("Общий подход к лечению: " + treatment)
    if when_doctor:
        lines.append("Очный осмотр нужен, если: " + when_doctor)
    if urgent:
        lines.append("Срочно: " + urgent)
    if not lines and simple:
        lines.append(simple[:700])
    return "\n".join(lines)


def _has_minimum_clinical_context(user_message: str, has_lab_data: bool) -> bool:
    """
    Strict relevance gate:
    do not produce direct treatment plan until enough context is collected.
    """
    msg = (user_message or "").strip().lower()
    if not msg:
        return False
    if has_lab_data and len(msg) >= 20:
        return True

    extracted = extract_symptoms_nutrition_activity_intent(msg)
    common_symptom_keywords = (
        "газообраз", "метеор", "вздут", "изжог", "диаре", "запор", "тошнот", "боль в животе",
        "кашл", "горло", "насморк", "сопл", "хрип", "температ", "головн", "давлен",
    )
    has_common_symptom = any(k in msg for k in common_symptom_keywords)
    has_symptom = bool(
        extracted.get("symptoms")
        or extracted.get("nutrition_mentions")
        or extracted.get("activity_mentions")
        or has_common_symptom
    )
    if not has_symptom:
        return False

    has_duration = any(k in msg for k in ("день", "дня", "недел", "месяц", "час", "сут", "длится", "давно"))
    has_severity = any(k in msg for k in ("сильно", "очень", "невыносим", "умеренн", "легк", "тяжел"))
    has_temp = bool(re.search(r"(\d{2}(?:[.,]\d)?)\s*°?\s*c?", msg))
    has_actions_taken = any(k in msg for k in ("принял", "принимал", "пил", "выпил", "помог", "не помог", "already took"))
    asks_for_practical_help = any(
        k in msg
        for k in (
            "что делать",
            "как лечить",
            "как с этим бороться",
            "как убрать",
            "как снизить",
            "в чем причина",
            "в чём причина",
            "почему это",
            "почему так",
        )
    )
    if has_symptom and has_common_symptom and asks_for_practical_help:
        return True
    # Typical short complaints should not be forced into long question mode.
    if has_symptom and len(msg) >= 18:
        return True
    return has_symptom and (has_duration or has_severity or has_temp or has_actions_taken or asks_for_practical_help)


def _compact_problem_text(user_message: str, max_len: int = 220) -> str:
    txt = re.sub(r"\s+", " ", (user_message or "").strip())
    txt = re.sub(
        r"^(привет|здравствуйте|добрый день|доброе утро|добрый вечер|консультант|привет консультант)[,!\.\s]+",
        "",
        txt,
        flags=re.IGNORECASE,
    )
    return txt[:max_len] if txt else "Жалоба пока описана слишком кратко."


def _requests_more_questions(user_message: str) -> bool:
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return False
    patterns = (
        "задай",
        "задайте",
        "уточни",
        "уточните",
        "дополнительные вопросы",
        "уточняющие вопросы",
        "для более точного диагноза",
        "чтобы точнее",
        "по одному вопросу",
        "по одному",
    )
    return any(p in msg for p in patterns)


def _looks_like_meta_feedback(user_message: str) -> bool:
    """Meta feedback without new symptoms: keep previous medical context."""
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg or len(msg) > 180:
        return False
    if _requests_more_questions(msg):
        return True
    markers = (
        "недостаточно",
        "не по теме",
        "не подходит",
        "не то",
        "неправильно",
        "не могла бы",
        "по одному вопросу",
        "задавай по одному",
        "это не по теме",
        "понятно но",
        "я все понимаю",
        "я всё понимаю",
        "нерелевант",
        "не релевант",
    )
    if not any(m in msg for m in markers):
        return False
    return True


def _is_short_followup_ack(user_message: str) -> bool:
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return False
    if len(msg) > 40:
        return False
    acks = (
        "ок",
        "понял",
        "понятно",
        "спасибо",
        "ясно",
        "хорошо",
        "угу",
        "ага",
        "да",
        "нет",
        "дальше",
        "продолжай",
    )
    return msg in acks


def _looks_like_contextual_followup(user_message: str) -> bool:
    """
    Detect follow-up details that continue prior complaint without restating symptoms.
    Example: duration, what was tried, diet/lifestyle changes.
    """
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg or len(msg) > 260:
        return False
    markers = (
        "ничего не пробовал",
        "не пробовал",
        "не принимал",
        "не пил",
        "на протяжении",
        "уже",
        "месяц",
        "недел",
        "день",
        "давно",
        "после еды",
        "после приема пищи",
        "после приёма пищи",
        "поменял меню",
        "изменил меню",
        "поменял рацион",
        "изменил рацион",
        "ем больше",
        "ем меньше",
        "больше белк",
        "меньше жир",
        "стало хуже",
        "стало лучше",
        "не помогает",
        "помогает",
    )
    return any(m in msg for m in markers)


def _is_medical_complaint_like(text: str) -> bool:
    msg = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not msg:
        return False
    intent = (extract_symptoms_nutrition_activity_intent(msg).get("intent") or "general")
    if intent != "general":
        return True
    complaint_keys = (
        "бол",
        "темпера",
        "кашл",
        "горл",
        "насморк",
        "сопл",
        "одыш",
        "хрип",
        "вздут",
        "метеор",
        "газообраз",
        "газов",
        "пука",
        "пуч",
        "изжог",
        "запор",
        "диаре",
        "понос",
        "тошнот",
        "рвот",
        "давлен",
        "головн",
        "живот",
        "кишеч",
        "жжет",
        "жжёт",
        "мочеисп",
        "выделен",
        "отек",
        "отёк",
        "сып",
        "зуд",
        "зуб",
        "десн",
        "десна",
        "пародонт",
        "пародонтит",
        "пародонтоз",
        "полости рта",
    )
    return any(k in msg for k in complaint_keys)


def _is_strict_protocol_relevant(user_message: str, strict_protocol: Optional[dict[str, Any]]) -> bool:
    """
    Релевантность протокола для точной диагностики: не «включить/выключить по желанию»,
    а соответствие контексту жалобы.
    """
    sp = strict_protocol if isinstance(strict_protocol, dict) else {}
    if not sp:
        return False
    msg_low = (user_message or "").lower()
    words = set(re.findall(r"[а-яёa-z0-9]+", msg_low))
    words = {w for w in words if len(w) >= 3}
    if not words:
        return False
    title = str(sp.get("title") or "").lower()
    diagnosis = str(sp.get("diagnosis") or "").lower()
    conclusion = str(sp.get("conclusion") or "").lower()
    keywords = [str(x).lower() for x in (sp.get("keywords") or []) if str(x).strip()]
    hay = " ".join([title, diagnosis, " ".join(keywords)])

    food_discomfort = any(
        k in msg_low
        for k in (
            "семечк",
            "подсолнечник",
            "непереносимость",
            "плохо после",
            "поел ",
            "поела ",
            "съел ",
            "съела ",
            "лёгкая тошнота",
            "лёгкое тошнота",
            "плохое самочувствие",
            "ухудшилось самочувствие",
        )
    )
    acute_pain_mentioned = any(k in msg_low for k in ("острая боль", "кинжальн", "сильная боль в животе", "острую боль"))
    treatment_text = " ".join([str(x) for x in (sp.get("treatment") or [])]).lower()
    is_acute_protocol = (
        "гельминтоз" in title
        or "гельминтоз" in diagnosis
        or ("боль в животе" in title and ("острая боль" in conclusion or "кинжальн" in conclusion))
        or ("острая боль" in treatment_text or "не есть при острой" in treatment_text or "обезболивающ" in treatment_text)
    )
    if food_discomfort and not acute_pain_mentioned and is_acute_protocol:
        return False

    has_food_trigger = any(
        k in msg_low
        for k in (
            "съел ",
            "поел ",
            "поела ",
            "съела ",
            "после еды",
            "после того как",
            "жирн",
            "свинин",
            "жирная ",
            "жирное",
            "переел",
        )
    )
    has_abdominal_after_food = has_food_trigger and any(k in msg_low for k in ("живот", "желудок", "в животе"))
    has_urinary_symptoms = any(
        k in msg_low
        for k in (
            "мочеиспускание",
            "мочиться",
            "больно мочиться",
            "резь при",
            "частые позывы",
            "туалет по-маленькому",
            "цистит",
            "моча",
            "поясница и моча",
        )
    )
    is_urinary_protocol = (
        "цистит" in title
        or "цистит" in diagnosis
        or "мочевой" in hay
        or "моча" in hay
        or "мочев" in hay
        or "почки" in title
        or "почки" in diagnosis
        or "почк" in hay
    )
    if has_abdominal_after_food and not has_urinary_symptoms and is_urinary_protocol:
        return False

    hit = sum(1 for w in words if w in hay)
    ratio = hit / max(len(words), 1)
    if hit < 2 and ratio < 0.34:
        return False

    has_gi_context = any(
        k in msg_low
        for k in ("вздут", "метеор", "газообраз", "газы", "газов", "пуч", "пук", "живот", "кишеч", "изжог", "рефлюкс", "запор", "диаре", "понос")
    )
    if has_gi_context:
        gi_hints = ("вздут", "метеор", "газ", "пуч", "пук", "жкт", "гастро", "живот", "кишеч", "рефлюкс", "изжог", "запор", "диаре", "понос")
        if not any(h in hay for h in gi_hints):
            return False
        # For isolated gas complaints without alarming context, reject aggressive gastro protocols.
        has_gi_gas_only = any(k in msg_low for k in ("пуч", "пука", "газ", "метеор", "вздут"))
        no_alarm = not any(k in msg_low for k in ("сильная боль", "кров", "чёрный стул", "черный стул", "похуд", "темпера", "лихорад"))
        if has_gi_gas_only and no_alarm:
            aggressive = ("h. pylori", "узи", "омепразол", "ребамипид", "дротаверин")
            protocol_blob = " ".join(
                [
                    title,
                    diagnosis,
                    conclusion,
                    " ".join([str(x).lower() for x in (sp.get("diagnostics") or [])]),
                    " ".join([str(x).lower() for x in (sp.get("treatment") or [])]),
                    " ".join([str(x).lower() for x in (sp.get("medications_recommended") or [])]),
                ]
            )
            if any(a in protocol_blob for a in aggressive):
                return False
    return True


def _has_explicit_topic_switch(user_message: str) -> bool:
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return False
    markers = (
        "другой вопрос",
        "новый вопрос",
        "сменим тему",
        "другая тема",
        "теперь другой вопрос",
        "теперь про",
        "а теперь",
        "следующий вопрос",
    )
    return any(m in msg for m in markers)


def _looks_like_assistant_echo_message(user_message: str) -> bool:
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return False
    markers = (
        "кратко по справочнику",
        "проблема:",
        "почему:",
        "что делать сегодня",
        "когда срочно",
        "информация носит справочный характер",
        "понимаю вас. сейчас данных маловато",
        "что беспокоит, как давно",
    )
    matched = sum(1 for m in markers if m in msg)
    return matched >= 2 or msg.startswith("кратко по справочнику")


def _resolve_effective_user_message(user_message: str, chat_history: list) -> str:
    """Use previous medical complaint when current turn is only feedback."""
    msg = (user_message or "").strip()
    if _has_explicit_topic_switch(msg):
        return msg
    intent_now = (extract_symptoms_nutrition_activity_intent(msg).get("intent") or "general")
    contextual_followup = _looks_like_contextual_followup(msg)
    keep_previous_context = (
        _looks_like_meta_feedback(msg)
        or _is_short_followup_ack(msg)
        or contextual_followup
    )
    if not keep_previous_context:
        return msg
    if contextual_followup:
        for item in reversed(chat_history or []):
            if (item or {}).get("role") != "user":
                continue
            candidate = ((item or {}).get("content") or "").strip()
            if not candidate or candidate == msg:
                continue
            if _is_medical_complaint_like(candidate) and not _looks_like_contextual_followup(candidate):
                return f"{candidate}. Дополнительно: {msg}"
    for item in reversed(chat_history or []):
        if (item or {}).get("role") != "user":
            continue
        candidate = ((item or {}).get("content") or "").strip()
        if not candidate:
            continue
        if candidate == msg:
            continue
        if _is_medical_complaint_like(candidate):
            if contextual_followup or intent_now == "general":
                return f"{candidate}. Дополнительно: {msg}"
            return candidate
    return msg


def _is_smalltalk_message(user_message: str) -> bool:
    """
    Detect non-medical greetings/chitchat to avoid accidental medical snippets.
    Не считать smalltalk длинные реплики и фразы вроде «понял» внутри жалобы на диалог.
    """
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return False
    # Короткое «привет как дела» + жалоба в той же фразе (часто голос склеивает) — не smalltalk.
    if any(
        k in msg
        for k in (
            "устал",
            "устав",
            "апат",
            "слабост",
            "не хоч",
            "ничего не хоч",
            "кроват",
            "вставать",
            "встать ",
            "тревог",
            "депресс",
            "выгорел",
            "жалоб",
            "симптом",
            "болит",
            "самочувств",
            "здоров",
        )
    ):
        return False
    if len(msg) > 52:
        return False
    if any(
        k in msg
        for k in (
            "бол",
            "темпера",
            "кашл",
            "горл",
            "давлен",
            "анализ",
            "сып",
            "зуд",
            "диагноз",
            "лечение",
            "препарат",
            "мокрот",
            "сопл",
            "одыш",
            "врач",
            "симптом",
            "говорил",
            "уже сказал",
            "бесконеч",
            "по кругу",
            "не в ту сторон",
            "дружище",
            "брат",
            "совсем",
            "консьерж",
            "михаил",
            "повторя",
            "пропис",
        )
    ):
        return False
    medical = extract_symptoms_nutrition_activity_intent(msg)
    if (medical.get("intent") or "general") != "general":
        return False
    smalltalk_tokens = (
        "привет",
        "здравств",
        "добрый день",
        "доброе утро",
        "добрый вечер",
        "как дела",
        "как ты",
        "чем занимаешься",
        "спасибо",
        "благодарю",
        "хорошо",
        "hello",
        "hi",
        "how are you",
        "thanks",
    )
    if msg in ("ок", "ок.", "да", "да.", "ну да"):
        return True
    return any(t in msg for t in smalltalk_tokens)


def _detect_emotion_state(user_message: str) -> str:
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return "calm"
    panic_keys = ("паник", "страшно", "умира", "задыха", "не хватает воздуха")
    anger_keys = ("бесит", "надоел", "отстань", "задолб", "злит")
    apathy_keys = ("нет сил", "ничего не хочется", "апат", "выгорел", "устал")
    motivation_keys = ("готов", "давай", "получилось", "лучше", "смогу")
    if any(k in msg for k in panic_keys):
        return "panic"
    if any(k in msg for k in anger_keys):
        return "anger"
    if any(k in msg for k in apathy_keys):
        return "apathy"
    if any(k in msg for k in motivation_keys):
        return "motivation"
    return "calm"


def _detect_resistance_level(user_message: str) -> int:
    msg = re.sub(r"\s+", " ", (user_message or "").strip().lower())
    if not msg:
        return 0
    if any(k in msg for k in ("не хочу анализы", "не буду сдавать", "не надо анализов", "отстань")):
        return 2
    if any(k in msg for k in ("не хочу", "надоело", "бесполезно", "не вижу смысла")):
        return 1
    return 0


def _build_runtime_orchestrator_state(user_message: str, chat_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    history = chat_history or []
    emotion = _detect_emotion_state(user_message)
    resistance = _detect_resistance_level(user_message)
    interrupt_count = 0
    for m in history[-12:]:
        if str((m or {}).get("role") or "").lower() != "user":
            continue
        c = str((m or {}).get("content") or "").lower()
        if any(k in c for k in ("подожди", "стоп", "перебива", "да подожди")):
            interrupt_count += 1
    soft_redirect_counter = 0
    for m in history[-8:]:
        if str((m or {}).get("role") or "").lower() != "user":
            continue
        c = str((m or {}).get("content") or "").lower()
        has_life_topic = any(k in c for k in ("работа", "муж", "жена", "начальник", "ссора", "семья"))
        has_med_topic = any(k in c for k in ("анализ", "симптом", "боль", "сон", "ферритин", "гемоглобин", "давление"))
        if has_life_topic and not has_med_topic:
            soft_redirect_counter += 1
    return {
        "emotion_state": emotion,
        "resistance_level": resistance,
        "interruption_count": interrupt_count,
        "soft_redirect_counter": soft_redirect_counter,
    }


def _is_msk_trauma_like(text: str) -> bool:
    msg = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not msg:
        return False
    has_region = any(k in msg for k in ("колен", "голеностоп", "лодыж", "плеч", "спин", "поясниц", "сустав"))
    has_mech_or_pain = any(
        k in msg
        for k in (
            "болит",
            "боль",
            "упал",
            "паден",
            "травм",
            "ушиб",
            "растяж",
            "подвернул",
            "не могу наступ",
            "распух",
            "трудно сгиб",
            "сквозняк",
            "просквоз",
        )
    )
    return has_region and has_mech_or_pain

import re
from typing import List, Dict, Any


# -------------------------------------------
# RED FLAG GUARD
# -------------------------------------------

RED_FLAG_KEYWORDS = [
    "сильная боль",
    "кровь в стуле",
    "черный стул",
    "потеря сознания",
    "острая боль",
    "непрекращающаяся рвота",
    "температура выше 39",
    "сильное обезвоживание",
]


def red_flag_guard(text: str) -> bool:
    """
    Проверяет наличие опасных симптомов.
    Если есть — triage = urgent
    """
    text = text.lower()

    for flag in RED_FLAG_KEYWORDS:
        if flag in text:
            return True

    return False


# -------------------------------------------
# CLINICAL PROFILE FILTER
# -------------------------------------------

CLINICAL_PROFILES = {
    "gastro": [
        "живот",
        "боль в животе",
        "тошнота",
        "рвота",
        "понос",
        "диарея",
        "изжога",
        "вздутие",
        "жкт",
        "желудок",
    ],
    "trauma": [
        "порез",
        "рана",
        "кровотечение",
        "травма",
        "ушиб",
    ],
    "cardio": [
        "сердце",
        "давление",
        "пульс",
        "боль в груди",
    ],
    "endocrine": [
        "сахар",
        "глюкоза",
        "диабет",
        "инсулин",
    ],
}


def detect_clinical_profile(symptoms: str) -> str:
    """
    Определяет профиль симптомов
    """
    symptoms = symptoms.lower()

    scores = {}

    for profile, keywords in CLINICAL_PROFILES.items():
        score = 0

        for k in keywords:
            if k in symptoms:
                score += 1

        scores[profile] = score

    best = max(scores, key=scores.get)

    if scores[best] == 0:
        return "general"

    return best


def clinical_profile_filter(
    protocols: List[Dict[str, Any]],
    symptom_text: str,
) -> List[Dict[str, Any]]:
    """
    Удаляет нерелевантные медицинские протоколы
    """

    profile = detect_clinical_profile(symptom_text)

    filtered = []

    for p in protocols:

        tags = p.get("tags", [])

        if profile == "general":
            filtered.append(p)
            continue

        if profile in tags:
            filtered.append(p)

    return filtered


# -------------------------------------------
# TRIAGE ENGINE
# -------------------------------------------


def triage(symptom_text: str) -> str:
    """
    Определяет срочность обращения
    """

    if red_flag_guard(symptom_text):
        return "urgent"

    mild_patterns = [
        "2 дня",
        "3 дня",
        "несколько дней",
        "легкая боль",
    ]

    for p in mild_patterns:
        if p in symptom_text.lower():
            return "routine"

    return "observe"

def _has_explicit_red_flag_content(text: str) -> bool:
    """
    Явные red flag признаки. Только они должны быстро вести в экстренный triage.
    """
    msg = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not msg:
        return False

    red_flag_phrases = (
        "сильная боль в груди",
        "боль в груди",
        "давит в груди",
        "жжение в груди",
        "не хватает воздуха",
        "трудно дышать",
        "сильная одышка",
        "одышка",
        "потерял сознание",
        "обморок",
        "судороги",
        "кровь в рвоте",
        "рвота с кровью",
        "кровь в стуле",
        "черный стул",
        "чёрный стул",
        "перекосило лицо",
        "не могу говорить",
        "онемела рука",
        "онемела нога",
        "сильная слабость с потерей сознания",
        "внезапная очень сильная головная боль",
        "самая сильная головная боль",
        "внезапно очень сильно заболела голова",
        "отек губ",
        "отёк губ",
        "отек языка",
        "отёк языка",
        "отек горла",
        "отёк горла",
        "свистящее дыхание",
    )

    if any(p in msg for p in red_flag_phrases):
        return True

    # Доп. числовой red flag для температуры
    if re.search(r"(39[.,]?[5-9]?|40[.,]?\d*)\s*°?\s*c?", msg):
        return True

    return False


def _should_run_red_flag_screening(user_message: str, quick_intent: str) -> bool:
    """
    Защита от ложных RED:
    - не запускаем red flag на smalltalk
    - не запускаем на слишком коротких/пустых фразах
    - запускаем на явных red flags
    - иначе только если сообщение вообще похоже на медицинскую жалобу
    """
    msg = re.sub(r"\s+", " ", (user_message or "").strip())
    if not msg:
        return False

    if len(msg) < 5:
        return False

    if _is_smalltalk_message(msg):
        return False

    if _has_explicit_red_flag_content(msg):
        return True

    if quick_intent != "general":
        return True

    return _is_medical_complaint_like(msg)

def _extract_action_lines(text: str, max_items: int = 4) -> list[str]:
    out = []
    seen: set[str] = set()
    for line in (text or "").split("\n"):
        s = line.strip(" -•\t")
        if len(s) < 8:
            continue
        low = s.lower()
        if any(k in low for k in ["анализ", "сдать", "пейте", "приним", "измер", "покой", "сон", "вода", "обратит", "наблюда"]):
            key = re.sub(r"[^а-яёa-z0-9 ]+", "", low)
            if key in seen:
                continue
            seen.add(key)
            out.append(s[:180])
        if len(out) >= max_items:
            break
    return out


def _sanitize_offtopic_medical_blocks(text: str, user_message: str) -> str:
    """Удаляет явно нерелевантные блоки (инородное тело, ожог) без контекста пользователя."""
    src = (text or "").strip()
    if not src:
        return ""
    user_low = (user_message or "").lower()
    has_choking_context = any(k in user_low for k in ("поперх", "подавил", "задыха", "инород", "удуш", "не могу дышать"))
    has_burn_context = any(k in user_low for k in ("ожог", "обжег", "обжёг", "обвар"))
    has_joint_context = any(k in user_low for k in ("сустав", "артрит", "артроз", "отек сустава", "скованность"))
    has_nutrition_context = any(k in user_low for k in ("питани", "рацион", "желез", "витамин", "дефицит", "еда"))
    has_gi_context = any(k in user_low for k in ("вздут", "метеор", "газообраз", "газы", "живот", "кишеч", "урчани", "пуч", "пук"))
    has_food_trigger_headache_context = (
        any(k in user_low for k in ("голов", "мигр", "цефал"))
        and any(k in user_low for k in ("после еды", "после", "после того", "после того как", "через"))
        and any(k in user_low for k in ("сыр", "творог", "молоко", "молоч", "вино", "шоколад", "йогурт", "кефир"))
    )
    has_respiratory_context = _respiratory_positive_present(user_low)
    has_fatigue_apathy_only = (
        any(
            k in user_low
            for k in (
                "устал",
                "усталый",
                "вял",
                "нет сил",
                "ничего не хочется",
                "апат",
                "слабос",
                "встать тяжело",
                "вставать тяжело",
                "тяжело вставать",
            )
        )
        and not has_respiratory_context
    )
    source_topics = detect_topics(user_message or "")
    conflict_topics = get_conflicting_topics(source_topics, min_hits=1)
    conflict_keywords = set()
    for ct in conflict_topics:
        for kw in topic_keywords(ct):
            conflict_keywords.add(kw)

    lines = []
    for line in src.splitlines():
        low = line.lower()
        if ("инород" in low or "поперх" in low or "удуш" in low) and not has_choking_context:
            continue
        if "ожог" in low and not has_burn_context:
            continue
        if any(k in low for k in ("сустав", "артрит", "артроз", "скованност")) and not has_joint_context:
            continue
        if any(k in low for k in ("дефицит железа", "витамин d", "часто вы едите", "рацион")) and not has_nutrition_context:
            continue
        if has_gi_context and any(k in low for k in ("головн", "кашл", "горл", "насморк", "сопл", "одыш", "давлен", "гипертенз")):
            continue
        # Mini-filter anti respiratory drift:
        # for "headache after food" keep neuro/food hypotheses and cut accidental ORVI/bronchitis branches.
        if has_food_trigger_headache_context and not has_respiratory_context and any(
            k in low
            for k in (
                "орви",
                "бронхит",
                "трахеит",
                "фарингит",
                "тонзиллит",
                "пневмон",
                "кашл",
                "мокрот",
                "насморк",
                "сопл",
                "горл",
                "простуд",
            )
        ):
            continue
        # Усталость/астения без признаков ОРВИ: режем «простудные» ветки из RAG/модели.
        if has_fatigue_apathy_only and any(
            k in low
            for k in (
                "орви",
                "бронхит",
                "трахеит",
                "фарингит",
                "тонзиллит",
                "пневмон",
                "кашл",
                "мокрот",
                "насморк",
                "сопл",
                "горл",
                "простуд",
                "инфекц верхних дыхат",
                "инфекция верхних дыхат",
            )
        ):
            continue
        if conflict_keywords and any(k in low for k in conflict_keywords):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = cleaned if cleaned else src
    return scrub_text_with_funnel(user_message, cleaned)


_ORDINALS_RU = ("Первое", "Второе", "Третье", "Четвёртое", "Пятое", "Шестое", "Седьмое", "Восьмое")


def _ordinal(i: int) -> str:
    return _ORDINALS_RU[i] if 0 <= i < len(_ORDINALS_RU) else str(i + 1) + "."


def _build_soft_continue_question(user_message: str) -> str:
    t = (user_message or "").lower()
    if any(k in t for k in ("скорая", "103", "неотлож", "очень плохо", "задыха", "сильная боль")):
        return "Если нужно, я могу помочь вызвать скорую помощь прямо сейчас."
    if any(k in t for k in ("анализ", "ферритин", "гемоглобин", "ттг", "витамин d", "лаборат")):
        return "Если хочешь, можем спокойно разобраться, какие анализы дадут больше ясности."
    if any(k in t for k in ("питани", "диет", "лишний вес", "вес", "аппетит")):
        return "Хочешь, я помогу составить план питания без жёстких диет?"
    if any(k in t for k in ("устал", "сон", "энерги", "подрост", "школ", "экзамен")):
        return "Хочешь, я помогу составить план по улучшению энергии и сна?"
    return "Если хочешь, могу составить подробный план на ближайшие дни."


def _ensure_soft_continue_question(text: str, user_message: str) -> str:
    body = str(text or "").strip()
    if not body:
        return body
    lower = body.lower()
    # If assistant already ended with a soft follow-up offer, keep as is.
    if any(
        marker in lower
        for marker in (
            "хочешь, я",
            "если хочешь",
            "если нужно, я могу",
            "могу составить",
        )
    ):
        return body
    return body + "\n" + _build_soft_continue_question(user_message)


def _format_max_relevance_answer(
    user_message: str,
    base_text: str,
    *,
    force_questions: bool,
    questions: list[str],
    clinical_profiles: list[dict[str, Any]] | None = None,
    profile: Optional[dict[str, Any]] = None,
    strict_protocol: Optional[dict[str, Any]] = None,
    complaint_protocol: Optional[dict[str, Any]] = None,
    chat_history: list[dict[str, Any]] | None = None,
) -> str:
    """
    Структура ответа: вывод → что делать (перечисление «Первое», «Второе»…) → когда срочно → источники (если есть) → дисклеймер.
    """
    dialog_low = _dialog_user_text_blob_lower(user_message or "", chat_history)
    base_text = _sanitize_offtopic_medical_blocks(base_text, dialog_low)
    filtered = re.sub(r"\s+", " ", (base_text or "").strip())
    why = filtered[:320] if filtered else "Пока данных маловато для точного вывода."
    urgent_line = "При нарастающей одышке, боли в груди, нарушении сознания, судорогах или резком ухудшении — обратитесь за помощью (103)."
    actions = _extract_action_lines(base_text, max_items=4)
    primary = (clinical_profiles or [None])[0] if clinical_profiles else None
    sources_line = ""

    if primary and not force_questions:
        profile_actions = list(primary.get("treatment") or [])[:2]
        profile_dx = list(primary.get("diagnostics") or [])[:2]
        profile_meds = list(primary.get("medications_recommended") or [])[:3]
        if profile_actions:
            actions = profile_actions + actions
        if profile_dx:
            actions.append("Диагностика для подтверждения: " + "; ".join(profile_dx))
        if profile_meds:
            actions.append("Лекарственные варианты (обсудить с врачом): " + ", ".join(profile_meds))

    if not actions:
        actions = [
            "Соберите недостающие данные по симптомам и динамике.",
            "При ухудшении состояния не откладывайте очный осмотр.",
        ]

    msg_low = dialog_low
    has_no_fever_context = _user_denies_fever(msg_low)
    has_fatigue_context = any(
        k in msg_low
        for k in (
            "устал",
            "усталый",
            "вял",
            "слаб",
            "нет сил",
            "разбит",
            "сонлив",
            "апат",
            "вставать не хочется",
            "ничего не хочется",
            "встать тяжело",
            "вставать тяжело",
            "тяжело вставать",
        )
    )
    has_food_overindulgence_context = any(
        k in msg_low for k in (
            "семечк", "переел", "переедание", "съел много", "съела много", "поел много", "поела много",
            "тошнит после еды", "плохое самочувствие после еды", "плохо после еды",
            "обожрался", "объелся", "300 грамм", "много съел", "жирное съел", "жареных семечек"
        )
    ) and any(k in msg_low for k in ("тошнит", "тошнот", "плохое самочувствие", "недомогание", "тяжесть", "общее недомогание"))
    has_food_trigger_headache_context = (
        any(k in msg_low for k in ("голов", "мигр", "цефал"))
        and any(k in msg_low for k in ("после еды", "после", "после того", "после того как", "через"))
        and any(
            k in msg_low
            for k in (
                "сыр",
                "творог",
                "молоко",
                "молоч",
                "вино",
                "шоколад",
                "ферментирован",
                "йогурт",
                "кефир",
            )
        )
    )
    has_cheese_trigger = any(k in msg_low for k in ("сыр", "пармезан", "чеддер", "рокфор"))
    has_cottage_trigger = any(k in msg_low for k in ("творог", "кисломолоч"))
    has_aged_cheese = any(k in msg_low for k in ("выдержан", "плеснев", "острый сыр", "пармезан", "чеддер", "рокфор"))
    has_migraine_features = (
        any(k in msg_low for k in ("тошнот", "тошнит"))
        and any(k in msg_low for k in ("светобоя", "свет раздражает", "пульсир", "мигр"))
    )
    has_allergy_urgent = any(k in msg_low for k in ("сып", "зуд", "отек", "отёк", "одыш", "удуш"))
    has_gi_gas_context = any(k in msg_low for k in ("вздут", "метеор", "газообраз", "газы", "пуч", "пук", "газов"))
    has_gi_any_context = any(k in msg_low for k in ("вздут", "метеор", "газообраз", "газы", "газов", "живот", "кишеч", "изжог", "рефлюкс", "запор", "диаре", "понос", "пуч", "пук"))
    has_back_pain_context = any(
        k in msg_low for k in ("болит спина", "боль в спине", "спину", "поясниц", "шея", "межлопат")
    )
    has_draft_trigger_context = any(
        k in msg_low for k in ("просквоз", "продуло", "сквозняк", "после холода", "замерз", "замёрз")
    )
    has_back_draft_context = has_back_pain_context and has_draft_trigger_context
    has_temp_context = bool(re.search(r"(\d{2}(?:[.,]\d)?)\s*°?\s*c?", msg_low)) or (
        (not has_no_fever_context) and any(k in msg_low for k in ("жар", "лихорад", "температ"))
    )
    has_reflux_context = any(k in msg_low for k in ("изжог", "рефлюкс", "гэрб", "горечь", "кислот"))
    has_constipation_context = any(k in msg_low for k in ("запор", "редкий стул", "твердый стул", "твёрдый стул"))
    has_diarrhea_context = any(k in msg_low for k in ("диаре", "понос", "жидкий стул", "частый стул"))
    gi_direct_help = has_gi_gas_context and any(
        k in msg_low for k in ("что делать", "что мне делать", "что принять", "как убрать", "как с этим бороться", "в чем причина", "в чём причина")
    )
    fatigue_no_fever_context = has_fatigue_context and has_no_fever_context and not has_reflux_context and not has_diarrhea_context

    complaint = complaint_protocol if isinstance(complaint_protocol, dict) else {}
    complaint_name = str(complaint.get("complaint") or complaint.get("name") or "").strip()
    complaint_causes = [
        str(x).strip()
        for x in (
            complaint.get("likely_causes")
            or complaint.get("top_hypotheses")
            or complaint.get("possible_conditions")
            or []
        )
        if str(x).strip()
    ]
    complaint_ask = [
        str(x).strip()
        for x in (
            complaint.get("must_ask_questions")
            or complaint.get("anamnesis_questions")
            or questions
            or []
        )
        if str(x).strip()
    ]
    complaint_steps = [
        str(x).strip()
        for x in (
            complaint.get("first_line_non_drug_steps")
            or complaint.get("treatment_basic")
            or complaint.get("nutrition_recommendations")
            or complaint.get("nutrition_advice")
            or []
        )
        if str(x).strip()
    ]
    complaint_red = [
        str(x).strip()
        for x in (complaint.get("red_flags_specific") or complaint.get("red_flags") or [])
        if str(x).strip()
    ]
    if complaint_name and not force_questions and not has_back_draft_context:
        default_knee_causes = [
            "перегрузка после бега или резкой нагрузки",
            "ушиб мягких тканей",
            "растяжение связок/сухожилий",
            "реактивное воспаление сустава (синовит)",
        ]
        has_knee_context = "колен" in complaint_name.lower()
        knee_trauma_context = has_knee_context and any(
            k in msg_low for k in ("упал", "паден", "удар", "ушиб", "трудно сгиб", "не могу согнуть")
        )
        trauma_knee_causes = [
            "ушиб коленного сустава",
            "повреждение мениска",
            "растяжение связок",
            "гемартроз",
        ]
        causes_pool = complaint_causes[:3] if complaint_causes else (default_knee_causes if has_knee_context else [])
        if knee_trauma_context:
            causes_pool = trauma_knee_causes
        if causes_pool:
            if knee_trauma_context:
                why_line = "Похоже, вы могли травмировать колено при падении. Чаще всего это: " + "; ".join(causes_pool) + "."
            else:
                why_line = f"{complaint_name} может быть по нескольким причинам: " + "; ".join(causes_pool) + "."
        else:
            why_line = "По описанию это похоже на частый и обычно неэкстренный сценарий."
        if knee_trauma_context:
            ask_text = "; ".join(
                [
                    "Есть ли отёк вокруг колена?",
                    "Можете ли вы полностью разогнуть ногу?",
                    "Есть ли щелчок или блокировка в суставе?",
                    "Больно ли наступать на ногу?",
                ]
            )
            steps_text = "; ".join(
                [
                    "покой и уменьшение нагрузки на колено",
                    "холод 15-20 минут 3-4 раза в день",
                    "держать ногу слегка приподнятой",
                ]
            )
        else:
            ask_text = "; ".join(complaint_ask[:3]) if complaint_ask else "достаточно ключевых данных, можно начать с безопасных шагов."
            steps_text = "; ".join((complaint_steps[:3] if complaint_steps else actions[:3]))
        urgent_text = "; ".join(complaint_red[:3]) if complaint_red else urgent_line
        return "\n".join(
            [
                "Похоже на: " + complaint_name,
                "Почему это возможно: " + why_line,
                "Что уточнить: " + ask_text,
                "Что можно сделать сейчас (что попробовать): " + (steps_text or "щадящий режим, питье, контроль динамики."),
                "Когда обратиться к врачу: " + urgent_text,
                DISCLAIMER_TEXT,
            ]
        )

    strict = strict_protocol if isinstance(strict_protocol, dict) else {}
    skip_strict_for_food = has_food_overindulgence_context or has_food_trigger_headache_context or has_gi_gas_context
    if strict and not force_questions and not skip_strict_for_food:
        dx = str(strict.get("diagnosis") or strict.get("title") or "").strip()
        conclusion = str(strict.get("conclusion") or "").strip()
        if any(x in dx.lower() for x in ("delivery for impact", "placeholder", "todo", "tbd")):
            dx = ""
        if any(x in conclusion.lower() for x in ("delivery for impact", "placeholder", "todo", "tbd")):
            conclusion = ""
        why_parts = []
        if dx:
            why_parts.append("Сейчас наиболее вероятный вариант: " + dx + ".")
        if conclusion:
            why_parts.append(conclusion)
        if why_parts:
            why = " ".join(why_parts)

        strict_actions: list[str] = []
        diagnostics = [str(x).strip() for x in (strict.get("diagnostics") or []) if str(x).strip()]
        treatment = [str(x).strip() for x in (strict.get("treatment") or []) if str(x).strip()]
        alternative = [str(x).strip() for x in (strict.get("alternative_treatment") or []) if str(x).strip()]
        meds = [str(x).strip() for x in (strict.get("medications_recommended") or []) if str(x).strip()]
        analogs = [str(x).strip() for x in (strict.get("medications_analogs") or []) if str(x).strip()]

        if diagnostics:
            strict_actions.append("Диагностика для подтверждения: " + "; ".join(diagnostics[:3]))
        if treatment:
            strict_actions.append("Основной подход к лечению: " + "; ".join(treatment[:3]))
        if alternative:
            strict_actions.append("Альтернативные/немедикаментозные методы: " + "; ".join(alternative[:2]))
        if meds:
            strict_actions.append("Рекомендованные препараты (обсудить с врачом): " + ", ".join(meds[:4]))
        if analogs:
            strict_actions.append("Возможные аналоги: " + ", ".join(analogs[:4]))
        if strict_actions:
            actions = strict_actions

        urgent_signs = [str(x).strip() for x in (strict.get("urgent_signs") or []) if str(x).strip()]
        if urgent_signs:
            urgent_line = "При " + "; ".join(urgent_signs[:3]) + " — обратитесь к врачу или 103."

    if has_back_draft_context and not force_questions:
        why = "После сквозняка мышцы спины часто спазмируются; без неврологических признаков это обычно неопасно."
        actions = [
            "Щадящий режим 24-48 часов: избегать резких наклонов и подъема тяжестей.",
            "Сухое тепло на область боли 15-20 минут 2-3 раза в день.",
            "Для местного облегчения можно гель с НПВП (например диклофенак/кетопрофен) по инструкции, если нет противопоказаний.",
            "Если выраженный спазм — мягкая мобилизация и аккуратная растяжка без усиления боли.",
            "Если за 2-3 дня не становится лучше, нужен очный осмотр врача.",
        ]
        urgent_line = (
            "Срочно к врачу при слабости/онемении в ноге, нарушении мочеиспускания или дефекации, "
            "лихорадке, травме, нарастающей ночной боли."
        )
    elif fatigue_no_fever_context and not force_questions:
        why = (
            "По описанию это больше похоже на синдром выраженной усталости/истощения без признаков острой инфекции. "
            "Частые причины: недосып и стресс, дефициты (железо, B12, витамин D), нарушения щитовидной железы, "
            "перегрузка и недостаточное восстановление."
        )
        actions = [
            "На ближайшие 3-5 дней: стабильный сон 7.5-9 часов, фиксированное время подъёма и отхода ко сну.",
            "Питание регулярно: белок в каждый приём пищи, достаточно воды, меньше сахара и позднего кофеина.",
            "Щадящая активность: спокойная ходьба 20-30 минут ежедневно вместо интенсивных тренировок.",
            "Полезно проверить базовые анализы: ОАК, ферритин, B12, ТТГ, витамин D, глюкоза.",
            "Если слабость нарастает или мешает базовой активности — очный осмотр терапевта в ближайшие дни.",
        ]
        urgent_line = (
            "Срочно 103/неотложка при обмороке, боли в груди, выраженной одышке, неврологических симптомах "
            "или резком ухудшении состояния."
        )
    elif has_food_trigger_headache_context and not force_questions:
        if has_allergy_urgent:
            why = (
                "Связь с продуктом есть, но сопутствующие признаки больше похожи на возможную аллергическую реакцию, "
                "а не на обычный пищевой триггер головной боли."
            )
            actions = [
                "Не употребляйте подозрительный продукт повторно до очной оценки врача.",
                "Зафиксируйте: какой продукт, через сколько начались симптомы, были ли сыпь/зуд/отек/одышка.",
                "Если симптомы повторяются, нужен очный разбор у врача-аллерголога/терапевта.",
            ]
            urgent_line = (
                "При нарастающем отеке лица/горла, одышке, свистящем дыхании или резком ухудшении — срочно 103."
            )
        elif has_cheese_trigger and not has_cottage_trigger:
            why = (
                "Это похоже на головную боль с пищевым триггером: для сыра чаще рассматриваются тирамин и гистамин, "
                "особенно при выдержанных или ферментированных сортах."
            )
            if has_aged_cheese:
                why += " Для выдержанных/плесневых сыров вероятность такого триггера выше."
            if has_migraine_features:
                why += " Сочетание с тошнотой и светочувствительностью больше похоже на мигренозную реакцию."
            actions = [
                "Ведите дневник: вид сыра, порция, через сколько началась боль, интенсивность (0-10), сопутствующие признаки.",
                "На 10-14 дней исключите подозрительные сорта сыра, затем оцените динамику.",
                "Проверьте повторяемость на другие триггеры: шоколад, красное вино, копчености, ферментированные продукты.",
                "Поддерживающе: достаточная гидратация, сон, меньше стресса и без переедания в день триггера.",
                "Если эпизоды повторяются — планово обсудите с неврологом/терапевтом.",
            ]
            urgent_line = (
                "Срочно 103 при внезапной очень сильной головной боли, нарушении речи/движений, онемении, "
                "потере сознания, судорогах, высокой температуре с сильной головной болью."
            )
        elif has_cottage_trigger and not has_cheese_trigger:
            why = (
                "По описанию это больше похоже на индивидуальную реакцию на молочный продукт "
                "или пищевую чувствительность, чем на типичный сценарий выдержанного сыра."
            )
            if has_migraine_features:
                why += " Но с учетом тошноты/светочувствительности возможен и мигренозный триггер."
            actions = [
                "Ведите дневник: творог/количество/время появления боли и сопутствующие признаки.",
                "На 1-2 недели исключите творог, затем оцените повторяемость симптома.",
                "Сравните реакцию на другие молочные продукты (молоко, кефир, йогурт), не вводя несколько новых тестов сразу.",
                "Следите за дополнительными триггерами: недосып, стресс, обезвоживание.",
                "Если головные боли становятся частыми или сильными — плановый очный разбор у врача.",
            ]
            urgent_line = (
                "Срочно 103 при внезапной очень сильной головной боли, неврологических симптомах "
                "(слабость, онемение, нарушение речи/зрения), потере сознания."
            )
        else:
            why = (
                "Это похоже на головную боль после еды с вероятным пищевым триггером. "
                "Чаще рассматриваются тирамин/гистамин, индивидуальная чувствительность и мигренозная реакция."
            )
            if has_migraine_features:
                why += " Симптомы с тошнотой и светочувствительностью усиливают вероятность мигренозного механизма."
            actions = [
                "Ведите дневник: продукт, объем, через сколько началась боль, интенсивность, сопутствующие признаки.",
                "На 1-2 недели исключите наиболее подозрительный триггер и оцените динамику.",
                "Проверьте, есть ли похожая реакция на шоколад, вино, копчености или ферментированные продукты.",
                "Снижайте фоновые триггеры: недосып, стресс, обезвоживание.",
                "При повторении приступов обратитесь к неврологу/терапевту для уточнения тактики.",
            ]
            urgent_line = (
                "Срочно 103 при внезапной очень сильной головной боли, нарушении речи/движений, "
                "онемении, потере сознания, судорогах, высокой температуре с сильной болью."
            )
    elif has_food_overindulgence_context and not force_questions:
        why = (
            "По симптомам: перегрузка ЖКТ из-за большого объёма или жирной пищи (например семечки). "
            "С точки зрения нутрициологии возможные механизмы: избыток жира — нагрузка на желчный пузырь и липазу, "
            "большой объём — растяжение желудка и замедление эвакуации, жареное масло — раздражение слизистой и окисленные жиры. "
            "Не инфекция и не опасное заболевание при отсутствии красных флагов."
        )
        actions = [
            "Покой желудку: 2–4 часа не есть, потом лёгкая пища небольшими порциями.",
            "Питьё: вода комнатной температуры, при тошноте — маленькими глотками.",
            "Ограничить жирное, жареное и объём пищи на 1–2 дня.",
            "На будущее: семечки лучше сырые или подсушенные, порция ~20–30 г, не на голодный желудок.",
            "При сохранении тошноты, рвоты, боли или ухудшении — очный осмотр врача.",
        ]
        urgent_line = "При ухудшении или тревожных признаках (неукротимая рвота, кровь, сильная боль, нарушение сознания) — обратитесь к врачу или 103."
        sources_line = (
            "Источники: клинические рекомендации по функциональной диспепсии и диетологии, "
            "принципы нутрициологии при перегрузке ЖКТ (жир, объём, щадящий режим)."
        )
    elif has_gi_gas_context and (not force_questions or gi_direct_help):
        why = (
            "Это похоже на функциональное вздутие/метеоризм: чаще связано с питанием, "
            "быстрым приемом пищи, непереносимостью отдельных продуктов или дисбалансом микробиоты."
        )
        actions = [
            "Похоже на ферментацию пищи: чаще провоцируют бобовые, часть молочных продуктов и избыток белка в одном приёме.",
            "На 10-14 дней уменьшите триггеры: фасоль/бобовые, кефир и другие молочные, большие белковые порции за раз.",
            "Ешьте медленнее, небольшими порциями; не сочетайте много бобовых и белка в один приём пищи.",
            "Ведите дневник: продукт, объём, через сколько появились газы/вздутие, что переносится лучше.",
            "Если выраженной боли и температуры нет, начинайте с питания и режима; лекарства без очной оценки не обязательны.",
        ]
        if any(k in msg_low for k in ("бол", "спазм", "запор", "диаре", "понос")):
            actions.append("Если есть боль, запор или диарея — нужен очный осмотр и базовые анализы кала/крови по назначению врача.")
        urgent_line = "При сильной боли, рвоте, крови в стуле, чёрном стуле или резком ухудшении — к врачу или 103."
    elif has_reflux_context and not force_questions:
        why = (
            "Это похоже на кислотозависимые симптомы (изжога/рефлюкс): "
            "часто связаны с перееданием, поздними приемами пищи, кофеином, жирной и острой едой."
        )
        actions = [
            "Ешьте небольшими порциями; не ложитесь 2-3 часа после еды, приподнимите изголовье на ночь.",
            "Ограничьте триггеры: жирное, острое, алкоголь, кофе, шоколад, газированные напитки.",
            "Контролируйте вес, избегайте тесной одежды в области живота.",
            "При частой изжоге обсудите с врачом курс антисекреторной терапии и план обследования.",
        ]
        if any(k in msg_low for k in ("боль при глотании", "похуд", "кров", "черный стул", "чёрный стул")):
            actions.append("При тревожных признаках (кровь, черный стул, похудение, боль при глотании) обратитесь к врачу срочно.")
        urgent_line = "При крови в стуле/рвоте, чёрном стуле, похудении или резком ухудшении — к врачу или 103."
    elif has_constipation_context and not force_questions:
        why = (
            "Это похоже на запор: нередко связан с нехваткой жидкости и клетчатки, "
            "малой физической активностью, стрессом или побочным действием препаратов."
        )
        actions = [
            "Пейте достаточно воды, увеличьте клетчатку постепенно (овощи, цельные крупы, псиллиум).",
            "Добавьте ежедневную ходьбу и привычку посещать туалет в одно и то же время без спешки.",
            "Сократите избыток крепкого чая/кофе и очень рафинированной пищи.",
            "Если стула нет более 3 дней или часто требуется слабительное — нужен очный разбор причин у врача.",
        ]
        if any(k in msg_low for k in ("кров", "сильн боль", "рвот", "похуд", "черный стул", "чёрный стул")):
            actions.append("При крови в стуле, выраженной боли, рвоте или похудении — срочно обратитесь за медицинской помощью.")
        urgent_line = "При крови в стуле, выраженной боли, рвоте или резком ухудшении — к врачу или 103."
    elif has_diarrhea_context and not force_questions:
        why = (
            "Это похоже на диарею: чаще вызвана кишечной инфекцией, пищевой реакцией, "
            "лекарствами или функциональными нарушениями ЖКТ."
        )
        actions = [
            "Главное сейчас — регидратация: пейте воду/растворы для восполнения жидкости небольшими порциями.",
            "На 1-2 дня щадящее питание (рис, банан, сухари, нежирные блюда), исключите молочное, жирное и алкоголь.",
            "Оцените частоту стула и признаки обезвоживания (сухость во рту, редкое мочеиспускание, слабость).",
            "Если диарея сохраняется более 48-72 часов, нужна очная консультация и анализы по назначению врача.",
        ]
        if any(k in msg_low for k in ("кров", "высокая температура", "39", "сильная слабость", "обезвож")):
            actions.append("При крови в стуле, высокой температуре или признаках обезвоживания обратитесь за помощью срочно.")
        urgent_line = "При крови в стуле, обезвоживании, высокой температуре или резком ухудшении — к врачу или 103."

    if has_gi_any_context and not has_temp_context:
        actions = [a for a in actions if not any(k in (a or "").lower() for k in ("температ", "жар", "лихорад"))]

    p = profile or {}
    allergies = [str(x).strip() for x in (p.get("allergies") or []) if str(x).strip()]
    chronic = [str(x).strip() for x in (p.get("chronic_conditions") or []) if str(x).strip()]
    family = str(p.get("family_history") or "").strip()
    if allergies:
        actions.append("При выборе препаратов учитывать аллергии: " + ", ".join(allergies))
    if chronic:
        actions.append("Сверять лечение с хроническими заболеваниями: " + ", ".join(chronic))
    if family:
        actions.append("Учитывать семейный анамнез в диагностических выводах.")

    has_high_temp = bool(re.search(r"(39|40)(?:[.,]\d)?\s*°?\s*c?", msg_low))
    has_respiratory = _respiratory_positive_present(msg_low)
    has_choking_context = any(k in msg_low for k in ("поперх", "подавил", "задыха", "инород", "удуш"))
    if has_high_temp and has_respiratory and not has_choking_context:
        why = "По описанию это больше похоже на острое инфекционное состояние, а не на инородное тело дыхательных путей."
    if has_no_fever_context and "воспал" in (why or "").lower():
        why = (
            "По текущим данным без температуры это менее похоже на острый воспалительный процесс; "
            "нужен акцент на восстановление, дефициты и метаболические причины."
        )

    if force_questions and questions:
        why = "Чтобы не ошибиться, нужно уточнить несколько деталей."
    if force_questions and strict and not questions:
        anamnesis = [str(x).strip() for x in (strict.get("anamnesis") or []) if str(x).strip()]
        if anamnesis:
           questions = [anamnesis[0]]

    intro_phrase = "Коротко уточню самое важное:"
    hypotheses_parts: list[str] = []
    if strict and not has_back_draft_context:
        dx = str(strict.get("diagnosis") or strict.get("title") or "").strip()
        if dx and not any(x in dx.lower() for x in ("delivery for impact", "placeholder", "todo", "tbd")):
            hypotheses_parts.append(dx)
    for cp in ([] if has_back_draft_context else (clinical_profiles or [])[:3]):
        name = str(cp.get("name") or cp.get("diagnosis") or cp.get("title") or "").strip()
        if name and (not any(x in name.lower() for x in ("delivery for impact", "placeholder", "todo", "tbd"))) and name not in hypotheses_parts:
            hypotheses_parts.append(name)

    hypotheses_line = ""
    if hypotheses_parts:
        hypotheses_line = "Что сейчас выглядит наиболее вероятно: " + ", ".join(hypotheses_parts[:3]) + "."

    # Убрать повторение «по симптомам» после заголовка (первый пункт не начинаем с «По симптомам:»)
    first_bullet = (why or "").strip()
    if has_back_draft_context and not force_questions:
        first_bullet = "мышечно-тоническая боль спины после переохлаждения (мышечный спазм)"
    first_bullet = re.sub(
        r"^\s*по\s+симптомам(?:\s+это)?\s*[:\-—]?\s*",
        "",
        first_bullet,
        flags=re.IGNORECASE,
    ).strip() or first_bullet

    if not force_questions:
        short_actions: list[str] = []
        for a in actions[:4]:
            clean_a = re.sub(
                r"^\s*(первое|второе|третье|четв[её]ртое|пятое|шестое|седьмое|восьмое|\d+[\.\)])\s*[\.\:\-\)]*\s*",
                "",
                str(a or ""),
                flags=re.IGNORECASE,
            ).strip() or str(a or "").strip()
            if clean_a:
                short_actions.append(clean_a)
        short_questions = [str(q or "").strip() for q in questions[:3] if str(q or "").strip()]
        if has_back_draft_context and short_questions:
            short_questions = short_questions[:1]
        lines = [
            "Похоже на: " + first_bullet,
            "Почему: " + (hypotheses_line.replace("Что сейчас выглядит наиболее вероятно: ", "").strip(". ") if hypotheses_line else why),
            "Что уточнить: " + ("; ".join(short_questions) if short_questions else "Пока достаточно данных, можно начать с безопасных шагов."),
            "Что можно сделать сейчас (что попробовать): " + ("; ".join(short_actions) if short_actions else "Наблюдать динамику и щадящий режим."),
            "Когда к врачу: " + urgent_line,
        ]
        out = "\n".join(lines)
        out = _ensure_soft_continue_question(out, user_message)
        return out + "\n" + DISCLAIMER_TEXT

    lines = ["Похоже на: " + first_bullet, "Что уточнить: " + intro_phrase]
    if hypotheses_line:
        lines.append("Почему: " + hypotheses_line.replace("Что сейчас выглядит наиболее вероятно: ", "").strip())
    for i, q in enumerate(questions[:MAX_QUESTIONS_PER_TURN]):
        lines.append("- " + q)
    lines.append("Когда к врачу: " + urgent_line)
    if sources_line:
        lines.append(sources_line)
    lines.append(DISCLAIMER_TEXT)
    return "\n".join(lines)


def _humanize_offline_answer(
    user_message: str,
    offline_formats: dict[str, Any],
    chat_history: list,
    has_lab_data: bool,
) -> tuple[str, str]:
    """
    Делает офлайн-ответ менее роботизированным:
    - короткое человеческое вступление
    - релевантная выжимка из simple-формата
    - 1-3 уточняющих вопроса при нехватке данных
    """
    simple = (offline_formats.get("simple") or "").strip()
    professional = (offline_formats.get("professional") or "").strip()
    base = _relevant_simple_snippet(simple, user_message) if simple else professional
    if base:
        base = re.sub(r"\s+", " ", base).strip()
    questions = suggest_clarifying_questions(
        user_message=user_message or "",
        chat_history=chat_history or [],
        has_lab_data=bool(has_lab_data),
        max_questions=MAX_QUESTIONS_PER_TURN,
    )
    if not base and not professional:
        text = "Понимаю вас. Чтобы ответ был точным и полезным, мне нужно немного уточнений."
    else:
        doctor_like = _build_doctor_like_offline_reply(user_message, simple, professional)
        text = "Понимаю, это неприятно.\n" + doctor_like
    if questions:
        text += "\n\nЧтобы ответить точнее, уточните, пожалуйста:\n- " + "\n- ".join(questions)
    text += "\n\n" + DISCLAIMER_TEXT
    simple_out = (simple[:400] if simple else text[:400]).strip()
    return text, simple_out


async def run_dialog_companion_turn(
    user_message: str,
    chat_history: Optional[list],
) -> dict[str, Any]:
    """
    Свободный диалог «рядом» с медконсультацией: без JSON-схемы клиники.
    При отсутствии LLM или ошибке вызывающая сторона может подставить офлайн-тексты.
    """
    out: dict[str, Any] = {
        "response": "",
        "llm_used": False,
        "model_used": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "error": None,
    }
    um = str(user_message or "").strip()
    if not um:
        out["error"] = "empty_message"
        return out
    settings = get_settings()
    hist = chat_history or []
    msgs: list[dict[str, str]] = []
    for row in hist[-12:]:
        if not isinstance(row, dict):
            continue
        role_raw = str(row.get("role") or "").strip().lower()
        if role_raw not in ("user", "assistant"):
            continue
        c = str(row.get("content") or "").strip()
        if not c:
            continue
        role_oai = "user" if role_raw == "user" else "assistant"
        msgs.append({"role": role_oai, "content": c[:1600]})
    system_text = (
        "Ты дружелюбный русскоязычный собеседник в приложении про здоровый образ жизни. "
        "Не ставь диагнозы, не назначай лечение и не подбирай дозы препаратов. "
        "Если пользователь задаёт явно медицинский вопрос (симптомы, анализы, лечение болезни) — ответь очень кратко "
        "и мягко предложи описать симптомы как в медицинской консультации этого приложения; не уходи в длинную клинику. "
        "Иначе поддерживай живой разговор по теме пользователя: можно шутить уместно и обсуждать бытовые темы. "
        "Ответ компактный, до примерно 1600 символов."
    )
    messages_payload = [{"role": "system", "content": system_text}] + msgs + [{"role": "user", "content": um[:2400]}]

    try:
        if settings.llm_worker_url:
            import httpx

            url = f"{str(settings.llm_worker_url).rstrip('/')}/chat/completions"
            async with httpx.AsyncClient(timeout=75.0) as client:
                r = await client.post(
                    url,
                    json={
                        "messages": messages_payload,
                        "model": settings.openai_model,
                        "temperature": 0.75,
                        "max_tokens": 750,
                    },
                )
                r.raise_for_status()
                raw_json = r.json()
                data = raw_json if isinstance(raw_json, dict) else {}
                text = str(data.get("content") or "").strip()
                out["response"] = text
                out["llm_used"] = bool(text)
                out["model_used"] = data.get("model") or settings.openai_model
                out["prompt_tokens"] = int(data.get("prompt_tokens") or 0)
                out["completion_tokens"] = int(data.get("completion_tokens") or 0)
                out["total_tokens"] = int(data.get("total_tokens") or 0)
                out["estimated_cost_usd"] = _estimate_openai_cost_usd(
                    str(out["model_used"] or ""),
                    out["prompt_tokens"],
                    out["completion_tokens"],
                )
                return out

        if settings.openai_api_key:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages_payload,
                temperature=0.75,
                max_tokens=750,
            )
            text = str(resp.choices[0].message.content or "").strip()
            out["response"] = text
            out["llm_used"] = bool(text)
            out["model_used"] = settings.openai_model
            usage = getattr(resp, "usage", None)
            out["prompt_tokens"] = int(getattr(usage, "prompt_tokens", 0) or 0)
            out["completion_tokens"] = int(getattr(usage, "completion_tokens", 0) or 0)
            out["total_tokens"] = int(getattr(usage, "total_tokens", 0) or 0)
            out["estimated_cost_usd"] = _estimate_openai_cost_usd(
                str(out["model_used"] or ""),
                out["prompt_tokens"],
                out["completion_tokens"],
            )
            return out
    except Exception as exc:
        logging.getLogger(__name__).warning("run_dialog_companion_turn failed: %s", exc)
        out["error"] = str(exc)
        return out

    out["error"] = "no_llm_configured"
    return out


async def run_consultation_turn(
    user_id: str,
    user_message: str,
    profile: dict,
    documents_count: int,
    symptom_entries: list,
    chat_history: list,
    app_mode: Optional[str] = None,
    vitals: Optional[dict] = None,
    document_context: Optional[str] = None,
    subject_id: Optional[str] = None,
    consultation_mode_hint: Optional[str] = None,
) -> dict[str, Any]:
    t0 = time.monotonic()
    medical_core_guidance_context: dict[str, Any] = {}
    selector_result: SelectorResult | None = None
    selector_payload: dict[str, Any] = {}
    selector_question: str = ""
    followup_state_obj: FollowupState = FollowupState()
    followup_decision_payload: dict[str, Any] = {}
    case_shift_candidate: bool = False
    confidence_gate_payload: dict[str, Any] = {}
    confidence_state_overlay: dict[str, Any] = {}
    followup_ready_for_summary: bool = False
    runtime_orchestrator_state: dict[str, Any] = {}

    def _result(
        *,
        response: str,
        response_simple: Optional[str] = None,
        conclusion: bool = False,
        report_id: Optional[str] = None,
        report: Optional[dict[str, Any]] = None,
        suggest_pdf: bool = False,
        severity: str = "YELLOW",
        red_flags_present: bool = False,
        red_flag_matches: Optional[list[str]] = None,
        structured: Optional[dict[str, Any]] = None,
        llm_used: bool = False,
        response_source: str = "app_guard",
        model_used: Optional[str] = None,
        worker_used: bool = False,
        request_id: Optional[str] = None,
        orchestrator_state: Optional[dict[str, Any]] = None,
        consultation_case: Optional[dict[str, Any]] = None,
        prompt_chars: int = 0,
        response_chars: int = 0,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        symptom_context_data: Optional[dict[str, Any]] = None,
        nutrition_context: Optional[dict[str, Any]] = None,
        lab_context_data: Optional[dict[str, Any]] = None,
        mikhail_state: Optional[str] = None,
        mikhail_urgency: Optional[str] = None,
        mikhail_questions: Optional[list[str]] = None,
        mikhail_recommended_labs: Optional[list[str]] = None,
        mikhail_hypotheses: Optional[list[str]] = None,
        mikhail_final_message: Optional[str] = None,
        mikhail_debug: Optional[dict[str, Any]] = None,
        user_report_structured: Optional[dict[str, Any]] = None,
        continuity_summary: Optional[dict[str, Any]] = None,
        care_plan: Optional[dict[str, Any]] = None,
        care_plan_message: Optional[str] = None,
        physician_report: Optional[dict[str, Any]] = None,
        physician_report_text: Optional[str] = None,
        product: Optional[dict[str, Any]] = None,
        launch: Optional[dict[str, Any]] = None,
        onboarding: Optional[dict[str, Any]] = None,
        conversion: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        structured_enriched = structured
        if isinstance(structured, dict) and medical_core_guidance_context:
            try:
                structured_enriched = apply_medical_core_guidance(
                    structured,
                    medical_core_guidance_context,
                    user_message=user_message or "",
                )
            except Exception:
                structured_enriched = structured

        if isinstance(structured_enriched, dict) and selector_payload.get("matched"):
            structured_enriched = dict(structured_enriched)
            structured_enriched["medical_core_selector"] = dict(selector_payload)
            if not structured_enriched.get("triage_target") and selector_payload.get("triage_target"):
                structured_enriched["triage_target"] = selector_payload.get("triage_target")
            if not structured_enriched.get("specialist_route") and selector_payload.get("specialist"):
                structured_enriched["specialist_route"] = selector_payload.get("specialist")
            if not structured_enriched.get("recommended_labs") and selector_payload.get("tests"):
                structured_enriched["recommended_labs"] = list(selector_payload.get("tests") or [])
            if not structured_enriched.get("nutrition_advice") and selector_payload.get("nutrition"):
                structured_enriched["nutrition_advice"] = list(selector_payload.get("nutrition") or [])
            if not structured_enriched.get("activity_advice") and selector_payload.get("activity"):
                structured_enriched["activity_advice"] = list(selector_payload.get("activity") or [])
            if not structured_enriched.get("follow_up_questions") and selector_payload.get("best_question"):
                structured_enriched["follow_up_questions"] = [str(selector_payload.get("best_question")).strip()]
        if isinstance(structured_enriched, dict):
            if followup_decision_payload:
                structured_enriched["medical_core_followup"] = dict(followup_decision_payload)
            elif followup_state_obj:
                structured_enriched["medical_core_followup"] = {
                    "action": "state",
                    "followup_state": followup_state_obj.to_dict(),
                }
            if case_shift_candidate:
                structured_enriched["case_shift_candidate"] = True
            if confidence_gate_payload:
                structured_enriched["confidence_gate"] = dict(confidence_gate_payload)
            if followup_ready_for_summary:
                structured_enriched["followup_ready_for_summary"] = True
            if runtime_orchestrator_state:
                structured_enriched["runtime_orchestrator_state"] = dict(runtime_orchestrator_state)

        orchestrator_state_enriched = orchestrator_state
        if selector_payload.get("matched"):
            try:
                orchestrator_state_enriched = attach_selector_state(orchestrator_state_enriched, selector_payload)
            except Exception:
                orchestrator_state_enriched = orchestrator_state
        try:
            orchestrator_state_enriched = attach_followup_state(orchestrator_state_enriched, followup_state_obj)
        except Exception:
            pass
        if confidence_state_overlay:
            try:
                merged = dict(orchestrator_state_enriched or {})
                merged.update(confidence_state_overlay)
                orchestrator_state_enriched = merged
            except Exception:
                pass

        out = {
            "response": response,
            "response_simple": response_simple,
            "conclusion": conclusion,
            "report_id": report_id,
            "report": report,
            "suggest_pdf": suggest_pdf,
            "severity": severity,
            "red_flags_present": red_flags_present,
            "red_flag_matches": red_flag_matches or [],
            "structured": structured_enriched,
            "llm_used": llm_used,
            "response_source": response_source,
            "model_used": model_used,
            "worker_used": worker_used,
            "request_id": request_id,
            "orchestrator_state": orchestrator_state_enriched,
            "runtime_orchestrator_state": dict(runtime_orchestrator_state),
            "consultation_case": consultation_case,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "symptom_context_data": symptom_context_data or {},
            "nutrition_context": nutrition_context or {},
            "lab_context_data": lab_context_data or {},
        }
        if mikhail_state is not None:
            out["state"] = mikhail_state
        if mikhail_urgency is not None:
            out["urgency"] = mikhail_urgency
        if mikhail_questions is not None:
            out["questions"] = mikhail_questions
        if mikhail_recommended_labs is not None:
            out["recommended_labs"] = mikhail_recommended_labs
        if mikhail_hypotheses is not None:
            out["user_hypotheses"] = mikhail_hypotheses
        if mikhail_final_message is not None:
            out["final_user_message"] = mikhail_final_message
        if mikhail_debug is not None:
            out["debug"] = mikhail_debug
        if user_report_structured is not None:
            out["user_report_structured"] = user_report_structured
        if continuity_summary is not None:
            out["continuity_summary"] = continuity_summary
        if care_plan is not None:
            out["care_plan"] = care_plan
        if care_plan_message is not None:
            out["care_plan_message"] = care_plan_message
        if physician_report is not None:
            out["physician_report"] = physician_report
        if physician_report_text is not None:
            out["physician_report_text"] = physician_report_text
        if product is not None:
            out["product"] = product
        if launch is not None:
            out["launch"] = launch
        if onboarding is not None:
            out["onboarding"] = onboarding
        if conversion is not None:
            out["conversion"] = conversion
        return out

    if _looks_like_assistant_echo_message(user_message):
        await _ensure_min_delay(t0)
        response = (
            "Похоже, в распознавание попал текст моего прошлого ответа. "
            "Скажите, пожалуйста, ваш новый вопрос коротко и своими словами.\n"
            + DISCLAIMER_TEXT
        )
        return _result(
            response=response,
            response_simple="Повторите, пожалуйста, новый вопрос коротко своими словами.",
            structured=_build_structured_payload(
                response_text=response,
                response_simple="Повторите, пожалуйста, новый вопрос коротко своими словами.",
                effective_user_message=user_message,
                severity="YELLOW",
                red_flags_present=False,
                follow_up_questions=[],
                clinical_profiles=[],
                symptom_context={},
                nutrition_context={},
                lab_context={},
            ),
            response_source="app_guard",
        )

    effective_user_message = _resolve_effective_user_message(user_message, chat_history)
    if _is_smalltalk_message(effective_user_message):
        quick = "Спасибо, всё хорошо. Я на связи и готов помочь по здоровью, когда будет медицинский вопрос."
        await _ensure_min_delay(t0, 0.25)
        return _result(
            response=quick + "\n" + DISCLAIMER_TEXT,
            response_simple=quick,
            structured=_build_structured_payload(
                response_text=quick,
                response_simple=quick,
                effective_user_message=effective_user_message,
                severity="GREEN",
                red_flags_present=False,
                follow_up_questions=[],
                clinical_profiles=[],
                symptom_context={},
                nutrition_context={},
                lab_context={},
            ),
            response_source="small_talk_hard_bypass",
            llm_used=False,
        )
    runtime_orchestrator_state = _build_runtime_orchestrator_state(effective_user_message, chat_history)
    conversation_prefs = get_mikhail_conversation_prefs(user_id)

    msg_low_pref = (effective_user_message or "").lower()
    requested_style = None
    if any(k in msg_low_pref for k in ("будь мягче", "помягче", "не дави", "без давления")):
        requested_style = "soft"
    elif any(k in msg_low_pref for k in ("будь прямее", "жестче", "пожестче", "мотивируй жестче")):
        requested_style = "direct"
    if requested_style and requested_style != conversation_prefs.get("preferred_style"):
        try:
            conversation_prefs = save_mikhail_conversation_prefs(
                user_id,
                {
                    "preferred_style": requested_style,
                    "updated_at": str(int(time.time())),
                    "signals": {
                        "emotion_state": runtime_orchestrator_state.get("emotion_state"),
                        "resistance_level": runtime_orchestrator_state.get("resistance_level"),
                    },
                },
            )
        except Exception:
            pass
    elif runtime_orchestrator_state.get("resistance_level", 0) >= 2 and conversation_prefs.get("preferred_style") != "soft":
        # При выраженном сопротивлении по умолчанию переключаемся на более мягкий стиль.
        try:
            conversation_prefs = save_mikhail_conversation_prefs(
                user_id,
                {
                    "preferred_style": "soft",
                    "updated_at": str(int(time.time())),
                    "signals": {
                        "emotion_state": runtime_orchestrator_state.get("emotion_state"),
                        "resistance_level": runtime_orchestrator_state.get("resistance_level"),
                    },
                },
            )
        except Exception:
            pass

    if _is_audio_check_phrase(effective_user_message):
        quick = "Слышу хорошо. Можете описать симптом или вопрос по здоровью."
        await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, quick))
        return _result(
            response=quick + "\n" + DISCLAIMER_TEXT,
            response_simple=quick,
            structured=_build_structured_payload(
                response_text=quick,
                response_simple=quick,
                effective_user_message=effective_user_message,
                severity="GREEN",
                red_flags_present=False,
                follow_up_questions=[],
                clinical_profiles=[],
                symptom_context={},
                nutrition_context={},
                lab_context={},
            ),
            response_source="audio_check_guard",
            llm_used=False,
        )

    if _is_periodontal_query(effective_user_message):
        quick = _periodontal_quick_response()
        await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, quick))
        return _result(
            response=quick + "\n\n" + DISCLAIMER_TEXT,
            response_simple=quick,
            structured=_build_structured_payload(
                response_text=quick,
                response_simple=quick,
                effective_user_message=effective_user_message,
                severity="YELLOW",
                red_flags_present=False,
                follow_up_questions=[
                    "Есть ли кровоточивость десен при чистке?",
                    "Есть ли подвижность зубов?",
                    "Есть ли отек/боль/гной в области десны?",
                ],
                clinical_profiles=[{"name": "Пародонтит vs пародонтоз", "description": "Стоматологическая дифференциация."}],
                symptom_context={},
                nutrition_context={},
                lab_context={},
                reasoning_context={
                    "reasoning_mode": "focused_questions_mode",
                    "leading_hypothesis": {"label": "Стоматологическая проблема пародонта", "confidence": 0.74},
                    "differential_list": [],
                    "must_ask_next": [],
                    "safe_actions_now": [],
                    "when_to_escalate": [],
                },
            ),
            response_source="oral_health_guard",
            llm_used=False,
        )

    if _is_oral_health_feedback_query(effective_user_message, chat_history):
        quick = _periodontal_quick_response()
        await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, quick))
        return _result(
            response=quick + "\n\n" + DISCLAIMER_TEXT,
            response_simple=quick,
            structured=_build_structured_payload(
                response_text=quick,
                response_simple=quick,
                effective_user_message=effective_user_message,
                severity="YELLOW",
                red_flags_present=False,
                follow_up_questions=[
                    "Есть ли кровоточивость десен при чистке?",
                    "Есть ли подвижность зубов?",
                    "Есть ли отек/боль/гной в области десны?",
                ],
                clinical_profiles=[{"name": "Стоматология (пародонт)", "description": "Ветка болезней пародонта."}],
                symptom_context={},
                nutrition_context={},
                lab_context={},
            ),
            response_source="oral_health_feedback_guard",
            llm_used=False,
        )

    parsed_symptoms = parse_symptoms(effective_user_message or "")
    symptom_context = parsed_symptoms.to_dict()

    nutrition_context = analyze_nutrition(
        parsed_symptoms,
        effective_user_message or "",
    )
    lab_type = None
    try:
        from app.services.lab_document_router import detect_lab_type
        lab_type = detect_lab_type((effective_user_message or "") + "\n" + (document_context or ""))
    except Exception:
        pass
    food_trigger_context = build_food_trigger_context(
        effective_user_message or "",
        document_context or "",
        lab_type=lab_type,
    )
    multidisciplinary_context = build_multidisciplinary_context(
        effective_user_message or "",
        document_context or "",
    )
    reasoning_graph_context = build_reasoning_graph_context(
        effective_user_message or "",
        document_context or "",
    )
    symptom_severity_context = build_symptom_severity_context(
        effective_user_message or "",
        document_context or "",
    )
    symptom_cause_context = build_symptom_cause_context(
        effective_user_message or "",
        document_context or "",
        food_trigger_context=food_trigger_context,
    )

    selector_state: dict[str, Any] = {}
    try:
        last_state = {}
        if chat_history and isinstance(chat_history[-1], dict):
            last_state = chat_history[-1].get("orchestrator_state") or {}
        selector_state = read_selector_state(last_state)
    except Exception:
        selector_state = {}

    try:
        selector = MedicalCoreSelector()
        if selector.available():
            selector_result = selector.select(
                user_message=effective_user_message,
                symptom_context=symptom_context,
                profile=profile or {},
                existing_state=selector_state,
                limit=5,
            )
            if selector_result and selector_result.matched:
                selector_payload = selector_result.to_dict()
                selector_question = str(selector_result.best_question or "").strip()
    except Exception:
        selector_result = None
        selector_payload = {}
        selector_question = ""

    try:
        last_orchestrator_state = {}
        if chat_history and isinstance(chat_history[-1], dict):
            last_orchestrator_state = chat_history[-1].get("orchestrator_state") or {}
        followup_state_obj = prime_followup_state(
            last_orchestrator_state,
            selector_payload=selector_payload,
            triage_level=str(selector_payload.get("triage_level") or ""),
            triage_target=str(selector_payload.get("triage_target") or ""),
            specialist=str(selector_payload.get("specialist") or ""),
        )
    except Exception:
        followup_state_obj = FollowupState()

    clinical_profiles = search_clinical_profiles(effective_user_message, top_k=3)
    complaint_hits = search_complaint_reference(effective_user_message, top_k=2)
    complaint_protocol = complaint_hits[0] if complaint_hits else None
    if complaint_protocol is None:
        complaint_protocol = build_bridge_complaint_protocol(effective_user_message, top_k=3)
    medical_core_enrichment = _build_medical_core_enrichment(effective_user_message, limit=3)
    medical_core_primary = medical_core_enrichment.get("primary") if isinstance(medical_core_enrichment, dict) else None
    if isinstance(medical_core_primary, dict):
        primary_triage = medical_core_primary.get("triage") or {}
        primary_care = medical_core_primary.get("care") or {}
        medical_core_guidance_context = {
            "complaint_entry": medical_core_primary,
            "safe_summary": {
                "care_level": str(medical_core_enrichment.get("care_level") or "").strip(),
                "red_flags": [str(x).strip() for x in (medical_core_enrichment.get("red_flags") or []) if str(x).strip()],
                "tests": [str(x).strip() for x in (primary_care.get("tests") or []) if str(x).strip()],
                "first_line": [str(x).strip() for x in (primary_care.get("first_line") or []) if str(x).strip()],
                "nutrition": [str(x).strip() for x in (primary_care.get("nutrition") or []) if str(x).strip()],
                "activity": [str(x).strip() for x in (primary_care.get("activity") or []) if str(x).strip()],
                "triage": dict(primary_triage) if isinstance(primary_triage, dict) else {},
            },
            "candidate_diseases": list(medical_core_enrichment.get("candidate_diseases") or []),
        }
    if complaint_protocol is None and isinstance(medical_core_primary, dict):
        complaint_protocol = _protocol_from_medical_core_entry(medical_core_primary)
    top20_hits = match_top20(effective_user_message, top_k=1)
    top20_entry = top20_hits[0] if top20_hits else None
    if complaint_protocol is None and top20_entry:
        complaint_protocol = _protocol_from_top20(top20_entry)
    elif complaint_protocol and top20_entry:
        complaint_protocol = _merge_top20_into_protocol(complaint_protocol, top20_entry)

    medication_mode = route_medication_lookup(
        effective_user_message or "",
        complaint_protocol=complaint_protocol if isinstance(complaint_protocol, dict) else None,
        mode_hint=consultation_mode_hint,
    )
    if medication_mode and _is_msk_trauma_like(effective_user_message or ""):
        medication_mode = None
    if medication_mode:
        mode_name = str(medication_mode.get("mode") or "").strip() or "medication_lookup_mode"
        mode_response = str(medication_mode.get("response") or "").strip()
        mode_simple = str(medication_mode.get("response_simple") or mode_response).strip()
        reasoning_ctx = {
            "reasoning_mode": mode_name,
            "leading_hypothesis": {
                "label": str(medication_mode.get("matched_label") or mode_name).strip(),
                "confidence": 0.81,
            },
            "differential_list": [],
            "must_ask_next": [],
            "safe_actions_now": [],
            "when_to_escalate": [],
            "red_flags_detected": [],
        }
        await _ensure_min_delay(t0)
        return _result(
            response=mode_response,
            response_simple=mode_simple,
            severity="YELLOW",
            structured=_build_structured_payload(
                response_text=mode_response,
                response_simple=mode_simple,
                effective_user_message=effective_user_message,
                severity="YELLOW",
                red_flags_present=False,
                follow_up_questions=[],
                clinical_profiles=[],
                symptom_context=symptom_context,
                nutrition_context=nutrition_context,
                lab_context={},
                food_trigger_context=food_trigger_context,
                multidisciplinary_context=multidisciplinary_context,
                symptom_cause_context=symptom_cause_context,
                symptom_severity_context=symptom_severity_context,
                relevance_funnel_context={},
                reasoning_context=reasoning_ctx,
            ),
            llm_used=False,
            response_source=mode_name,
            symptom_context_data=symptom_context,
            nutrition_context=nutrition_context,
            lab_context_data={},
        )

    lab_context = analyze_labs(document_context or "")
    labs_layer_context = build_labs_layer_context(
        user_text=effective_user_message or "",
        document_text=document_context or "",
        complaint_protocol=complaint_protocol,
        clinical_profiles=clinical_profiles,
    )
    if labs_layer_context:
        lab_context["labs_layer"] = labs_layer_context
        follow_up = [str(x).strip() for x in (labs_layer_context.get("follow_up_recommendations") or []) if str(x).strip()]
        if follow_up:
            current = [str(x).strip() for x in (lab_context.get("suggested_tests") or []) if str(x).strip()]
            merged = []
            seen = set()
            for item in current + follow_up:
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
            lab_context["suggested_tests"] = merged

    assessment = build_diagnostic_assessment(
    symptom_context=symptom_context,
    nutrition_context=nutrition_context,
    lab_context=lab_context,
    top_k=5,
)

    clinical_profile = assessment["clinical_profile"]
    ranked_diseases = assessment["ranked_diseases"]
    triage_data = assessment["triage"]

    top_hypotheses = ranked_diseases[:3]

    quick_intent = (
        extract_symptoms_nutrition_activity_intent(effective_user_message or "").get("intent") or "general"
    )

    if _is_smalltalk_message(effective_user_message):
        response_text = (
            "Здравствуйте. Рад помочь.\n"
            "Чтобы перейти к делу, коротко опишите жалобу: что беспокоит, как давно и что уже пробовали.\n"
            + DISCLAIMER_TEXT
        )
        await _ensure_min_delay(t0)
        return _result(
            response=response_text,
            response_simple="Здравствуйте. Опишите, пожалуйста, вашу жалобу и длительность симптомов.",
            structured=_build_structured_payload(
                response_text=response_text,
                response_simple="Здравствуйте. Опишите, пожалуйста, вашу жалобу и длительность симптомов.",
                effective_user_message=effective_user_message,
                severity="YELLOW",
                red_flags_present=False,
                follow_up_questions=[],
                clinical_profiles=[],
                symptom_context=symptom_context,
                nutrition_context=nutrition_context,
                lab_context=lab_context,
                symptom_cause_context=symptom_cause_context,
                symptom_severity_context=symptom_severity_context,
            ),
            response_source="app_guard",
            symptom_context_data=symptom_context,
            nutrition_context=nutrition_context,
            lab_context_data=lab_context,
        )

    if is_emergency_call_intent(effective_user_message or ""):
        profile_name = " ".join(str((profile or {}).get("name") or "").split())
        profile_address = " ".join(str((profile or {}).get("address") or "").split())
        profile_age = _format_profile_age(profile or {})
        profile_sex = _format_profile_sex(profile or {})
        emergency_reason = _build_emergency_suspected_reason(effective_user_message or "", None)
        dispatcher_details = []
        if profile_name:
            dispatcher_details.append(f"имя: {profile_name}")
        if profile_age:
            dispatcher_details.append(f"возраст: {profile_age}")
        if profile_sex:
            dispatcher_details.append(f"пол: {profile_sex}")
        if emergency_reason:
            dispatcher_details.append(f"предположение: {emergency_reason}")
        dispatcher_line = (" Для диспетчера передаю: " + "; ".join(dispatcher_details) + ".") if dispatcher_details else ""
        if profile_address:
            emergency = (
                "Слышу вас. Похоже, нужна срочная помощь. "
                "Хорошо, вызываю скорую. "
                f"Твой адрес: {profile_address}. "
                f"Повторяю адрес для диспетчера: {profile_address}. "
                "Если есть возможность, продублируйте адрес и ключевые симптомы оператору 103/112."
                + dispatcher_line
            )
        else:
            emergency = (
                "Слышу вас. Похоже, нужна срочная помощь. "
                "Сейчас звоните 103 или 112. "
                "Продиктуйте оператору полный адрес и ключевые симптомы. Я остаюсь с вами."
                + dispatcher_line
            )
        logger.info(
            "emergency_call_intent_detected",
            extra={
                "user_id": user_id,
                "subject_id": subject_id or "main",
                "has_address": bool(profile_address),
            },
        )
        await _ensure_min_delay(t0, 0.45)
        return _result(
            response=emergency + "\n" + DISCLAIMER_TEXT,
            response_simple=emergency,
            structured=_build_structured_payload(
                response_text=emergency,
                response_simple=emergency,
                effective_user_message=effective_user_message,
                severity="RED",
                red_flags_present=True,
                follow_up_questions=[],
                clinical_profiles=[],
                symptom_context=symptom_context,
                nutrition_context=nutrition_context,
                lab_context=lab_context,
            ),
            response_source="emergency_call_intent",
            llm_used=False,
        )

    # Stateful triage (oral / MSK): if flow returns a response, use it and skip long path
    try:
        triage_response, _ = run_stateful_triage(
            user_message=effective_user_message or "",
            chat_history=chat_history or [],
        )
        if triage_response and (triage_response or "").strip():
            consultation_state = build_consultation_state(
                user_message=effective_user_message or "",
                chat_history=chat_history or [],
                profile=profile,
                structured={"severity": "YELLOW", "chief_complaint": effective_user_message or ""},
                complaint_protocol=complaint_protocol,
                complaint_meta=build_complaint_meta(complaint_protocol),
                strict_protocol=None,
                has_lab_data=documents_count > 0,
            )
            complaint = complaint_protocol if isinstance(complaint_protocol, dict) else {}
            care_plan = [str(x).strip() for x in (complaint.get("first_line_non_drug_steps") or []) if str(x).strip()]
            when_urgent = [str(x).strip() for x in (complaint.get("when_to_see_doctor") or complaint.get("red_flags_specific") or []) if str(x).strip()]
            structured_for_report = {
                "care_plan_today": care_plan,
                "top_hypotheses": [{"name": h.get("name") or h.get("label_ru") or str(h)} for h in top_hypotheses[:5] if isinstance(h, dict)],
                "patient_summary": triage_response[:300] if len(triage_response or "") > 300 else triage_response,
                "when_urgent": when_urgent[:4],
            }
            consultation_summary = _summarize_for_report(chat_history, effective_user_message, symptom_entries)
            report = build_consultation_final_report(
                case_summary=consultation_summary,
                severity="YELLOW",
                structured=structured_for_report,
                orchestrator_state=consultation_state.model_dump(),
                title="Итог консультации",
            )
            await _ensure_min_delay(t0)
            return _result(
                response=triage_response,
                response_simple=(triage_response[:300] + "…" if len(triage_response) > 300 else triage_response),
                conclusion=True,
                report=report,
                suggest_pdf=True,
                structured=_build_structured_payload(
                    response_text=triage_response,
                    response_simple=triage_response[:200] or triage_response,
                    effective_user_message=effective_user_message,
                    severity="YELLOW",
                    red_flags_present=False,
                    follow_up_questions=[],
                    clinical_profiles=[{"name": h.get("name") or "", "description": h.get("explanation") or ""} for h in top_hypotheses[:3] if isinstance(h, dict) and h.get("name")],
                    symptom_context=symptom_context,
                    nutrition_context=nutrition_context,
                    lab_context=lab_context,
                    food_trigger_context=food_trigger_context,
                    multidisciplinary_context=multidisciplinary_context,
                    symptom_cause_context=symptom_cause_context,
                    symptom_severity_context=symptom_severity_context,
                    relevance_funnel_context={},
                    reasoning_context={"reasoning_mode": "stateful_triage"},
                ),
                llm_used=False,
                response_source="stateful_triage",
                symptom_context_data=symptom_context,
                nutrition_context=nutrition_context,
                lab_context_data=lab_context,
            )
    except Exception:
        pass

    msg_low_eff = (effective_user_message or "").lower()
    explicit_red_flag = _has_explicit_red_flag_content(effective_user_message)
    allergy_urgent_phrase = (
        any(k in msg_low_eff for k in ("отек губ", "отёк губ", "отек языка", "отёк языка", "отек горла", "отёк горла"))
        and any(k in msg_low_eff for k in ("после", "орех", "еда", "продукт", "аллерг", "клубник"))
    )
    if allergy_urgent_phrase:
        profile_address_allergy = " ".join(str((profile or {}).get("address") or "").split())
        allergy_core = (
            "Есть признаки возможной острой аллергической реакции. "
            "Если отек нарастает, появляется одышка, свистящее дыхание или слабость — срочно звоните 103/112."
        )
        urgent_resp = wrap_immediate_emergency_message(allergy_core, profile_address=profile_address_allergy)
        allergy_amb_struct = ambulance_offer_flow_payload(profile_address_allergy)
        await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, urgent_resp))
        structured_allergy = _build_structured_payload(
            response_text=urgent_resp,
            response_simple=urgent_resp,
            effective_user_message=effective_user_message,
            severity="RED",
            red_flags_present=True,
            follow_up_questions=[],
            clinical_profiles=[],
            when_urgent=["Срочно звоните 103 или 112 при нарастании отека/одышке."],
            symptom_context=symptom_context,
            nutrition_context=nutrition_context,
            lab_context=lab_context,
            symptom_cause_context=symptom_cause_context,
            symptom_severity_context=symptom_severity_context,
        )
        structured_allergy = {**structured_allergy, **allergy_amb_struct}
        return _result(
            response=urgent_resp,
            response_simple=urgent_resp,
            severity="RED",
            red_flags_present=True,
            red_flag_matches=["allergy_angioedema_risk"],
            structured=structured_allergy,
            response_source="red_flag_guard",
            symptom_context_data=symptom_context,
            nutrition_context=nutrition_context,
            lab_context_data=lab_context,
        )
    should_check_red = explicit_red_flag or _should_run_red_flag_screening(
        effective_user_message, quick_intent
    ) or bool((symptom_severity_context or {}).get("urgent"))

    profile_address_red = " ".join(str((profile or {}).get("address") or "").split())
    if should_check_red:
        is_red, red_response, matched_flags, red_aux = screen_user_input(
            effective_user_message, symptom_entries, profile_address=profile_address_red
        )
    else:
        is_red, red_response, matched_flags, red_aux = False, "", [], {}

    if is_red and red_response:
        top_ranked_code = str((top_hypotheses[0] or {}).get("code") or "").strip().lower() if top_hypotheses else ""
        benign_gastro_top = {
            "food_poisoning",
            "acute_gastroenteritis",
            "gastroenteritis",
            "gastritis",
            "gerd",
            "ibs",
            "indigestion",
        }
        ranking_is_benign = top_ranked_code in benign_gastro_top
        triage_is_not_urgent = str((triage_data or {}).get("triage") or "").lower() != "urgent"
        anemia_nonurgent_context = (
            any(k in msg_low_eff for k in ("гемоглобин", "hgb", "анем"))
            and not any(k in msg_low_eff for k in ("обморок", "потеря сознания", "сильная одышка", "боль в груди"))
        )

        if (ranking_is_benign and triage_is_not_urgent and not explicit_red_flag) or anemia_nonurgent_context:
            is_red, red_response, matched_flags, red_aux = False, "", [], {}

    if is_red and red_response:
        await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, red_response))
        structured_red = _build_structured_payload(
            response_text=red_response,
            response_simple=red_response,
            effective_user_message=effective_user_message,
            severity="RED",
            red_flags_present=True,
            follow_up_questions=[],
            clinical_profiles=[],
            when_urgent=["Срочно звоните 103 или в местную службу спасения 112."],
            symptom_context=symptom_context,
            nutrition_context=nutrition_context,
            lab_context=lab_context,
            symptom_cause_context=symptom_cause_context,
            symptom_severity_context=symptom_severity_context,
        )
        if red_aux:
            structured_red = {**structured_red, **red_aux}
        return _result(
            response=red_response,
            response_simple=red_response,
            severity="RED",
            red_flags_present=True,
            red_flag_matches=matched_flags,
            structured=structured_red,
            response_source="red_flag_guard",
            symptom_context_data=symptom_context,
            nutrition_context=nutrition_context,
            lab_context_data=lab_context,
        )

    # Clinical Orchestrator: единый пайплайн ввод → симптомы → red flags → документы → анализы → правила → decision engine → ответ
    try:
        symptom_list = []
        for e in symptom_entries or []:
            s = str((e.get("text") or e.get("symptom") or e.get("entry") or e)).strip()
            if s:
                symptom_list.append(s)
        if effective_user_message and effective_user_message.strip() and (effective_user_message not in symptom_list):
            symptom_list = [effective_user_message.strip()] + symptom_list
        orch_input = OrchestratorInput(
            user_text=effective_user_message or "",
            user_id=user_id,
            session_id=subject_id,
            symptoms=symptom_list[:20],
            uploaded_files=[],
            raw_lab_rows=[],
            profile=profile or {},
            conversation_history=chat_history or [],
            initial_hypotheses=[{"name": r.get("name") or "", "score": float(r.get("score") or 0)} for r in (ranked_diseases or [])],
        )
        orch = ClinicalOrchestrator()
        orch_result = orch.run(orch_input)
        if orch_result.ok and orch_result.final_user_message:
            consultation_state = build_consultation_state(
                user_message=effective_user_message or "",
                chat_history=chat_history or [],
                profile=profile,
                structured={"severity": "RED" if orch_result.state == "emergency" else "YELLOW", "chief_complaint": effective_user_message or ""},
                complaint_protocol=complaint_protocol,
                complaint_meta=build_complaint_meta(complaint_protocol),
                strict_protocol=None,
                has_lab_data=documents_count > 0,
            )
            care_plan_list = []
            if orch_result.care_plan and isinstance(orch_result.care_plan, dict):
                care_plan_list = [str(a).strip() for a in (orch_result.care_plan.get("actions") or []) if str(a).strip()]
            if not care_plan_list and isinstance(complaint_protocol, dict):
                care_plan_list = [str(x).strip() for x in (complaint_protocol.get("first_line_non_drug_steps") or []) if str(x).strip()]
            complaint = complaint_protocol if isinstance(complaint_protocol, dict) else {}
            when_urgent = [str(x).strip() for x in (complaint.get("when_to_see_doctor") or complaint.get("red_flags_specific") or []) if str(x).strip()]
            structured_for_report = {
                "care_plan_today": care_plan_list,
                "recommended_labs": list(orch_result.recommended_labs or []),
                "top_hypotheses": [{"name": h} for h in (orch_result.user_hypotheses or [])[:5]],
                "patient_summary": (orch_result.final_user_message or "")[:300],
                "when_urgent": when_urgent[:4],
            }
            consultation_summary = _summarize_for_report(chat_history, effective_user_message, symptom_entries)
            report = build_consultation_final_report(
                case_summary=consultation_summary,
                severity="RED" if orch_result.state == "emergency" else "YELLOW",
                structured=structured_for_report,
                orchestrator_state=consultation_state.model_dump(),
                title="Итог консультации",
            )
            await _ensure_min_delay(t0)
            payload = _build_structured_payload(
                response_text=orch_result.final_user_message,
                response_simple=(orch_result.final_user_message[:400] if len(orch_result.final_user_message or "") > 400 else orch_result.final_user_message),
                effective_user_message=effective_user_message,
                severity="RED" if orch_result.state == "emergency" else "YELLOW",
                red_flags_present=(orch_result.state == "emergency"),
                follow_up_questions=orch_result.questions or [],
                clinical_profiles=[],
                symptom_context=symptom_context,
                nutrition_context=nutrition_context,
                lab_context=lab_context,
                symptom_cause_context=symptom_cause_context,
                symptom_severity_context=symptom_severity_context,
            )
            return _result(
                response=orch_result.final_user_message or "",
                response_simple=(orch_result.final_user_message or "")[:400],
                conclusion=True,
                report=report,
                suggest_pdf=True,
                severity="RED" if orch_result.state == "emergency" else "YELLOW",
                red_flags_present=(orch_result.state == "emergency"),
                structured=payload,
                response_source="clinical_orchestrator",
                symptom_context_data=symptom_context,
                nutrition_context=nutrition_context,
                lab_context_data=lab_context,
                mikhail_state=orch_result.state,
                mikhail_urgency=orch_result.urgency,
                mikhail_questions=orch_result.questions or [],
                mikhail_recommended_labs=orch_result.recommended_labs or [],
                mikhail_hypotheses=orch_result.user_hypotheses or [],
                mikhail_final_message=orch_result.final_user_message or "",
                mikhail_debug=orch_result.debug,
                user_report_structured=orch_result.user_report_structured,
                continuity_summary=orch_result.continuity_summary,
                care_plan=orch_result.care_plan,
                care_plan_message=orch_result.care_plan_message,
                physician_report=orch_result.physician_report,
                physician_report_text=orch_result.physician_report_text,
                product=orch_result.product,
                launch=orch_result.launch,
                onboarding=orch_result.onboarding,
                conversion=orch_result.conversion,
            )
    except Exception:
        pass

    if (
        quick_intent == "general"
        and not complaint_protocol
        and not _is_medical_complaint_like(effective_user_message)
        and would_ask_clarifying_instead_of_joke(effective_user_message)
    ):
        followup = suggest_clarifying_questions(
            user_message=effective_user_message or "",
            chat_history=chat_history or [],
            has_lab_data=documents_count > 0,
            max_questions=MAX_QUESTIONS_PER_TURN,
        )
        response_text = (
            "Чтобы помочь, уточните, пожалуйста:\n\n"
            + (
                "\n".join(followup)
                if followup
                else "Опишите, что именно беспокоит: что чувствуете, как давно и что уже пробовали."
            )
        )
        response_simple = "Уточните, пожалуйста, жалобу — задам несколько наводящих вопросов."
        await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, recommendation_part))
        return _result(
            response=response_text,
            response_simple=response_simple,
            structured=_build_structured_payload(
                response_text=response_text,
                response_simple=response_simple,
                effective_user_message=effective_user_message,
                severity="YELLOW",
                red_flags_present=False,
                follow_up_questions=followup,
                clinical_profiles=[],
                symptom_context=symptom_context,
                nutrition_context=nutrition_context,
                lab_context=lab_context,
                symptom_cause_context=symptom_cause_context,
                symptom_severity_context=symptom_severity_context,
            ),
            response_source="app_guard",
            symptom_context_data=symptom_context,
            nutrition_context=nutrition_context,
            lab_context_data=lab_context,
        )


    offline_formats = search_offline_with_formats(effective_user_message, max_med=3, max_guide=3)
    offline_fallback = offline_formats.get("professional") or ""

    learned_list: list[dict[str, Any]] = []
    use_learned_instead_of_llm = False
    learned_list = get_learned_responses(effective_user_message or "", limit=2)
    if not (offline_fallback or "").strip() and learned_list and learned_list[0].get("score", 0) >= 0.5:
        learned_text = (learned_list[0].get("response") or learned_list[0].get("response_simple") or "").strip()
        if learned_text:
            offline_fallback = learned_text
            use_learned_instead_of_llm = True

    doc_ctx = (document_context or "").strip()
    specialty_key, specialty_label = detect_specialty(effective_user_message, chat_history, doc_ctx)
    role_hint = (
        "\n\nТы отвечаешь в роли: " + specialty_label + ". "
        "Веди диалог как полноценный обученный специалист. Правило диалога: сначала кратко сформулируй рабочую гипотезу "
        "(1–2 предложения), затем при необходимости задай РОВНО ОДИН уточняющий вопрос в JSON follow_up_questions "
        f"(массив из 0 или 1 строки). За весь диалог не более {MAX_FOLLOWUP_ROUNDS} таких вопросов подряд: "
        "если пользователь уже ответил на предыдущие уточнения — не повторяй те же вопросы, переходи к выводу. "
        "После лимита уточнений или при достаточных данных: заполни top_hypotheses, care_plan_today, "
        "рекомендации по лечению/наблюдению, питанию и физической активности; follow_up_questions оставь пустым. "
        "Итоговые выводы можно пометить [CONCLUSION] в patient_facing_response при необходимости."
    )
    role_hint += (
        "\n\nВажно: в истории могут быть сообщения по разным темам (разные жалобы, разные анализы). "
        "Отвечай только на текущий запрос пользователя. Не объединяй все жалобы и все анализы в один вывод — "
        "один человек не «болеет всем»; давай релевантные выводы и рекомендации только по текущей теме."
    )
    if doc_ctx:
        role_hint += (
            "\n\nКонтекст по одному отчёту/документу (учитывай только если он относится к текущему запросу):\n"
            + doc_ctx[:2000]
        )

    metabolic_hint = ""
    if _is_metabolic_context(effective_user_message, doc_ctx, chat_history):
        clinical_core = _get_clinical_core_prompt()
        metabolic_hint = (
            "\n\nДополнительный режим метаболической интерпретации "
            "(применяй только в пределах релевантных метаболических данных):\n"
            + _get_metabolic_addon_prompt()
            + (("\n\n---\n\n" + clinical_core) if clinical_core else "")
        )

    cached = get_response_cache(user_id, effective_user_message)

    context_str = _build_context_string(profile, documents_count, symptom_entries, vitals)

    mode_hint = ""
    if app_mode == "COMFORT_45_PLUS":
        mode_hint = "\n\nРежим 45+: макс. 2 гипотезы, без процентов (формулируй «более вероятно» / «менее вероятно»), короткие формулировки, успокаивающий тон."
    elif app_mode == "COMFORT_65_PLUS":
        mode_hint = "\n\nРежим 65+: одна основная причина и одна альтернатива, без вероятностей и графиков, очень короткие фразы; при RED — экстренные инструкции."
    mode_hint += (
        "\n\n[ПОШАГОВЫЙ ДИАЛОГ — ПРИОРИТЕТ]\n"
        f"1) Если можно безопасно ответить без уточнений — дай ответ сразу (гипотеза + что делать + питание/активность при уместности).\n"
        f"2) Иначе: краткая гипотеза + не более ОДНОГО нового вопроса в follow_up_questions (массив максимум из 1 элемента).\n"
        f"3) Не повторяй вопрос, на который пользователь уже ответил в истории чата.\n"
        f"4) После {MAX_FOLLOWUP_ROUNDS} твоих ответов с уточнениями в этом диалоге обязательно дай итог: "
        "top_hypotheses, care_plan_today, когда к врачу; follow_up_questions = [].\n"
        "В JSON: follow_up_questions — 0 или 1 строка за раз."
    )

    kb_context = search_scenario_context(effective_user_message)
    complaint_defaults = build_complaint_meta(complaint_protocol)
    current_season = _current_season_label()
    msg_low_eff = (effective_user_message or "").lower()

    is_food_discomfort_triage = (
        any(k in msg_low_eff for k in (
            "семечк", "подсолнечник", "плохо после", "после еды", "жирн",
            "переел", "переедание", "поел много", "поела много", "съел много", "съела много",
            "300 грамм", "много съел", "обожрался", "объелся"
        ))
        and any(k in msg_low_eff for k in ("тошнот", "плохое самочувствие", "ухудшилось", "недомога", "тяжесть", "общее недомогание"))
        and not any(k in msg_low_eff for k in ("острая боль", "кинжальн", "сильная боль в животе"))
    )

    offline_priority_mode = _should_use_offline_priority(
        complaint_protocol=complaint_protocol,
        current_season=current_season,
        documents_count=documents_count,
        chat_history=chat_history,
    )

    complaint_name = str((complaint_protocol or {}).get("complaint") or "").lower()
    if "плохо после еды" in complaint_name or "непереносимость пищи" in complaint_name or is_food_discomfort_triage:
        offline_priority_mode = False

    strict_hits = search_strict_topic_protocol(effective_user_message, top_k=1)
    strict_protocol = strict_hits[0] if strict_hits else None
    if strict_protocol and not _is_strict_protocol_relevant(effective_user_message, strict_protocol):
        strict_protocol = None
    if is_food_discomfort_triage:
        strict_protocol = None
        complaint_protocol = None

    funnel_candidates: list[dict[str, Any]] = []
    if strict_protocol:
        dx = str((strict_protocol or {}).get("diagnosis") or (strict_protocol or {}).get("title") or "").strip()
        if dx:
            funnel_candidates.append({"label": dx, "source": "strict_protocol"})
    for cp in clinical_profiles[:6]:
        name = str((cp or {}).get("name") or "").strip()
        if name:
            funnel_candidates.append({"label": name, "source": "clinical_profiles"})
    for h in top_hypotheses[:6]:
        name = str((h or {}).get("name") or "").strip()
        if name:
            funnel_candidates.append({"label": name, "source": "diagnostic_engine"})
    for c in (symptom_cause_context.get("candidate_hypotheses") or [])[:6]:
        label = str(c or "").strip()
        if label:
            funnel_candidates.append({"label": label, "source": "symptom_cause_graph"})
    for c in (food_trigger_context.get("possible_conditions") or [])[:6]:
        label = str(c or "").strip()
        if label:
            funnel_candidates.append({"label": label, "source": "food_trigger_rules"})
    for c in (multidisciplinary_context.get("candidate_hypotheses") or [])[:6]:
        label = str(c or "").strip()
        if label:
            funnel_candidates.append({"label": label, "source": "multidisciplinary_library"})
    for c in (reasoning_graph_context.get("candidate_conditions") or [])[:6]:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label") or "").strip()
        if label:
            funnel_candidates.append({"label": label, "source": "reasoning_graph_conditions"})

    relevance_funnel = apply_relevance_funnel(effective_user_message or "", funnel_candidates)
    top_funnel_labels = [str(x).strip() for x in (relevance_funnel.get("top_labels") or []) if str(x).strip()]
    if top_funnel_labels:
        clinical_profiles = [{"name": x, "description": "Отфильтровано воронкой релевантности."} for x in top_funnel_labels[:3]]
    if strict_protocol:
        strict_dx = str((strict_protocol or {}).get("diagnosis") or (strict_protocol or {}).get("title") or "").strip().lower()
        if strict_dx and strict_dx not in {x.lower() for x in top_funnel_labels} and top_funnel_labels:
            strict_protocol = None

    clinical_hint = format_profiles_for_prompt(clinical_profiles)
    kb_hint = ("\n\nРелевантный сценарий из медицинской базы знаний:\n" + kb_context) if kb_context else ""

    try:
        master_layer = get_master_knowledge_for_prompt(6000)
        if master_layer:
            kb_hint = "\n\n[MASTER v3 — сценарии, маркеры, AUTO DIAGNOSIS ENGINE]\n" + master_layer + kb_hint
    except Exception:
        pass

    if top20_entry:
        kb_hint += "\n\n" + format_top20_for_prompt(top20_entry)

    intent_sem = format_intent_hint_for_prompt(effective_user_message or "")
    if intent_sem:
        kb_hint += "\n\n" + intent_sem

    if complaint_protocol:
        kb_hint += "\n\nРелевантный протокол жалобы:\n" + str(complaint_protocol.get("complaint") or "") + ". "
        if complaint_protocol.get("description"):
            kb_hint += str(complaint_protocol.get("description") or "")[:500]
        seasonality = complaint_defaults.get("seasonality") or {}
        peaks = [str(x).strip().lower() for x in (seasonality.get("peak_seasons") or []) if str(x).strip()]
        if peaks:
            seasonal_status = "сейчас сезонный пик" if current_season in peaks else "вне сезонного пика"
            kb_hint += (
                "\nСезонный контекст: сейчас " + current_season + "; для этой жалобы пики: "
                + ", ".join(peaks) + " (" + seasonal_status + ")."
            )
        elif seasonality.get("year_round"):
            kb_hint += "\nСезонный контекст: жалоба актуальна круглый год."

    if medical_core_enrichment:
        mc_primary = medical_core_enrichment.get("primary") or {}
        mc_name = str(mc_primary.get("name") or "").strip()
        mc_level = str(medical_core_enrichment.get("care_level") or "").strip()
        mc_red_flags = [str(x).strip() for x in (medical_core_enrichment.get("red_flags") or []) if str(x).strip()]
        mc_candidates = [str(x).strip() for x in (medical_core_enrichment.get("candidate_diseases") or []) if str(x).strip()]
        mc_must_ask = [str(x).strip() for x in (medical_core_enrichment.get("must_ask") or []) if str(x).strip()]
        kb_hint += "\n\n[MEDICAL_CORE_OVERLAY — read-only enrichment]"
        if mc_name:
            kb_hint += "\nЖалоба (overlay): " + mc_name
        if mc_level:
            kb_hint += "\nРекомендуемый уровень помощи: " + mc_level
        if mc_candidates:
            kb_hint += "\nКандидатные гипотезы по жалобе: " + "; ".join(mc_candidates[:3])
        if mc_must_ask:
            kb_hint += "\nПриоритетные уточняющие вопросы: " + "; ".join(mc_must_ask[:2])
        if mc_red_flags:
            kb_hint += "\nRed flags overlay: " + "; ".join(mc_red_flags[:3])

    if clinical_hint:
        kb_hint += "\n\nРелевантные клинические профили из офлайн-каталога:\n" + clinical_hint

    if symptom_context:
        kb_hint += "\n\nСимптомный контекст:\n" + json.dumps(symptom_context, ensure_ascii=False)

    if nutrition_context:
        kb_hint += "\n\nНутриционный контекст:\n" + json.dumps(nutrition_context, ensure_ascii=False)

    if food_trigger_context:
        kb_hint += "\n\nКонтекст пищевых триггеров:\n" + json.dumps(food_trigger_context, ensure_ascii=False)
        food_prompt = str((food_trigger_context.get("concierge_prompt") or "")).strip()
        if food_prompt:
            kb_hint += "\n\nFood Trigger Engine (еда -> симптом -> гипотеза):\n" + food_prompt[:3200]
        hist_layer = food_trigger_context.get("histamine_layer") if isinstance(food_trigger_context, dict) else {}
        if isinstance(hist_layer, dict) and hist_layer:
            kb_hint += (
                "\n\nHistamine / MCAS layer (дополнительный образовательный слой, не выше clinical_guidelines):\n"
                + json.dumps(hist_layer, ensure_ascii=False)
            )
            hist_rag = [str(x).strip() for x in (hist_layer.get("rag_hits") or []) if str(x).strip()]
            if hist_rag:
                kb_hint += "\n\nRAG: food histamine chunks:\n- " + "\n- ".join(hist_rag[:3])
    if multidisciplinary_context:
        kb_hint += (
            "\n\nМультидисциплинарный слой (врач/нутрициолог/биохимик/функциональная диагностика):\n"
            + json.dumps(multidisciplinary_context, ensure_ascii=False)
        )
    if reasoning_graph_context:
        kb_hint += (
            "\n\nReasoning Graph layers (symptoms/conditions/labs/red_flags/foods/edges/follow_up_questions):\n"
            + json.dumps(reasoning_graph_context, ensure_ascii=False)
        )

    if symptom_cause_context:
        kb_hint += (
            "\n\nSymptom Cause Graph (дополнительный слой после clinical_guidelines/ontologies/profiles):\n"
            + json.dumps(symptom_cause_context, ensure_ascii=False)
        )
        cause_rag = [str(x).strip() for x in (symptom_cause_context.get("rag_hits") or []) if str(x).strip()]
        if cause_rag:
            kb_hint += "\n\nRAG: symptom->cause chunks:\n- " + "\n- ".join(cause_rag[:3])

    if symptom_severity_context:
        kb_hint += (
            "\n\nSymptom Severity Layer (дополнительный слой после clinical_guidelines/ontologies/profiles):\n"
            + json.dumps(symptom_severity_context, ensure_ascii=False)
        )
        sev_rag = [str(x).strip() for x in (symptom_severity_context.get("rag_hits") or []) if str(x).strip()]
        if sev_rag:
            kb_hint += "\n\nRAG: symptom severity chunks:\n- " + "\n- ".join(sev_rag[:3])

    if relevance_funnel:
        kb_hint += "\n\nRelevance funnel (пакет кандидатов -> отсев):\n" + json.dumps(relevance_funnel, ensure_ascii=False)

    try:
        from app.services.mikhail_knowledge_retrieval import format_unified_kb_prompt_section

        unified_kb = format_unified_kb_prompt_section(
            (effective_user_message or "").strip(),
            final_items=12,
            max_chars=4500,
        )
        if unified_kb:
            kb_hint += "\n\n" + unified_kb
    except Exception:
        pass

    if lab_context:
        kb_hint += "\n\nЛабораторный контекст:\n" + json.dumps(lab_context, ensure_ascii=False)
        mikhail_addon = str((((lab_context or {}).get("labs_layer") or {}).get("assistant_prompt_addon") or "")).strip()
        if mikhail_addon:
            kb_hint += "\n\nДополнительные правила для Михаила (medical prompt add-on):\n" + mikhail_addon[:3500]
        reasoning_prompt = str((((lab_context or {}).get("labs_layer") or {}).get("reasoning_engine_prompt") or "")).strip()
        if reasoning_prompt:
            kb_hint += (
                "\n\nDiagnostic Reasoning Engine (выполнить до формирования ответа):\n"
                + reasoning_prompt[:4500]
                + "\n\nСначала завершай внутренний клинический анализ по шагам, потом формируй ответ пользователю."
            )
        retrieval_ranking_prompt = str((((lab_context or {}).get("labs_layer") or {}).get("retrieval_ranking_prompt") or "")).strip()
        if retrieval_ranking_prompt:
            kb_hint += (
                "\n\nMedical Retrieval Ranking Engine (после retrieval, до reasoning):\n"
                + retrieval_ranking_prompt[:3200]
            )
        adaptive_question_prompt = str((((lab_context or {}).get("labs_layer") or {}).get("adaptive_question_prompt") or "")).strip()
        if adaptive_question_prompt:
            kb_hint += (
                "\n\nAdaptive Medical Question Engine (после Symptom Intake, до Lab Parser):\n"
                + adaptive_question_prompt[:3200]
            )
        lab_result_parser_prompt = str((((lab_context or {}).get("labs_layer") or {}).get("lab_result_parser_prompt") or "")).strip()
        if lab_result_parser_prompt:
            kb_hint += (
                "\n\nLab Result Parsing Engine (извлечение и нормализация анализов):\n"
                + lab_result_parser_prompt[:3200]
            )
        evidence_weighting_prompt = str((((lab_context or {}).get("labs_layer") or {}).get("evidence_weighting_prompt") or "")).strip()
        if evidence_weighting_prompt:
            kb_hint += (
                "\n\nClinical Evidence Weighting Engine (после reasoning, до safety):\n"
                + evidence_weighting_prompt[:3200]
            )
        safety_guardrail_prompt = str((((lab_context or {}).get("labs_layer") or {}).get("clinical_guardrail_prompt") or "")).strip()
        if safety_guardrail_prompt:
            kb_hint += (
                "\n\nClinical Safety Guardrail (проверка ответа перед отправкой):\n"
                + safety_guardrail_prompt[:3200]
            )
        output_template = (((lab_context or {}).get("labs_layer") or {}).get("output_template") or {})
        if output_template:
            kb_hint += (
                "\n\nОбязательный формат ответа (medical_output_template.json):\n"
                + json.dumps(output_template, ensure_ascii=False)[:5000]
                + "\n\nКритично: не выходи за этот шаблон и порядок разделов."
            )

    if is_food_discomfort_triage:
        kb_hint += """

Триаж «дискомфорт/тошнота после еды (семечки, жирное)» — действуй строго так:
1) Успокоить: «Помогу разобраться.» Озвучь возможные причины: раздражение желудка жирной пищей, переедание, чувствительность к маслу/желчный, реже пищевая непереносимость. Гипотезу «гормоны» для этой жалобы не поддерживай.
2) Задать минимально достаточные уточняющие вопросы (блоки): когда появились симптомы после еды; есть ли рвота, сильная боль в животе, температура, слабость; тяжесть в правом подреберье, вздутие, изжога, горечь; сколько съели (семечек/жирного), бывало ли раньше; болезни желудка/желчного, тошнота после жирного.
3) После ответов — вероятностный вывод (переедание жирного / реакция желчного / раздражение желудка / реже непереносимость), не категоричный диагноз.
4) Рекомендации: что делать сейчас (не есть жирное несколько часов, тёплая вода/чай, мята/ромашка/имбирь, при тяжести — ферменты по инструкции); когда к врачу (сильная боль, рвота, температура, симптомы >24 ч); на будущее (не много жареных семечек, лучше сырые/подсушенные, ~20–30 г, не на голодный желудок).
5) Красные флаги: сильная боль, рвота, температура, ухудшение — напомнить обратиться к врачу."""

    offline_hint = ""
    if offline_fallback:
        offline_hint = (
            "\n\nДанные из офлайн-справочника (лекарства, первая помощь, симптомы). "
            "Учитывай при ответе и сопоставляй с анамнезом пользователя:\n"
            + (offline_fallback[:2500] or "")
        )

    learned_hint = ""
    if learned_list and not use_learned_instead_of_llm:
        for i, le in enumerate(learned_list[:2]):
            if le.get("score", 0) >= 0.35 and (le.get("response") or le.get("response_simple")):
                learned_hint += (
                    "\n\nУдачный ответ из офлайн-справочника по похожему вопросу (источник для анализа, при релевантности используй):\n"
                    + (le.get("response") or le.get("response_simple") or "")[:1800]
                )
                break

    cache_hint = ""
    if cached and (cached.get("response") or cached.get("response_simple")):
        cache_hint = (
            "\n\nРанее на похожий вопрос был дан ответ (используй как ориентир, при необходимости обнови):\n"
            "Вопрос: " + (cached.get("query_orig") or "")[:300]
            + "\nОтвет: " + (cached.get("response") or cached.get("response_simple") or "")[:1200]
        )

    ultra_short_layer = _get_ultra_short_prompt_layer()
    shared_rules_layer = _get_shared_rules_layer()
    reasoning_prompt_layer = _get_reasoning_prompt_layer()
    final_short_prompt_layer = _get_final_short_prompt_layer()
    medication_prompt_layer = _get_medication_search_prompt_layer()
    medication_patch_layer = _get_concierge_medication_patch_layer()
    dialogue_style_layer = _get_dialogue_style_layer()
    character_prompt_layer = _get_character_prompt_layer()
    orchestrator_prompt_layer = _get_orchestrator_prompt_layer()
    preferred_style = str((conversation_prefs or {}).get("preferred_style") or "soft").strip().lower()
    if preferred_style not in {"soft", "direct"}:
        preferred_style = "soft"
    orchestration_runtime_hint = (
        "\n\n[RUNTIME_ORCHESTRATOR_STATE]\n"
        + json.dumps(runtime_orchestrator_state, ensure_ascii=False)
        + "\n"
        + f"[USER_STYLE_PREFERENCE]\npreferred_style={preferred_style}\n"
        + "Правило: если preferred_style=soft, снижай давление и выбирай мягкий redirect; "
        + "если preferred_style=direct, допускается более прямой мотивационный тон без грубости."
    )

    warm_dialog_layer = format_warm_dialog_examples_block(
        (effective_user_message or "").strip(),
        max_dialogs=2,
        max_chars=6500,
    )
    medication_handbook_layer = ""
    if medication_prompt_layer or medication_patch_layer:
        medication_handbook_layer = "\n\n" + medication_handbook_policy_snippet()

    system_content = (
        _get_system_prompt()
        + ("\n\n[ULTRA_SHORT_MODE_LAYER]\n" + ultra_short_layer if ultra_short_layer else "")
        + ("\n\n[MEDICAL_REASONING_ENGINE_LAYER]\n" + reasoning_prompt_layer if reasoning_prompt_layer else "")
        + ("\n\n[FINAL_ANSWER_SHORT_MODE]\n" + final_short_prompt_layer if final_short_prompt_layer else "")
        + ("\n\n[MEDICATION_SEARCH_ENGINE_LAYER]\n" + medication_prompt_layer if medication_prompt_layer else "")
        + ("\n\n[CONCIERGE_MEDICATION_ROUTING_PATCH]\n" + medication_patch_layer if medication_patch_layer else "")
        + medication_handbook_layer
        + ("\n\n[MIKHAIL_CHARACTER]\n" + character_prompt_layer if character_prompt_layer else "")
        + ("\n\n" + dialogue_style_layer if dialogue_style_layer else "")
        + (("\n\n" + warm_dialog_layer) if warm_dialog_layer else "")
        + ("\n\n[MIKHAIL_CONVERSATIONAL_ORCHESTRATOR]\n" + orchestrator_prompt_layer if orchestrator_prompt_layer else "")
        + ("\n\n[SHARED_RESPONSE_RULES]\n" + shared_rules_layer if shared_rules_layer else "")
        + _structured_output_instruction()
        + mode_hint
        + role_hint
        + metabolic_hint
        + orchestration_runtime_hint
        + "\n\nКонтекст по пользователю:\n"
        + context_str
        + kb_hint
        + offline_hint
        + cache_hint
        + learned_hint
    )

    messages = [{"role": "system", "content": system_content}]
    recent_history = chat_history[-10:] if chat_history else []
    for m in recent_history:
        messages.append({"role": m.get("role", "user"), "content": (m.get("content") or "")[:4000]})
    messages.append({"role": "user", "content": (effective_user_message or "").strip()[:3000]})
    prompt_chars = sum(len(str((m or {}).get("content") or "")) for m in messages)

    settings = get_settings()
    response_text = ""
    response_simple: Optional[str] = None
    llm_structured_payload: Optional[dict[str, Any]] = None
    response_source = "offline_fallback"
    llm_used = False
    worker_used = False
    model_used: Optional[str] = None
    request_id: Optional[str] = None
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    estimated_cost_usd = 0.0

    def _fallback_offline_or_error() -> None:
        nonlocal response_text, response_simple, llm_structured_payload, response_source, llm_used, worker_used, model_used, request_id, prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd
        response_source = "offline_fallback"
        llm_structured_payload = None
        llm_used = False
        worker_used = False
        model_used = None
        request_id = None
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        estimated_cost_usd = 0.0
        if offline_fallback:
            response_text, response_simple = _humanize_offline_answer(
                user_message=effective_user_message,
                offline_formats=offline_formats,
                chat_history=chat_history,
                has_lab_data=documents_count > 0,
            )
        else:
            response_text = (
                "Сейчас не удалось обработать запрос. Попробуйте ещё раз или опишите жалобы подробнее. "
                "Можно зайти в раздел «Симптомы» или «Офлайн-справочник»."
            )

    if offline_priority_mode and complaint_protocol:
        response_text, response_simple = _build_offline_priority_response(
            complaint_protocol=complaint_protocol,
            season=current_season,
        )
        response_source = "offline_priority"

    if offline_priority_mode:
        llm_used = False
        worker_used = False
        model_used = None
        request_id = None
    elif use_learned_instead_of_llm and learned_list:
        response_text = (learned_list[0].get("response") or "").strip()
        response_simple = (learned_list[0].get("response_simple") or response_text[:1200]).strip()
        response_source = "learned_cache"
    elif settings.llm_worker_url:
        try:
            import httpx

            url = f"{settings.llm_worker_url}/chat/completions"
            async with httpx.AsyncClient(timeout=90.0) as client:
                r = await client.post(
                    url,
                    json={
                        "messages": messages,
                        "model": settings.openai_model,
                        "temperature": 0.4,
                        "max_tokens": 800,
                        "response_format": CONSULTATION_JSON_SCHEMA,
                    },
                )
                r.raise_for_status()
                data = r.json()
                response_text = (data.get("content") or "").strip()
                llm_structured_payload = _extract_json_object(response_text)
                if llm_structured_payload:
                    validated = ConsultationStructuredOutput.model_validate(llm_structured_payload)
                    llm_structured_payload = validated.model_dump()
                    response_text = validated.patient_facing_response or validated.patient_summary or response_text
                    response_simple = validated.patient_summary or response_simple
                response_source = "openai_worker"
                llm_used = True
                worker_used = True
                model_used = data.get("model") or settings.openai_model
                request_id = data.get("request_id")
                prompt_tokens = int(data.get("prompt_tokens") or 0)
                completion_tokens = int(data.get("completion_tokens") or 0)
                total_tokens = int(data.get("total_tokens") or 0)
                estimated_cost_usd = _estimate_openai_cost_usd(model_used or "", prompt_tokens, completion_tokens)
        except Exception:
            _fallback_offline_or_error()
    elif settings.openai_api_key:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                temperature=0.4,
                max_tokens=800,
                response_format=CONSULTATION_JSON_SCHEMA,
            )
            response_text = (resp.choices[0].message.content or "").strip()
            llm_structured_payload = _extract_json_object(response_text)
            if llm_structured_payload:
                validated = ConsultationStructuredOutput.model_validate(llm_structured_payload)
                llm_structured_payload = validated.model_dump()
                response_text = validated.patient_facing_response or validated.patient_summary or response_text
                response_simple = validated.patient_summary or response_simple
            response_source = "openai_direct"
            llm_used = True
            worker_used = False
            model_used = settings.openai_model
            request_id = getattr(resp, "id", None)
            usage = getattr(resp, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
            estimated_cost_usd = _estimate_openai_cost_usd(model_used or "", prompt_tokens, completion_tokens)
        except Exception:
            _fallback_offline_or_error()
    else:
        if offline_fallback:
            response_text, response_simple = _humanize_offline_answer(
                user_message=effective_user_message,
                offline_formats=offline_formats,
                chat_history=chat_history,
                has_lab_data=documents_count > 0,
            )
        else:
            followup = suggest_clarifying_questions(
                user_message=effective_user_message or "",
                chat_history=chat_history or [],
                has_lab_data=documents_count > 0,
                max_questions=MAX_QUESTIONS_PER_TURN,
            )
            if is_food_discomfort_triage:
                response_text = (
                    "Помогу разобраться. Лёгкая тошнота или плохое самочувствие после жареных семечек (или жирной пищи) "
                    "чаще всего связаны с раздражением желудка жирной пищей, перееданием, чувствительностью к маслу или реакцией желчного пузыря, "
                    "реже — с пищевой непереносимостью. Чтобы уточнить причину, задам несколько вопросов."
                )
                if followup:
                    response_text += "\n\n" + "\n".join(followup)
                response_simple = "Помогу разобраться. Задам несколько уточняющих вопросов о симптомах после еды."
            else:
                response_text = "Понимаю вас. Сейчас данных маловато для точного ответа."
                if followup:
                    response_text += "\n\nУточните, пожалуйста:\n- " + "\n- ".join(followup)
                else:
                    response_text += "\n\nЧто беспокоит, как давно и что уже пробовали?"
                response_simple = response_text

    _clar_done_pre = count_assistant_clarification_rounds(chat_history or [])
    if isinstance(llm_structured_payload, dict):
        fq_raw = llm_structured_payload.get("follow_up_questions") or []
        if _clar_done_pre >= MAX_CLARIFICATION_ROUNDS:
            llm_structured_payload["follow_up_questions"] = []
        elif isinstance(fq_raw, list) and len(fq_raw) > 1:
            first_q = str(fq_raw[0]).strip()
            llm_structured_payload["follow_up_questions"] = [first_q] if first_q else []

    intent = (extract_symptoms_nutrition_activity_intent(effective_user_message or "").get("intent") or "general")
    filtered = filter_response_by_relevance(response_text or "", effective_user_message or "", intent)
    if filtered.get("is_sufficient"):
        response_text = (filtered.get("filtered_text") or response_text).strip()
    else:
        followup = suggest_clarifying_questions(
            user_message=effective_user_message or "",
            chat_history=chat_history or [],
            has_lab_data=documents_count > 0,
            max_questions=MAX_QUESTIONS_PER_TURN,
        )
        response_text = filtered.get("insufficient_message") or "У меня недостаточно данных для ответа."
        if followup:
            response_text += "\n\nЧтобы ответ был точнее, уточните:\n- " + "\n- ".join(followup)

    raw_response_text = response_text
    wants_questions = _requests_more_questions(user_message or "")
    heuristic_followups = suggest_clarifying_questions(
        user_message=effective_user_message or "",
        chat_history=chat_history or [],
        has_lab_data=documents_count > 0,
        max_questions=MAX_QUESTIONS_PER_TURN,
    )

    consultation_state = build_consultation_state(
        user_message=effective_user_message or "",
        chat_history=chat_history or [],
        profile=profile,
        structured=llm_structured_payload
        or {
            "severity": "YELLOW",
            "chief_complaint": effective_user_message or "",
        },
        complaint_protocol=complaint_protocol,
        complaint_meta=complaint_defaults,
        strict_protocol=strict_protocol,
        has_lab_data=documents_count > 0,
    )

    save_consultation_state(
        user_id,
        {
            "complaint": consultation_state.complaint,
            "protocol_source": consultation_state.protocol_source,
            "severity": consultation_state.severity,
            "required_fields": consultation_state.required_fields,
            "collected_facts": consultation_state.collected_facts,
            "missing_fields": consultation_state.missing_fields,
            "last_follow_up_question": consultation_state.last_follow_up_question,
            "can_conclude": consultation_state.can_conclude,
            "suggested_labs": consultation_state.suggested_labs,
            "nutrition_recommendations": consultation_state.nutrition_recommendations,
            "physical_exercise_prevention_rehabilitation": consultation_state.physical_exercise_prevention_rehabilitation,
            "dialogue_meta": consultation_state.dialogue_meta,
            "labs_meta": consultation_state.labs_meta,
            "seasonality": consultation_state.seasonality,
            "market_signal_cluster": consultation_state.market_signal_cluster,
            "public_source_basis": consultation_state.public_source_basis,
        },
        subject_id=subject_id,
    )

    consultation_case = None
    if consultation_state.labs_meta.get("ask_dialog_to_attach"):
        case_name = _consultation_case_name(consultation_state.complaint)
        consultation_case = get_or_create_named_lab_case(user_id, case_name, subject_id=subject_id)
        save_consultation_state(
            user_id,
            {
                "consultation_case_id": consultation_case.get("id"),
                "consultation_case_name": consultation_case.get("name"),
            },
            subject_id=subject_id,
        )

    followup_questions = list(heuristic_followups)
    medical_core_followups = [
        str(x).strip()
        for x in (
            (medical_core_enrichment.get("red_flag_questions") or [])
            + (medical_core_enrichment.get("must_ask") or [])
        )
        if str(x).strip()
    ][:MAX_QUESTIONS_PER_TURN]
    graph_followups = [
        str(x).strip() for x in ((symptom_cause_context or {}).get("adaptive_questions") or []) if str(x).strip()
    ]
    severity_followups = [
        str(x).strip() for x in ((symptom_severity_context or {}).get("followup_questions") or []) if str(x).strip()
    ]
    reasoning_graph_followups = [
        str(x).strip() for x in ((reasoning_graph_context or {}).get("adaptive_questions") or []) if str(x).strip()
    ]
    if graph_followups or severity_followups or reasoning_graph_followups:
        merged_followups: list[str] = []
        seen_followups: set[str] = set()
        for item in reasoning_graph_followups + medical_core_followups + severity_followups + graph_followups + followup_questions:
            key = item.lower()
            if key in seen_followups:
                continue
            seen_followups.add(key)
            merged_followups.append(item)
        followup_questions = merged_followups[:MAX_QUESTIONS_PER_TURN]
    elif medical_core_followups:
        followup_questions = medical_core_followups[:MAX_QUESTIONS_PER_TURN]
    followup_questions = _filter_repeat_followups(
        followup_questions,
        user_message=effective_user_message or "",
        chat_history=chat_history or [],
    )[:MAX_QUESTIONS_PER_TURN]
    if selector_question:
        followup_questions = _filter_repeat_followups(
            [selector_question],
            user_message=effective_user_message or "",
            chat_history=chat_history or [],
        )[:MAX_QUESTIONS_PER_TURN]
    elif selector_state:
        remembered_q = selector_followup_question({"medical_core_selector": selector_state})
        if remembered_q:
            followup_questions = _filter_repeat_followups(
                [remembered_q],
                user_message=effective_user_message or "",
                chat_history=chat_history or [],
            )[:MAX_QUESTIONS_PER_TURN]

    diagnostic_assessment = build_diagnostic_assessment(
        symptom_context=symptom_context,
        nutrition_context=nutrition_context,
        lab_context=lab_context,
        top_k=5,
    )

    diagnostic_profile = diagnostic_assessment.get("clinical_profile") or "general"
    ranked_diseases = diagnostic_assessment.get("ranked_diseases") or []
    triage_data = diagnostic_assessment.get("triage") or {}
    top_hypotheses = ranked_diseases[:3]

    # анти-паника
    if triage_data.get("triage") == "urgent" and not triage_data.get("red_flags"):
        triage_data["triage"] = "routine"

    followup_severity = "RED" if str(triage_data.get("triage") or "").lower() == "urgent" else "YELLOW"
    candidate_followups = [str(q).strip() for q in (followup_questions or []) if str(q).strip()][:3]
    if selector_payload.get("best_question"):
        best_q = str(selector_payload.get("best_question") or "").strip()
        if best_q and best_q not in candidate_followups:
            candidate_followups.insert(0, best_q)
    try:
        gate_v2 = evaluate_followup_turn(
            user_text=effective_user_message or "",
            followup_state=followup_state_obj.to_dict(),
        )
        gate_action = str(gate_v2.get("action") or "").strip().lower()
        gate_state = gate_v2.get("followup_state") or {}
        if isinstance(gate_state, dict) and gate_state:
            followup_state_obj = FollowupState.from_dict(gate_state)

        followup_decision_payload = {
            "answer_quality": {
                "status": gate_v2.get("quality_status"),
                "score": gate_v2.get("quality_score"),
            },
            "quality_gate_action": gate_action or "continue",
        }

        if gate_action == "reask":
            override_q = str(gate_v2.get("assistant_override_text") or "").strip()
            if override_q:
                followup_questions = [override_q]
        elif gate_action == "urgent":
            triage_data["triage"] = "urgent"
            triage_data["reason"] = str(gate_v2.get("assistant_override_text") or triage_data.get("reason") or "Обнаружены признаки потенциально опасного состояния.")
            followup_questions = []
        else:
            if gate_action == "accept_and_flag_case_shift":
                case_shift_candidate = True
            followup_decision = decide_followup_turn(
                user_message=effective_user_message or "",
                followup_state=followup_state_obj,
                candidate_questions=candidate_followups,
                turn_id="",
                question_source="medical_core_selector",
                selector_payload=selector_payload,
                red_flags_present=bool(triage_data.get("red_flags")),
                severity=followup_severity,
            )
            followup_decision_payload.update(followup_decision.to_dict())
            followup_state_obj = FollowupState.from_dict(followup_decision.followup_state or followup_state_obj.to_dict())
            if followup_decision.action in {"ask", "reask"} and str(followup_decision.question or "").strip():
                followup_questions = [str(followup_decision.question).strip()]
            elif followup_decision.action == "finalize":
                followup_questions = []
            elif followup_decision.action == "urgent":
                triage_data["triage"] = "urgent"
                triage_data["reason"] = str(triage_data.get("reason") or "Обнаружены признаки потенциально опасного состояния.")
    except Exception:
        followup_decision_payload = {}

    # Seventh-stage confidence gate: decide stop-rules and best next slot.
    try:
        triage_level = str(triage_data.get("triage") or "").strip().lower()
        mc_domain = str((medical_core_primary or {}).get("domain") or "").strip().lower() if isinstance(medical_core_primary, dict) else ""
        mc_category = str((medical_core_primary or {}).get("category") or "").strip() if isinstance(medical_core_primary, dict) else ""
        confidence_input_state: dict[str, Any] = {
            "selector_complaint": str(selector_payload.get("entry_id") or selector_payload.get("entry_name") or consultation_state.complaint or ""),
            "complaint_key": str(selector_payload.get("complaint_key") or ""),
            "current_branch": str(selector_payload.get("entry_name") or ""),
            "domain": mc_domain,
            "category": mc_category,
            "triage_level": triage_level,
            "urgent": triage_level == "urgent",
        }
        confidence_gate = run_confidence_gate(
            orchestrator_state=confidence_input_state,
            followup_state=followup_state_obj.to_dict(),
        )
        confidence_gate_payload = {
            "confidence": confidence_gate.get("confidence"),
            "should_stop": bool(confidence_gate.get("should_stop")),
            "should_ask_one_more": bool(confidence_gate.get("should_ask_one_more")),
            "next_best_slot": confidence_gate.get("next_best_slot"),
            "reasons": list(confidence_gate.get("reasons") or []),
            "assistant_hint": confidence_gate.get("assistant_hint"),
        }
        overlay = confidence_gate.get("orchestrator_state") or {}
        if isinstance(overlay, dict):
            confidence_state_overlay = {
                "confidence_gate": dict(overlay.get("confidence_gate") or {}),
                "followup_ready_for_summary": bool(overlay.get("followup_ready_for_summary")),
            }
            maybe_followup = overlay.get("medical_core_followup") or {}
            if isinstance(maybe_followup, dict) and maybe_followup:
                followup_state_obj = FollowupState.from_dict(maybe_followup)
        followup_ready_for_summary = bool(confidence_state_overlay.get("followup_ready_for_summary"))
        if confidence_gate_payload.get("should_stop"):
            followup_questions = []
        elif confidence_gate_payload.get("should_ask_one_more") and not followup_questions:
            slot = str(confidence_gate_payload.get("next_best_slot") or "").strip().lower()
            next_q = CONFIDENCE_SLOT_QUESTION.get(slot)
            if next_q:
                followup_questions = [next_q]
    except Exception:
        confidence_gate_payload = {}
        confidence_state_overlay = {}
        followup_ready_for_summary = False

    clinical_profiles = []
    if top_hypotheses:
        clinical_profiles = [
            {
                "name": h.get("name") or "",
                "description": h.get("explanation") or "",
            }
            for h in top_hypotheses
            if h.get("name")
        ]
    funnel_top = [str(x).strip() for x in (relevance_funnel.get("top_labels") or []) if str(x).strip()]
    if funnel_top:
        existing_by_name = {
            str((cp or {}).get("name") or "").strip().lower(): cp
            for cp in clinical_profiles
            if str((cp or {}).get("name") or "").strip()
        }
        filtered_profiles: list[dict[str, Any]] = []
        for label in funnel_top[:3]:
            keep = existing_by_name.get(label.lower())
            if keep:
                filtered_profiles.append(keep)
            else:
                filtered_profiles.append({"name": label, "description": "Отфильтровано воронкой релевантности."})
        clinical_profiles = filtered_profiles

    force_questions = (
        wants_questions
        or (not _has_minimum_clinical_context(effective_user_message, documents_count > 0))
        or (not consultation_state.can_conclude)
    )
    if followup_ready_for_summary:
        force_questions = False
        followup_questions = []
    if _clar_done_pre >= MAX_CLARIFICATION_ROUNDS:
        force_questions = False
        followup_questions = []

    if followup_ready_for_summary:
        try:
            safe_bundle = render_safe_summary_bundle(
                user_message=effective_user_message or "",
                top_hypotheses=top_hypotheses,
                structured_payload=llm_structured_payload if isinstance(llm_structured_payload, dict) else {},
                guidance_context=medical_core_guidance_context,
                triage_data=triage_data,
                followup_state=followup_state_obj.to_dict(),
            )
            response_text = str(safe_bundle.get("patient_facing_response") or response_text or "").strip()
            response_simple = str(safe_bundle.get("patient_summary") or response_simple or response_text).strip()
            response_source = "safe_summary_renderer"
            followup_questions = []
            merged_payload = dict(llm_structured_payload or {})
            merged_payload.update(safe_bundle)
            merged_payload["followup_ready_for_summary"] = True
            llm_structured_payload = merged_payload
        except Exception:
            pass

    reasoning_output = build_medical_reasoning_output(
        user_message=effective_user_message or "",
        complaint_protocol=complaint_protocol,
        food_trigger_context=food_trigger_context,
        lab_context=lab_context,
        symptom_severity_context=symptom_severity_context,
        followup_questions=followup_questions,
        reasoning_graph_context=reasoning_graph_context,
        chat_history=chat_history or [],
    )
    reasoning_mode = str((reasoning_output or {}).get("reasoning_mode") or "").strip().lower()
    dynamic_intake_mode = bool((reasoning_output or {}).get("dynamic_intake_mode"))
    if not followup_ready_for_summary:
        if dynamic_intake_mode:
            force_questions = False
            response_text = render_short_answer_from_reasoning(reasoning_output)
            response_source = "reasoning_engine_dynamic"
        elif reasoning_mode == "focused_questions_mode":
            force_questions = True
            rq = [str(x).strip() for x in ((reasoning_output or {}).get("must_ask_next") or []) if str(x).strip()]
            if rq:
                followup_questions = rq[:MAX_QUESTIONS_PER_TURN]
        elif reasoning_mode in ("obvious_pattern", "complaint_lab_reasoning"):
            force_questions = False
            response_text = render_short_answer_from_reasoning(reasoning_output)
            response_source = "reasoning_engine"
        elif reasoning_mode == "urgent_mode":
            force_questions = False
            response_text = render_short_answer_from_reasoning(reasoning_output)
            response_source = "reasoning_engine_urgent"
            triage_data["triage"] = "urgent"
            triage_data["reason"] = "Обнаружены признаки потенциально опасного состояния."
            triage_data["red_flags"] = (reasoning_output or {}).get("red_flags_detected") or []

    if not dynamic_intake_mode and not followup_ready_for_summary:
        response_text = _format_max_relevance_answer(
            user_message=effective_user_message,
            base_text=response_text,
            force_questions=force_questions,
            questions=followup_questions,
            clinical_profiles=clinical_profiles,
            profile=profile,
            strict_protocol=strict_protocol,
            complaint_protocol=complaint_protocol,
            chat_history=chat_history or [],
        )

    response_text = _apply_orchestrator_rules(
        base_text=response_text,
        consultation_state=consultation_state,
        has_lab_data=documents_count > 0,
        force_questions=force_questions,
        followup_questions=followup_questions,
        user_message=effective_user_message or "",
    )

    if CONCLUSION_MARKER in (raw_response_text or "") and not force_questions:
        recommendation_part = (raw_response_text or "").split(CONCLUSION_MARKER, 1)[-1].strip()
        recommendation_part = re.sub(r"^\s*\[CONCLUSION\]\s*", "", recommendation_part).strip()
        if not recommendation_part:
            recommendation_part = "Рекомендуется обратиться к врачу для очного осмотра."

        recommendation_part = _format_max_relevance_answer(
            user_message=effective_user_message,
            base_text=recommendation_part,
            force_questions=False,
            questions=[],
            clinical_profiles=clinical_profiles,
            profile=profile,
            strict_protocol=strict_protocol,
            complaint_protocol=complaint_protocol,
            chat_history=chat_history or [],
        )

        consultation_summary = _summarize_for_report(chat_history, effective_user_message, symptom_entries)

        final_red_flags = list(triage_data.get("red_flags") or [])
        final_when_urgent = list((llm_structured_payload or {}).get("when_urgent") or [])

        triage_reason = triage_data.get("reason")
        if triage_reason:
            final_when_urgent = [triage_reason] + final_when_urgent

        final_severity = str(
            (llm_structured_payload or {}).get("severity")
            or consultation_state.severity
            or "YELLOW"
        )
        if str(triage_data.get("triage") or "").lower() == "urgent":
            final_severity = "RED"

        final_structured = _build_structured_payload(
            response_text=recommendation_part,
            response_simple=response_simple or recommendation_part,
            effective_user_message=effective_user_message,
            severity=final_severity,
            red_flags_present=bool(final_red_flags),
            follow_up_questions=[],
            clinical_profiles=clinical_profiles,
            when_urgent=final_when_urgent,
            parsed_payload=llm_structured_payload,
            preferred_labs=consultation_state.suggested_labs,
            symptom_context=symptom_context,
            nutrition_context=nutrition_context,
            lab_context=lab_context,
            symptom_cause_context=symptom_cause_context,
            symptom_severity_context=symptom_severity_context,
            relevance_funnel_context=relevance_funnel,
            reasoning_context=reasoning_output,
        )

        report = build_consultation_final_report(
            case_summary=consultation_summary,
            severity=str(final_structured.get("severity") or consultation_state.severity or "YELLOW"),
            structured=final_structured,
            orchestrator_state=consultation_state.model_dump(),
            title="Итог консультации",
        )

        from app.services.user_store import save_consultation_report, save_severity

        report_id = save_consultation_report(user_id, report, subject_id=subject_id)
        sev = (report.get("severity_index") or "GREEN").upper()
        if sev in ("GREEN", "YELLOW", "RED"):
            save_severity(user_id, sev, "consultation")

        save_to_response_cache(
            user_id,
            effective_user_message,
            recommendation_part,
            report.get("user_summary"),
        )
        await _ensure_min_delay(t0)
        return _result(
            response=recommendation_part,
            response_simple=report.get("user_summary"),
            conclusion=True,
            report_id=report_id,
            report=report,
            suggest_pdf=True,
            severity=sev,
            structured=final_structured,
            llm_used=llm_used,
            response_source=response_source,
            model_used=model_used,
            worker_used=worker_used,
            request_id=request_id,
            orchestrator_state=consultation_state.model_dump(),
            consultation_case=consultation_case,
            prompt_chars=prompt_chars,
            response_chars=len(recommendation_part or ""),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
            symptom_context_data=symptom_context,
            nutrition_context=nutrition_context,
            lab_context_data=lab_context,
        )

    if response_text:
        response_text = _inject_food_trigger_block(
            response_text,
            food_trigger_context,
            effective_user_message,
        )
        if response_simple:
            response_simple = _inject_food_trigger_block(
                response_simple,
                food_trigger_context,
                effective_user_message,
            )
        save_to_response_cache(user_id, effective_user_message, response_text, response_simple)
        save_to_learned = bool(response_text.strip()) and (
            llm_used or response_source in ("offline_fallback", "offline_priority", "learned_cache")
        )
        if save_to_learned:
            hypotheses = []
            if isinstance(llm_structured_payload, dict):
                hypotheses = (
                    llm_structured_payload.get("hypotheses")
                    or llm_structured_payload.get("diagnosis")
                    or []
                )[:10]
                if isinstance(hypotheses, str):
                    hypotheses = [hypotheses]
            save_learned_response(
                effective_user_message or "",
                response_text,
                response_simple=response_simple,
                hypotheses=hypotheses if hypotheses else None,
            )

    triage_level = str(triage_data.get("triage") or "").lower()

    if triage_level == "urgent":
        severity = "RED"
    elif followup_questions:
        severity = "YELLOW"
    else:
        severity = "GREEN"

    await _ensure_min_delay(t0, _resolve_min_delay_sec(effective_user_message, response_text))
    return _result(
        response=response_text,
        response_simple=response_simple,
        severity=severity,
        structured=_build_structured_payload(
            response_text=response_text,
            response_simple=response_simple,
            effective_user_message=effective_user_message,
            severity=severity,
            red_flags_present=bool(triage_data.get("red_flags")),
            follow_up_questions=followup_questions,
            clinical_profiles=clinical_profiles,
            when_urgent=[triage_data.get("reason")] if triage_data.get("reason") else [],
            parsed_payload=llm_structured_payload,
            preferred_labs=consultation_state.suggested_labs,
            symptom_context=symptom_context,
            nutrition_context=nutrition_context,
            lab_context=lab_context,
            food_trigger_context=food_trigger_context,
            multidisciplinary_context=multidisciplinary_context,
            symptom_cause_context=symptom_cause_context,
            symptom_severity_context=symptom_severity_context,
            relevance_funnel_context=relevance_funnel,
            reasoning_context=reasoning_output,
        ),
        llm_used=llm_used,
        response_source=response_source,
        model_used=model_used,
        worker_used=worker_used,
        request_id=request_id,
        orchestrator_state=consultation_state.model_dump(),
        consultation_case=consultation_case,
        prompt_chars=prompt_chars,
        response_chars=len(response_text or ""),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
        symptom_context_data=symptom_context,
        nutrition_context=nutrition_context,
        lab_context_data=lab_context,
    )