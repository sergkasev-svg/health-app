"""
Clinical Orchestrator Layer: единый пайплайн медицинского ответа.
Ввод → симптомы → red flags → документы → анализы → правила → гипотезы → фильтр → decision engine → ответ.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.knowledge.filters.diagnosis_filter import is_relevant_diagnosis
from app.services.diagnostic_ranking_engine import filter_ranked_hypotheses_for_labs_only
from app.services.lab_postprocess import postprocess_lab_analysis_for_user
from app.services.mikhail_decision_engine import (
    DecisionInput,
    DecisionOutput,
    MikhailDecisionEngine,
)
from app.services.mikhail_memory import LabRecord, MikhailSessionMemory
from app.services.mikhail_memory_store import MikhailMemoryStore
from app.services.mikhail_followup_engine import MikhailFollowUpEngine
from app.services.lab_trend_analyzer import summarize_trends
from app.services.mikhail_care_plan_engine import MikhailCarePlanEngine, build_care_plan_message
from app.services.care_plan_models import CarePlan
from app.services.physician_report_generator import PhysicianReportGenerator
from app.services.physician_report_formatter import format_physician_report
from app.services.entitlement_service import EntitlementService
from app.services.product_orchestrator import ProductOrchestrator
from app.services.onboarding_store import OnboardingStore
from app.services.onboarding_engine import OnboardingEngine
from app.services.conversion_signals import collect_conversion_signals, detect_first_value
from app.services.conversion_engine import ConversionEngine
from app.services.product_analytics_events import track_product_event, EVENT_FIRST_VALUE_REACHED
from app.services.quality_logger import QualityLogger
from app.services.quality_models import compute_session_quality_score
from app.services.symptom_parser import parse_symptoms
from app.core.settings import get_settings
from app.services.clinical_routing_engine import ClinicalRoutingEngine, route_to_lab_type_alias
from app.services.clinical_routing_models import ClinicalRouteDecision
from app.services.route_hypothesis_filter import filter_hypotheses_by_route, user_hypothesis_strings
from app.services.route_question_filter import filter_questions_by_route
from app.services.route_output_validator import validate_route_consistency


def _clinical_routing_enabled() -> bool:
    try:
        return bool(get_settings().ENABLE_CLINICAL_ROUTING_ENGINE)
    except Exception:
        return False


def _render_hints_for_route(primary_route: str) -> dict[str, Any]:
    organic = primary_route == "organic_acids_route"
    templates: dict[str, str] = {
        "organic_acids_route": "organic_acids_physician_table",
        "cbc_route": "cbc_physician_table",
        "thyroid_route": "thyroid_physician_table",
        "urine_general_route": "urine_physician_table",
        "lipid_route": "lipid_physician_table",
        "generic_safe_route": "generic_safe",
        "emergency_route": "emergency",
        "physician_report_only_route": "physician_report_only",
    }
    return {
        "report_template": templates.get(primary_route, "generic_safe"),
        "use_tables": organic or primary_route in ("cbc_route", "thyroid_route", "urine_general_route", "lipid_route"),
        "highlight_abnormal_only": organic,
        "routing_badge": primary_route.replace("_route", "").replace("_", " "),
    }


# --- Red flags для оркестратора (совпадают с decision engine) ---
ORCHESTRATOR_RED_FLAGS = [
    "боль в груди",
    "одышка в покое",
    "потеря сознания",
    "перекос лица",
    "кровь в стуле",
    "кровь в рвоте",
    "чёрный стул",
    "черный стул",
    "судороги",
    "очень сильная боль в животе",
    "сильная боль в животе",
    "выраженная слабость",
    "ухудшение состояния",
    "сатурация низкая",
    "обморок",
]

FALLBACK_QUESTIONS = [
    "Что именно вас беспокоит?",
    "Как давно появились симптомы?",
    "Есть ли результаты анализов или обследований?",
]

FALLBACK_MESSAGE = (
    "Пока данных недостаточно, чтобы сделать полезный вывод. "
    "Опишите симптомы и, если есть, загрузите анализы или обследования."
)


@dataclass
class OrchestratorInput:
    """Вход оркестратора."""
    user_text: str = ""
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    symptoms: List[str] = field(default_factory=list)
    uploaded_files: List[Dict[str, Any]] = field(default_factory=list)
    raw_lab_rows: List[Dict[str, Any]] = field(default_factory=list)
    profile: Dict[str, Any] = field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    locale: Optional[str] = None
    channel: Optional[str] = None
    initial_hypotheses: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class OrchestratorContext:
    """Контекст между этапами."""
    normalized_symptoms: List[str] = field(default_factory=list)
    red_flags: List[str] = field(default_factory=list)
    lab_rows: List[Dict[str, Any]] = field(default_factory=list)
    structured_lab_report: Optional[Dict[str, Any]] = None
    doctor_report: Optional[Dict[str, Any]] = None
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    filtered_hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    user_hypotheses: List[str] = field(default_factory=list)
    requested_labs: List[str] = field(default_factory=list)
    parsed_documents: List[Dict[str, Any]] = field(default_factory=list)
    lab_type: Optional[str] = None  # organic_acids, cbc, thyroid, unknown
    knowledge_hits: List[Dict[str, Any]] = field(default_factory=list)
    decision_state: Optional[str] = None
    urgency: Optional[str] = None
    decision_output: Optional[DecisionOutput] = None
    memory: Optional[Any] = None
    continuity_summary: Optional[Dict[str, Any]] = None
    care_plan: Optional[Any] = None
    care_plan_message: Optional[str] = None
    physician_report: Optional[Any] = None
    physician_report_text: Optional[str] = None
    product: Optional[Dict[str, Any]] = None
    onboarding: Optional[Dict[str, Any]] = None
    conversion: Optional[Dict[str, Any]] = None
    debug: Dict[str, Any] = field(default_factory=dict)
    route_decision: Optional[ClinicalRouteDecision] = None


@dataclass
class OrchestratorOutput:
    """Выход оркестратора для API."""
    ok: bool = True
    state: str = "needs_more_data"
    urgency: str = "low"
    final_user_message: str = ""
    questions: List[str] = field(default_factory=list)
    recommended_labs: List[str] = field(default_factory=list)
    user_report_structured: Optional[Dict[str, Any]] = None
    user_hypotheses: List[str] = field(default_factory=list)
    doctor_report: Optional[Dict[str, Any]] = None
    continuity_summary: Optional[Dict[str, Any]] = None
    care_plan: Optional[Dict[str, Any]] = None
    care_plan_message: Optional[str] = None
    physician_report: Optional[Dict[str, Any]] = None
    physician_report_text: Optional[str] = None
    product: Optional[Dict[str, Any]] = None
    launch: Optional[Dict[str, Any]] = None
    onboarding: Optional[Dict[str, Any]] = None
    conversion: Optional[Dict[str, Any]] = None
    debug: Dict[str, Any] = field(default_factory=dict)
    routing: Optional[Dict[str, Any]] = None
    render_hints: Optional[Dict[str, Any]] = None


def _float_or_none(x: Any) -> Optional[float]:
    """Безопасно привести к float или None."""
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _load_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    """Безопасно загрузить JSON. Не падать при отсутствии файла."""
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


class ClinicalOrchestrator:
    """
    Единый пайплайн: пользовательский ввод → извлечение симптомов → анализ файлов/анализов
    → правила → decision engine → безопасный ответ Михаила.

    Жёсткий порядок: clinical routing (_run_clinical_routing) выполняется ДО postprocess лаборатории,
    ранжирования гипотез, decision engine и physician report — ветка задаётся до «объяснений».
    """

    def run(self, payload: OrchestratorInput) -> OrchestratorOutput:
        """Пайплайн: normalize → memory → symptoms → red_flags → parse_docs → **routing** → labs → knowledge_rules → rank → filter → decision → care_plan → physician_report → followup → output."""
        context = OrchestratorContext()
        try:
            self._normalize_input(payload, context)
            self._load_memory(payload, context)
            self._extract_symptoms(payload, context)
            self._detect_red_flags(payload, context)
            self._parse_uploaded_documents(payload, context)
            self._run_clinical_routing(payload, context)
            self._process_labs(payload, context)
            self._merge_memory(payload, context)
            self._apply_knowledge_rules(context)
            self._rank_hypotheses(payload, context)
            self._filter_hypotheses(context)
            self._run_decision_engine(payload, context)
            self._build_care_plan(context)
            self._build_physician_report(payload, context)
            self._update_followup_and_questions(payload, context)
            self._compose_final_message(context)
            self._enrich_message_with_continuity(context)
            self._build_continuity_summary(context)
            self._save_memory(payload, context)
            output = self._build_output(context)
            output = self._apply_product_gates(payload, context, output)
            output = self._apply_onboarding_conversion(payload, context, output)
            self._log_quality(payload, context, output)
            return output
        except Exception as e:
            context.debug["orchestrator_error"] = str(e)
            return self._build_fallback_output(context)

    def _load_memory(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Загрузить память сессии. При ошибке — пустая память для текущей сессии."""
        try:
            store = MikhailMemoryStore()
            context.memory = store.load(payload.user_id, payload.session_id)
        except Exception:
            context.memory = MikhailSessionMemory(session_id=payload.session_id, user_id=payload.user_id)

    def _merge_memory(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Объединить текущие данные с памятью: симптомы, лабы, state (позже)."""
        if not context.memory:
            return
        try:
            store = MikhailMemoryStore()
            lab_list = []
            for row in (context.lab_rows or []):
                if isinstance(row, dict):
                    lab_list.append(LabRecord(
                        marker_name=str(row.get("marker_name") or row.get("title") or row.get("name") or "").strip(),
                        value=_float_or_none(row.get("value")),
                        unit=row.get("unit"),
                        ref_low=_float_or_none(row.get("ref_low")),
                        ref_high=_float_or_none(row.get("ref_high")),
                        flag=row.get("flag"),
                        date=None,
                        source_file=row.get("source_file"),
                    ))
            context.memory = store.merge(context.memory, {
                "symptoms": context.normalized_symptoms or [],
                "labs": lab_list,
                "source": "orchestrator",
            })
        except Exception:
            pass

    def _build_care_plan(self, context: OrchestratorContext) -> None:
        """Построить план действий по state и pathway; сохранить в context."""
        try:
            engine = MikhailCarePlanEngine()
            ctx_dict = {
                "structured_lab_report": context.structured_lab_report,
                "lab_rows": context.lab_rows,
                "normalized_symptoms": context.normalized_symptoms,
            }
            plan = engine.build_plan(context.decision_output, ctx_dict, context.memory)
            context.care_plan = plan
            context.care_plan_message = build_care_plan_message(plan)
        except Exception:
            context.care_plan = None
            context.care_plan_message = None

    def _build_physician_report(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Собрать врачебный отчёт из decision_output, context и memory."""
        try:
            ctx_dict = {
                "normalized_symptoms": context.normalized_symptoms,
                "lab_rows": context.lab_rows,
                "structured_lab_report": context.structured_lab_report,
                "red_flags": context.red_flags,
                "profile": getattr(payload, "profile", None) or {},
            }
            gen = PhysicianReportGenerator()
            report = gen.generate(context.decision_output, ctx_dict, context.memory)
            context.physician_report = report
            context.physician_report_text = format_physician_report(report)
        except Exception:
            context.physician_report = None
            context.physician_report_text = None

    def _update_followup_and_questions(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Обновить follow-up план и заменить questions на те, что ещё не задавали."""
        if not context.decision_output:
            return
        try:
            followup = MikhailFollowUpEngine()
            if context.memory:
                context.memory.follow_up_plan = followup.update_plan(
                    context.memory, context.decision_output,
                    {"structured_lab_report": context.structured_lab_report},
                )
                next_q = followup.get_next_questions(context.memory, context.decision_output)
                if next_q is not None:
                    context.decision_output.questions = next_q[:3]
            else:
                context.decision_output.questions = (context.decision_output.questions or [])[:3]
        except Exception:
            context.decision_output.questions = (context.decision_output.questions or [])[:3]
        if _clinical_routing_enabled() and context.route_decision and context.decision_output:
            qs = context.decision_output.questions or []
            context.decision_output.questions = filter_questions_by_route(qs, context.route_decision)
            val = validate_route_consistency(
                context.route_decision,
                context.user_hypotheses or [],
                context.decision_output.questions or [],
            )
            context.debug["route_validation"] = val

    def _enrich_message_with_continuity(self, context: OrchestratorContext) -> None:
        """Добавить одну короткую фразу о динамике, если есть тренды."""
        if not context.memory or not context.decision_output or not context.decision_output.final_user_message:
            return
        try:
            trends = summarize_trends(context.memory)
            summary = trends.get("summary") or []
            if not summary:
                return
            phrase = "По сравнению с прошлым анализом: " + "; ".join(summary[:2]) + "."
            if len(phrase) < 120 and phrase not in (context.decision_output.final_user_message or ""):
                context.decision_output.final_user_message = (context.decision_output.final_user_message or "").strip() + "\n\n" + phrase
        except Exception:
            pass

    def _build_continuity_summary(self, context: OrchestratorContext) -> None:
        """Собрать continuity_summary: known_symptoms, pending_questions, pending_labs, recent_trends, next_step."""
        try:
            if context.memory:
                followup = MikhailFollowUpEngine()
                mon = followup.get_monitoring_summary(context.memory)
                trends = summarize_trends(context.memory)
                context.continuity_summary = {
                    "known_symptoms": mon.get("known_symptoms") or [],
                    "pending_questions": mon.get("pending_questions") or [],
                    "pending_labs": mon.get("pending_labs") or [],
                    "recent_trends": trends.get("summary") or [],
                    "next_step": mon.get("next_step"),
                }
            else:
                context.continuity_summary = {
                    "known_symptoms": [],
                    "pending_questions": [],
                    "pending_labs": [],
                    "recent_trends": [],
                    "next_step": None,
                }
        except Exception:
            context.continuity_summary = {}

    def _save_memory(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Сохранить память после обновления state, hypotheses, asked_questions."""
        if not context.memory:
            return
        try:
            if context.decision_output:
                if context.decision_output.questions:
                    from app.services.mikhail_memory import AskedQuestionRecord
                    for q in context.decision_output.questions[:3]:
                        if q and not any((a.question or "").strip().lower() == (q or "").strip().lower() for a in context.memory.asked_questions):
                            context.memory.asked_questions.append(AskedQuestionRecord(question=(q or "").strip(), answered=False))
                if context.decision_output.state:
                    context.memory.prior_states = (context.memory.prior_states or []) + [context.decision_output.state]
                    context.memory.prior_states = context.memory.prior_states[-10:]
                if context.memory.follow_up_plan:
                    pass
            store = MikhailMemoryStore()
            store.save(context.memory)
        except Exception:
            pass

    def _normalize_input(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Trim текста, дедупликация симптомов, нормализация файлов."""
        payload.user_text = (payload.user_text or "").strip()
        seen = set()
        symptoms = []
        for s in payload.symptoms or []:
            t = str(s).strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                symptoms.append(t)
        payload.symptoms = symptoms
        files = []
        for f in payload.uploaded_files or []:
            if isinstance(f, dict):
                files.append({k: (v if v is not None else "") for k, v in f.items()})
            else:
                files.append({"raw": str(f)})
        payload.uploaded_files = files
        payload.raw_lab_rows = payload.raw_lab_rows or []
        payload.profile = payload.profile or {}
        payload.conversation_history = payload.conversation_history or []
        context.debug["normalized"] = True

    def _extract_symptoms(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Извлечь симптомы из payload.symptoms, user_text и последних сообщений."""
        collected: List[str] = []
        for s in payload.symptoms or []:
            t = str(s).strip()
            if t:
                collected.append(t)
        text = payload.user_text or ""
        if text:
            parsed = parse_symptoms(text)
            for n in getattr(parsed, "normalized_symptoms", []) or []:
                if n and n not in collected:
                    collected.append(n)
            primary = getattr(parsed, "primary_symptom", None)
            if primary and primary not in collected:
                collected.append(primary)
        for msg in (payload.conversation_history or [])[-5:]:
            if isinstance(msg, dict) and (msg.get("role") or "").lower() == "user":
                part = str(msg.get("content") or msg.get("text") or "").strip()
                if part and len(part) > 3 and part not in collected:
                    parsed = parse_symptoms(part)
                    for n in getattr(parsed, "normalized_symptoms", []) or []:
                        if n and n not in collected:
                            collected.append(n)
        context.normalized_symptoms = collected[:30]
        context.debug["extracted_symptoms"] = context.normalized_symptoms[:15]

    def _detect_red_flags(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Найти красные флаги в user_text и симптомах."""
        text = (payload.user_text or "").lower()
        if context.normalized_symptoms:
            text += " " + " ".join(str(x).lower() for x in context.normalized_symptoms)
        found = []
        for flag in ORCHESTRATOR_RED_FLAGS:
            if flag.lower() in text:
                found.append(flag)
        context.red_flags = list(dict.fromkeys(found))
        context.debug["red_flags"] = context.red_flags

    def _parse_uploaded_documents(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Роутинг документов: cbc, thyroid, biochemical, urine, doctor_report, unknown_document."""
        from app.services.lab_document_router import detect_lab_type

        doc_types = []
        lab_rows = list(payload.raw_lab_rows or [])
        all_text_parts: List[str] = [payload.user_text or ""]
        for f in payload.uploaded_files or []:
            if not isinstance(f, dict):
                context.parsed_documents.append({"type": "unknown_document", "raw": str(f)})
                doc_types.append("unknown_document")
                continue
            content = f.get("content") or f.get("text") or f.get("body") or f.get("extracted_text") or ""
            all_text_parts.append(str(content))
            rows = f.get("lab_rows") or f.get("rows") or []
            if rows and isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict) and (r.get("title") or r.get("code") or r.get("name")):
                        lab_rows.append(r)
                doc_types.append("cbc" if any("гемоглобин" in str(r.get("title", "")).lower() or "mch" in str(r.get("title", "")).lower() for r in rows) else "biochemical")
                context.parsed_documents.append({"type": doc_types[-1], "lab_rows_count": len(rows)})
            elif "tsh" in str(content).lower() or "тиреотроп" in str(content).lower():
                doc_types.append("thyroid")
                context.parsed_documents.append({"type": "thyroid"})
            elif "врач" in str(content).lower() and ("заключение" in str(content).lower() or "диагноз" in str(content).lower()):
                doc_types.append("doctor_report")
                context.doctor_report = {"source": "uploaded", "preview": str(content)[:500]}
                context.parsed_documents.append({"type": "doctor_report"})
            else:
                context.parsed_documents.append({"type": "unknown_document"})
                doc_types.append("unknown_document")
        context.lab_rows = lab_rows
        context.debug["parsed_doc_types"] = doc_types
        combined_text = " ".join(all_text_parts)
        context.lab_type = detect_lab_type(combined_text) if combined_text.strip() else None

    def _run_clinical_routing(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Clinical Routing Engine: до гипотез и decision engine."""
        if not _clinical_routing_enabled():
            context.debug["clinical_routing"] = "disabled"
            return
        try:
            engine = ClinicalRoutingEngine()
            pl: Dict[str, Any] = {
                "user_text": payload.user_text or "",
                "uploaded_files": list(payload.uploaded_files or []),
            }
            decision = engine.decide(
                pl,
                context.parsed_documents or [],
                context.normalized_symptoms or [],
                context.red_flags or [],
            )
            context.route_decision = decision
            context.debug["routing"] = decision.to_api_dict()
            context.debug["clinical_routing"] = "enabled"
            # Синхронизация lab_type с authoritative document route для diagnosis_filter
            if not decision.safety_override:
                alias = route_to_lab_type_alias(decision.primary_route)
                if alias:
                    context.lab_type = alias
        except Exception as e:
            context.debug["clinical_routing_error"] = str(e)
            context.route_decision = None

    def _process_labs(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Объединить lab_rows, прогнать через lab postprocess."""
        lab_rows = context.lab_rows or []
        if not lab_rows and payload.raw_lab_rows:
            lab_rows = list(payload.raw_lab_rows)
        if not lab_rows:
            context.debug["lab_processed"] = False
            return
        symptoms = context.normalized_symptoms or []
        profile = payload.profile or {}
        try:
            post = postprocess_lab_analysis_for_user(
                lab_rows=lab_rows,
                doctor_hypotheses=context.hypotheses or [],
                symptoms=symptoms,
                user_profile=profile,
            )
            structured = dict(post.get("user_report_structured") or {})
            structured["hidden_debug"] = post.get("debug_user_report") or {}
            context.structured_lab_report = structured
            raw_hypos = list(post.get("user_hypotheses") or [])[:2]
            if raw_hypos and isinstance(raw_hypos[0], dict):
                context.user_hypotheses = [h.get("name") or h.get("title") or str(h) for h in raw_hypos]
            else:
                context.user_hypotheses = [str(h) for h in raw_hypos]
            context.debug["lab_processed"] = True
            context.debug["lab_debug"] = post.get("debug_user_report")
        except Exception as e:
            context.debug["lab_error"] = str(e)
            context.structured_lab_report = None

    def _apply_knowledge_rules(self, context: OrchestratorContext) -> None:
        """Подключить rule sets; при routing=organic_acids — без широких encyclopedia-индексов (меньше ложных тем)."""
        applied: List[str] = []
        base = Path(__file__).resolve().parent.parent / "knowledge" / "labs"
        rd = getattr(context, "route_decision", None)
        oa_minimal = (
            _clinical_routing_enabled()
            and rd
            and rd.primary_route == "organic_acids_route"
        )

        primary = _load_json_safe(base / "primary_rules.json")
        if primary:
            applied.append("primary_rules")

        if not oa_minimal:
            secondary = _load_json_safe(base / "secondary_indices.json")
            if secondary and (
                not context.structured_lab_report
                or (context.structured_lab_report or {}).get("hidden_debug", {}).get("topics")
            ):
                applied.append("secondary_indices")
            specialized = _load_json_safe(base / "specialized_rules.json")
            if specialized:
                applied.append("specialized_rules")
        else:
            context.debug["knowledge_rules_gated"] = "organic_acids_minimal_no_secondary_specialized"

        context.knowledge_hits = [{"rule_set": r} for r in applied]
        context.debug["applied_rules"] = applied

    def _rank_hypotheses(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Объединить сигналы: лаб. паттерны, симптомы, initial_hypotheses, правила → hypotheses."""
        hypotheses: List[Dict[str, Any]] = []
        report = context.structured_lab_report or {}
        topics = (report.get("hidden_debug") or report.get("debug") or {}).get("topics") or []
        rd = getattr(context, "route_decision", None)
        skip_infection_for_oa = (
            _clinical_routing_enabled()
            and rd
            and rd.primary_route == "organic_acids_route"
        )
        if "iron_deficiency" in topics or "anemia_pattern" in topics:
            hypotheses.append({"name": "Дефицит железа / анемия", "probability": 0.7, "source": "lab_pattern", "supports": ["MCH/Hb/retic"]})
        if "thyroid_hypo" in topics:
            hypotheses.append({"name": "Гипотиреоз", "probability": 0.65, "source": "lab_pattern", "supports": ["TSH high"]})
        if "thyroid_hyper" in topics:
            hypotheses.append({"name": "Гиперфункция щитовидной железы", "probability": 0.6, "source": "lab_pattern", "supports": ["TSH low"]})
        if not skip_infection_for_oa and "possible_allergy" in topics:
            hypotheses.append({"name": "Возможная аллергия", "probability": 0.5, "source": "lab_pattern", "supports": ["эозинофилы"]})
        if not skip_infection_for_oa and ("infection_pattern" in topics or "inflammation_pattern" in topics):
            hypotheses.append({"name": "Воспаление / инфекция", "probability": 0.55, "source": "lab_pattern", "supports": ["WBC/нейтрофилы"]})
        for h in (context.hypotheses or []) + (payload.initial_hypotheses or []):
            if isinstance(h, dict) and (h.get("name") or h.get("title")):
                hypotheses.append({
                    "name": h.get("name") or h.get("title"),
                    "probability": float(h.get("probability") or h.get("score") or 0.5),
                    "source": h.get("source") or "ranking",
                    "supports": h.get("supports") or [],
                })
        seen_names = set()
        deduped = []
        for h in hypotheses:
            n = (h.get("name") or "").strip()
            if n and n.lower() not in seen_names:
                seen_names.add(n.lower())
                deduped.append(h)
        context.hypotheses = deduped[:10]
        context.debug["raw_hypotheses_count"] = len(context.hypotheses)

    def _filter_hypotheses(self, context: OrchestratorContext) -> None:
        """Фильтр через diagnosis_filter; при включённом routing — filter_hypotheses_by_route."""
        symptoms = context.normalized_symptoms or []
        raw_h = [{"name": h.get("name"), "probability": h.get("probability"), "score": h.get("probability")} for h in context.hypotheses]
        filtered = filter_ranked_hypotheses_for_labs_only(
            raw_h,
            symptoms=symptoms,
            lab_type=context.lab_type,
        )
        if _clinical_routing_enabled() and context.route_decision:
            filtered_dicts = [
                {"name": h.get("name"), "probability": h.get("probability"), "title": h.get("name")}
                for h in filtered
            ]
            filtered_dicts = filter_hypotheses_by_route(filtered_dicts, context.route_decision)
            filtered = [
                {"name": h.get("name") or h.get("title"), "probability": h.get("probability") or 0.5, "score": h.get("probability") or 0.5}
                for h in filtered_dicts
            ]
        context.filtered_hypotheses = filtered[:3]
        context.user_hypotheses = user_hypothesis_strings(context.filtered_hypotheses, max_n=2)
        context.debug["filtered_hypotheses_count"] = len(context.filtered_hypotheses)

    def _run_decision_engine(self, payload: OrchestratorInput, context: OrchestratorContext) -> None:
        """Запуск MikhailDecisionEngine; сохранить state, urgency, questions, final_user_message."""
        decision_input = DecisionInput(
            user_text=payload.user_text or "",
            symptoms=context.normalized_symptoms or [],
            lab_rows=context.lab_rows or [],
            structured_lab_report=context.structured_lab_report,
            hypotheses=context.filtered_hypotheses or [],
            user_profile=payload.profile or {},
            red_flags=context.red_flags or [],
            uploaded_files=payload.uploaded_files or [],
            conversation_context={"parsed_documents": context.parsed_documents},
        )
        engine = MikhailDecisionEngine()
        out = engine.evaluate(decision_input)
        context.decision_output = out
        context.decision_state = out.state
        context.urgency = out.urgency
        context.requested_labs = out.recommended_labs or []
        context.debug["decision_state"] = out.state
        context.debug["urgency"] = out.urgency

    def _compose_final_message(self, context: OrchestratorContext) -> None:
        """Собрать финальное сообщение: emergency / needs_more_data / request_labs / обычный ответ."""
        out = context.decision_output
        if out:
            context.debug["final_message_source"] = "decision_engine"
            return
        if context.red_flags:
            context.decision_output = DecisionOutput(
                state="emergency",
                urgency="high",
                final_user_message="Есть признаки, при которых нужна срочная медицинская помощь. Не откладывайте обращение. Срочно звоните 103/112 или обратитесь за неотложной помощью.",
            )
            return
        context.decision_output = DecisionOutput(
            state="needs_more_data",
            urgency="low",
            questions=FALLBACK_QUESTIONS[:3],
            final_user_message=FALLBACK_MESSAGE,
        )

    def _apply_product_gates(
        self,
        payload: OrchestratorInput,
        context: OrchestratorContext,
        output: OrchestratorOutput,
    ) -> OrchestratorOutput:
        """Применить гейты монетизации. Emergency/red flags не блокируем."""
        try:
            ent_svc = EntitlementService()
            entitlements = ent_svc.get_user_entitlements(payload.user_id)
            po = ProductOrchestrator()
            out_dict = {
                "ok": output.ok,
                "state": output.state,
                "urgency": output.urgency,
                "final_user_message": output.final_user_message,
                "questions": output.questions,
                "recommended_labs": output.recommended_labs,
                "user_report_structured": output.user_report_structured,
                "user_hypotheses": output.user_hypotheses,
                "care_plan": output.care_plan,
                "care_plan_message": output.care_plan_message,
                "physician_report": output.physician_report,
                "physician_report_text": output.physician_report_text,
                "continuity_summary": output.continuity_summary,
            }
            gated = po.apply_gates(out_dict, entitlements, {"red_flags": context.red_flags})
            output.physician_report = gated.get("physician_report")
            output.physician_report_text = gated.get("physician_report_text")
            output.product = gated.get("product")
            output.launch = gated.get("launch")
        except Exception:
            output.product = {
                "active_tier": "free",
                "gated_features": [],
                "available_features": [],
                "upgrade_prompts": [],
                "offers": [],
                "pricing_cards": [],
                "launch_flags": {},
            }
            output.launch = None
        return output

    def _apply_onboarding_conversion(
        self,
        payload: OrchestratorInput,
        context: OrchestratorContext,
        output: OrchestratorOutput,
    ) -> OrchestratorOutput:
        """Онбординг и конверсия: шаги, next_best_action, conversion decision. При emergency — без отвлечений."""
        try:
            store = OnboardingStore()
            ob_state = store.load(payload.user_id, payload.session_id)
            clinical_dict = {
                "ok": output.ok,
                "state": output.state,
                "urgency": output.urgency,
                "final_user_message": output.final_user_message,
                "questions": output.questions,
                "recommended_labs": output.recommended_labs,
                "user_report_structured": output.user_report_structured,
                "user_hypotheses": output.user_hypotheses,
                "care_plan": output.care_plan,
                "continuity_summary": output.continuity_summary,
                "physician_report": output.physician_report,
                "physician_report_text": output.physician_report_text,
                "red_flags": context.red_flags,
            }
            user_ctx = {
                "user_text": payload.user_text,
                "has_uploaded_files": bool(payload.uploaded_files or payload.raw_lab_rows),
                "documents_count": len(payload.uploaded_files or []),
                "lab_rows_count": len(context.lab_rows or []),
                "is_returning_user": bool(context.memory and (getattr(context.memory, "labs", None) or getattr(context.memory, "symptoms", None))),
                "pending_labs_uploaded": False,
                "first_upload": not ob_state.first_upload_done,
                "memory": context.memory,
                "product_context": output.product,
            }
            if output.continuity_summary and (output.continuity_summary.get("pending_labs") or []):
                user_ctx["pending_labs_uploaded"] = bool(context.lab_rows)

            if output.state == "emergency" or (output.urgency or "").lower() == "high":
                output.onboarding = {
                    "is_new_user": ob_state.is_new_user,
                    "current_step_id": None,
                    "first_value_reached": ob_state.first_value_reached,
                    "steps": [],
                    "next_best_action": {"title": "Следуйте рекомендациям выше", "description": "", "cta": None},
                    "empty_state_guidance": None,
                    "return_guidance": None,
                }
                output.conversion = {"should_show_upgrade": False, "placement": None, "offer_id": None, "message": None}
                return output

            eng = OnboardingEngine()
            ob_result = eng.evaluate(user_ctx, ob_state, clinical_dict)
            signals = collect_conversion_signals(user_ctx, clinical_dict, output.product or {})
            ent_svc = EntitlementService()
            entitlements = ent_svc.get_user_entitlements(payload.user_id)
            conv_eng = ConversionEngine()
            conv_decision = conv_eng.decide(ob_state, signals, entitlements, clinical_dict)

            just_reached = ob_result.get("first_value_reached") and not ob_state.first_value_reached
            ob_state.first_value_reached = ob_state.first_value_reached or ob_result.get("first_value_reached")
            if just_reached:
                track_product_event(EVENT_FIRST_VALUE_REACHED, {"user_id": payload.user_id})
            if user_ctx.get("has_uploaded_files") and not ob_state.first_upload_done:
                ob_state.first_upload_done = True
            if ob_state.first_value_reached:
                ob_state.first_report_done = True
            if conv_decision.should_show_upgrade:
                ob_state.first_upgrade_prompt_shown = True
            store.save(ob_state)

            output.onboarding = ob_result
            output.conversion = conv_decision.to_dict() if hasattr(conv_decision, "to_dict") else {
                "should_show_upgrade": conv_decision.should_show_upgrade,
                "placement": conv_decision.placement,
                "offer_id": conv_decision.offer_id,
                "message": conv_decision.message,
                "offer": conv_decision.offer,
            }
        except Exception:
            output.onboarding = {}
            output.conversion = {"should_show_upgrade": False}
        return output

    def _log_quality(
        self,
        payload: OrchestratorInput,
        context: OrchestratorContext,
        output: OrchestratorOutput,
    ) -> None:
        """Логирование качества и воронки. При любой ошибке — silent no-op, ответ уже собран."""
        try:
            logger = QualityLogger()
            event = logger.build_clinical_event(payload, output, context)
            rv = (context.debug or {}).get("route_validation") or {}
            for t in rv.get("quality_tags") or []:
                if t and t not in event.quality_tags:
                    event.quality_tags.append(t)
            if rv and not rv.get("ok", True):
                event.quality_tags.append("route_validation_failed")
            if output.routing:
                event.quality_tags.append("clinical_routing_engine")
            failures = logger.maybe_log_failure_case(payload, output, context, event)
            score_result = compute_session_quality_score(event, failures)
            event.quality_score = score_result.get("score")
            event.quality_grade = score_result.get("grade")
            logger._store.log_clinical_event(event)
            for m in logger.build_funnel_metrics(payload, output, output.onboarding, output.product):
                logger._store.log_funnel_metric(m)
        except Exception:
            pass

    def _routing_and_hints(self, context: OrchestratorContext) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        rd = context.route_decision
        if not rd or not _clinical_routing_enabled():
            return None, None
        return rd.to_api_dict(), _render_hints_for_route(rd.primary_route)

    def _build_output(self, context: OrchestratorContext) -> OrchestratorOutput:
        """Собрать OrchestratorOutput из context."""
        routing, render_hints = self._routing_and_hints(context)
        dbg_common = {k: v for k, v in context.debug.items() if k not in ("lab_error", "orchestrator_error")}
        if routing:
            dbg_common["routing"] = routing
        out = context.decision_output
        if not out:
            return OrchestratorOutput(
                ok=True,
                state="needs_more_data",
                urgency="low",
                final_user_message=FALLBACK_MESSAGE,
                questions=FALLBACK_QUESTIONS[:3],
                recommended_labs=[],
                user_report_structured=context.structured_lab_report,
                user_hypotheses=context.user_hypotheses or [],
                doctor_report=context.doctor_report,
                continuity_summary=context.continuity_summary,
                care_plan=context.care_plan.to_dict() if context.care_plan else None,
                care_plan_message=context.care_plan_message,
                physician_report=context.physician_report.to_dict() if context.physician_report else None,
                physician_report_text=context.physician_report_text,
                product=None,
                launch=None,
                onboarding=None,
                conversion=None,
                routing=routing,
                render_hints=render_hints,
                debug=dbg_common,
            )
        return OrchestratorOutput(
            ok=True,
            state=out.state or "needs_more_data",
            urgency=out.urgency or "low",
            final_user_message=out.final_user_message or "",
            questions=out.questions or [],
            recommended_labs=out.recommended_labs or context.requested_labs or [],
            user_report_structured=context.structured_lab_report,
            user_hypotheses=out.likely_hypotheses or context.user_hypotheses or [],
            doctor_report=context.doctor_report,
            continuity_summary=context.continuity_summary,
            care_plan=context.care_plan.to_dict() if context.care_plan else None,
            care_plan_message=context.care_plan_message,
            physician_report=context.physician_report.to_dict() if context.physician_report else None,
            physician_report_text=context.physician_report_text,
            product=None,
            launch=None,
            onboarding=None,
            conversion=None,
            routing=routing,
            render_hints=render_hints,
            debug={
                **dbg_common,
                "extracted_symptoms": context.debug.get("extracted_symptoms"),
                "red_flags": context.debug.get("red_flags"),
                "parsed_doc_types": context.debug.get("parsed_doc_types"),
                "applied_rules": context.debug.get("applied_rules"),
                "raw_hypotheses_count": context.debug.get("raw_hypotheses_count"),
                "filtered_hypotheses_count": context.debug.get("filtered_hypotheses_count"),
                "decision_state": context.decision_state,
                "urgency": context.urgency,
            },
        )

    def _build_fallback_output(self, context: OrchestratorContext) -> OrchestratorOutput:
        """При ошибке — needs_more_data и безопасные вопросы."""
        return OrchestratorOutput(
            ok=False,
            state="needs_more_data",
            urgency="low",
            final_user_message=FALLBACK_MESSAGE,
            questions=FALLBACK_QUESTIONS[:3],
            recommended_labs=[],
            user_report_structured=None,
            user_hypotheses=[],
            doctor_report=None,
            continuity_summary=None,
            care_plan=None,
            care_plan_message=None,
            physician_report=None,
            physician_report_text=None,
            product=None,
            launch=None,
            onboarding=None,
            conversion=None,
            debug=context.debug,
        )
