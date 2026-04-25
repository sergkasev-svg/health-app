from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from app.orchestration.prompt_registry import PromptRegistry
from app.orchestration.routers import route_after_adaptive
from app.orchestration.state_models import (
    AdaptiveQuestionOutput,
    ConsultationState,
    FinalAnswerOutput,
    HistoryState,
    HypothesisItem,
    IntakeOutput,
    LabParserOutput,
    NextBestQuestion,
    ParsedLabValue,
    RankedKnowledgeItem,
    RankingOutput,
    ReasoningOutput,
    RetrievalOutput,
    RetrievedKnowledgeItem,
    SafetyOutput,
    UploadedFileState,
    WeightedHypothesisItem,
    WeightingOutput,
)
from app.services.clinical_profiles import search_clinical_profiles
from app.services.complaint_reference import search_complaint_reference
from app.services.labs_layer_lookup import build_labs_layer_context
from app.services.red_flag_screening import screen_red_flags
from app.services.diagnostic_ranking_engine import filter_ranked_hypotheses_for_labs_only
from app.services.lab_document_router import detect_lab_type
from app.services.strict_topic_protocol import search_strict_topic_protocol

try:
    from app.reasoning.medical_graph_engine import rank_diseases
except Exception:
    rank_diseases = None
try:
    from app.services.symptom_normalizer import normalize as symptom_normalize
except Exception:
    symptom_normalize = None
try:
    from app.services.systemic_triage import triage_priority
except Exception:
    triage_priority = None
try:
    from app.services.anatomy_router import detect_anatomy
except Exception:
    detect_anatomy = None
try:
    from app.services.lab_interpreter import interpret_labs
except Exception:
    interpret_labs = None
try:
    from app.services.question_engine import generate_questions
except Exception:
    generate_questions = None
try:
    from app.reasoning.clinical_reasoner import clinical_reason
except Exception:
    clinical_reason = None
try:
    from app.services.red_flag_engine import detect_red_flags_from_text
except Exception:
    detect_red_flags_from_text = None
try:
    from app.reasoning.probabilistic_reasoner import probabilistic_diagnosis
except Exception:
    probabilistic_diagnosis = None


class BlockRunner:
    def __init__(self, prompt_registry: PromptRegistry | None = None) -> None:
        self.prompt_registry = prompt_registry or PromptRegistry.from_default_paths()
        backend_dir = Path(__file__).resolve().parents[2]
        self.project_root = backend_dir.parent
        self._aliases = self._load_aliases()
        self._analytes = self._load_analytes()

    def _load_aliases(self) -> dict[str, str]:
        path = self.project_root / "medical_knowledge" / "labs" / "terminology" / "aliases.json"
        out: dict[str, str] = {}
        try:
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                out.update({str(k).lower(): str(v).lower() for k, v in payload.items()})
            analytes_dir = self.project_root / "medical_knowledge" / "labs" / "analytes"
            for fp in sorted(analytes_dir.glob("*.json")):
                a = json.loads(fp.read_text(encoding="utf-8"))
                analyte_id = str(a.get("id") or fp.stem).strip().lower()
                if not analyte_id:
                    continue
                name = str(a.get("name") or "").strip().lower()
                if name:
                    out.setdefault(name, analyte_id)
                for alias in (a.get("aliases") or []):
                    alias_str = str(alias or "").strip().lower()
                    if alias_str:
                        out.setdefault(alias_str, analyte_id)
        except Exception:
            return out
        return out

    def _load_analytes(self) -> dict[str, dict[str, Any]]:
        path = self.project_root / "medical_knowledge" / "labs" / "analytes"
        out: dict[str, dict[str, Any]] = {}
        try:
            import json

            for fp in sorted(path.glob("*.json")):
                payload = json.loads(fp.read_text(encoding="utf-8"))
                analyte_id = str(payload.get("id") or fp.stem).strip().lower()
                if analyte_id:
                    out[analyte_id] = payload
        except Exception:
            return out
        return out

    def _to_text_context(self, state: ConsultationState) -> str:
        symptom_blob = ", ".join(state.history.symptoms or [])
        upload_blob = "\n".join([f.content_text or "" for f in state.uploaded_files if f.content_text])
        return f"{state.chief_complaint}\n{symptom_blob}\n{upload_blob}".strip()

    def run_intake_normalizer(
        self,
        user_input: str,
        chat_history: list[dict[str, Any]] | None = None,
        uploaded_files: list[dict[str, Any]] | None = None,
    ) -> IntakeOutput:
        text = str(user_input or "").strip()
        normalized_text = symptom_normalize(text) if symptom_normalize else text
        low = normalized_text.lower() if normalized_text else text.lower()
        symptoms: list[str] = []
        symptom_markers = [
            "слабость",
            "головокружение",
            "бледность",
            "температура",
            "боль в животе",
            "тошнота",
            "рвота",
            "одышка",
            "кашель",
            "жажда",
            "боль",
            "жжение",
        ]
        for marker in symptom_markers:
            if marker in low:
                symptoms.append(marker)

        location = ""
        if triage_priority and low:
            priority = triage_priority(low)
            if priority:
                location = priority
        if not location and detect_anatomy and low:
            zone = detect_anatomy(low)
            if zone:
                location = f"orthopedics_{zone}"

        duration = ""
        duration_match = re.search(r"(\d+\s*(дн(я|ей)?|нед(ел(и|ь))?|месяц(а|ев)?))", low)
        if duration_match:
            duration = duration_match.group(1)

        temperature = None
        temp_match = re.search(r"(3[5-9](?:[.,]\d)?)", low)
        if temp_match and ("темпера" in low or "жар" in low):
            temperature = float(temp_match.group(1).replace(",", "."))

        chief_complaint = text

        files: list[UploadedFileState] = []
        for item in uploaded_files or []:
            if isinstance(item, dict):
                files.append(
                    UploadedFileState(
                        file_name=str(item.get("file_name") or "uploaded_file"),
                        file_type=str(item.get("file_type") or "unknown"),
                        content_text=item.get("content_text"),
                    )
                )

        return IntakeOutput(
            chief_complaint=chief_complaint,
            history=HistoryState(
                duration=duration,
                symptoms=list(dict.fromkeys(symptoms)),
                temperature=temperature,
                location=location,
            ),
            uploaded_files=files,
        )

    def run_adaptive_question_engine(self, state: ConsultationState) -> AdaptiveQuestionOutput:
        known_data = {
            "age": state.user_profile.age,
            "sex": state.user_profile.sex,
            "main_complaint": state.chief_complaint,
            "duration": state.history.duration,
            "temperature": state.history.temperature,
            "symptoms": state.history.symptoms,
            "chronic_conditions": state.history.chronic_conditions,
            "medications": state.history.medications,
            "allergies": state.history.allergies,
            "pregnancy": state.user_profile.pregnancy,
            "labs_available": bool(state.parsed_labs or state.uploaded_files),
        }
        context_text = self._to_text_context(state)
        red_flags = screen_red_flags(context_text)
        labs_layer = build_labs_layer_context(
            user_text=context_text,
            document_text=context_text,
            complaint_protocol=None,
            clinical_profiles=[],
        )
        raw_hypos = [{"name": h, "score": 0.6} for h in (labs_layer.get("symptom_hypotheses") or [])[:5]]
        symptoms_from_context = [s.strip() for s in (context_text or "").replace(",", " ").split() if s and len(s.strip()) > 2][:10]
        lab_type = detect_lab_type(context_text or "")
        top_hypotheses = filter_ranked_hypotheses_for_labs_only(raw_hypos, symptoms=symptoms_from_context, lab_type=lab_type)

        missing = []
        if state.user_profile.age is None:
            missing.append("age")
        if not state.user_profile.sex:
            missing.append("sex")
        if not state.history.duration:
            missing.append("duration")
        if state.history.temperature is None:
            missing.append("temperature")
        if not state.history.location:
            missing.append("location")

        next_question = None
        should_stop = False
        stop_reason = ""
        if red_flags:
            should_stop = True
            stop_reason = "urgent_red_flags_detected"
            next_question = NextBestQuestion(
                question="Нужна срочная очная помощь. Можете ли вы вызвать неотложную помощь прямо сейчас?",
                reason="Обнаружены красные флаги.",
                question_type="red_flag",
                expected_impact="high",
            )
        elif missing:
            key = missing[0]
            questions = {
                "age": "Сколько вам лет?",
                "sex": "Уточните, пожалуйста, ваш пол.",
                "duration": "Как давно начались симптомы?",
                "temperature": "Какая сейчас температура тела?",
                "location": "Где именно локализуется основной симптом?",
            }
            next_question = NextBestQuestion(
                question=questions.get(key, "Уточните, пожалуйста, ключевой недостающий параметр."),
                reason="Нужно закрыть критичный пробел в данных для безопасного triage.",
                question_type="follow_up",
                expected_impact="high",
            )
        else:
            should_stop = True
            stop_reason = "minimum_data_collected"
            if state.chief_complaint:
                next_question = NextBestQuestion(
                    question="Есть ли усиление симптомов в динамике за последние сутки?",
                    reason="Уточнение тяжести может изменить urgency и приоритет дообследования.",
                    question_type="severity",
                    expected_impact="medium",
                )

        return AdaptiveQuestionOutput(
            known_data=known_data,
            top_hypotheses=top_hypotheses,
            red_flags_detected=red_flags,
            missing_critical_data=missing,
            next_best_question=next_question,
            should_stop_questioning=should_stop,
            stop_reason=stop_reason,
        )

    def run_lab_result_parser(self, state: ConsultationState) -> LabParserOutput:
        text = self._to_text_context(state).lower()
        parsed: list[ParsedLabValue] = []
        seen: set[str] = set()
        for alias, analyte_id in sorted(self._aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
            if len(alias) < 2:
                continue
            if alias not in text:
                continue
            if analyte_id in seen:
                continue
            value_match = re.search(rf"{re.escape(alias)}[^\d\-]{{0,24}}(\d+(?:[.,]\d+)?)", text, flags=re.IGNORECASE)
            if not value_match:
                continue
            value = float(value_match.group(1).replace(",", "."))
            analyte = self._analytes.get(analyte_id, {})
            rr = (analyte.get("reference_ranges") or [{}])[0] if isinstance(analyte, dict) else {}
            lower = rr.get("lower")
            upper = rr.get("upper")
            if analyte_id == "mcv" and value > 10:
                value = value / 100.0
            status = "unknown"
            if lower is not None and value < float(lower):
                status = "low"
            elif upper is not None and value > float(upper):
                status = "high"
            elif lower is not None or upper is not None:
                status = "normal"
            parsed.append(
                ParsedLabValue(
                    analyte_id=analyte_id,
                    name=str(analyte.get("name") or analyte_id),
                    value=value,
                    unit=str((analyte.get("units") or [{}])[0].get("unit") or ""),
                    reference_range=f"{lower}-{upper}" if (lower is not None or upper is not None) else "",
                    status=status,  # type: ignore[arg-type]
                    panel=str((analyte.get("panel_ids") or [""])[0]),
                    confidence_score=0.9,
                )
            )
            seen.add(analyte_id)
        return LabParserOutput(parsed_labs=parsed)

    def run_knowledge_retrieval(self, state: ConsultationState) -> RetrievalOutput:
        items: list[RetrievedKnowledgeItem] = []
        query = self._to_text_context(state)
        complaint_hits = search_complaint_reference(query, top_k=2)
        strict_hits = search_strict_topic_protocol(query, top_k=2)
        profile_hits = search_clinical_profiles(query, top_k=3)
        labs_layer = build_labs_layer_context(
            user_text=query,
            document_text=query,
            complaint_protocol=complaint_hits[0] if complaint_hits else None,
            clinical_profiles=profile_hits,
        )

        for it in complaint_hits:
            items.append(
                RetrievedKnowledgeItem(
                    source_type="complaints_reference",
                    source_id=str(it.get("id") or "complaint"),
                    content_summary=str(it.get("description") or it.get("complaint") or "")[:280],
                    relevance_hint="high",
                )
            )
        for it in strict_hits:
            items.append(
                RetrievedKnowledgeItem(
                    source_type="strict_topic_protocols",
                    source_id=str(it.get("id") or it.get("title") or "strict_protocol"),
                    content_summary=str(it.get("title") or it.get("diagnosis") or "")[:280],
                    relevance_hint="medium",
                )
            )
        for it in profile_hits:
            items.append(
                RetrievedKnowledgeItem(
                    source_type="disease_clinical_profiles",
                    source_id=str(it.get("id") or it.get("name") or "clinical_profile"),
                    content_summary=str(it.get("description") or it.get("name") or "")[:280],
                    relevance_hint="high",
                )
            )
        for ma in (labs_layer.get("matched_analytes") or [])[:6]:
            items.append(
                RetrievedKnowledgeItem(
                    source_type="labs",
                    source_id=str(ma.get("id") or "analyte"),
                    content_summary=f"Лаб-показатель: {ma.get('name') or ma.get('id')}",
                    relevance_hint="high",
                )
            )
        if state.parsed_labs:
            items.append(
                RetrievedKnowledgeItem(
                    source_type="clinical_guidelines",
                    source_id="guideline_general_lab_interpretation",
                    content_summary="Использовать guideline-first подход при интерпретации отклонений лаборатории.",
                    relevance_hint="medium",
                )
            )
            items.append(
                RetrievedKnowledgeItem(
                    source_type="ontologies",
                    source_id="ontology_loinc_icd10",
                    content_summary="Нормализация терминов и сопоставление кодов через онтологии.",
                    relevance_hint="medium",
                )
            )
        return RetrievalOutput(retrieved_knowledge=items)

    def run_retrieval_ranking(self, state: ConsultationState) -> RankingOutput:
        priority = {
            "clinical_guidelines": 1.0,
            "ontologies": 0.95,
            "disease_clinical_profiles": 0.9,
            "strict_topic_protocols": 0.82,
            "labs": 0.75,
            "educational": 0.65,
            "wellness": 0.5,
            "complaints_reference": 0.88,
        }
        hint_boost = {"high": 0.1, "medium": 0.05, "low": 0.0}
        dedupe: dict[tuple[str, str], RankedKnowledgeItem] = {}
        for item in state.retrieved_knowledge:
            base = priority.get(item.source_type, 0.6)
            rel = min(1.0, base + hint_boost.get(item.relevance_hint, 0.0))
            conf = min(1.0, base)
            ranked = RankedKnowledgeItem(
                source_id=item.source_id,
                source_type=item.source_type,
                relevance_score=round(rel, 3),
                confidence_score=round(conf, 3),
                knowledge_summary=item.content_summary,
            )
            key = (ranked.source_type, ranked.source_id)
            prev = dedupe.get(key)
            if prev is None or ranked.relevance_score > prev.relevance_score:
                dedupe[key] = ranked
        out = sorted(dedupe.values(), key=lambda x: (x.relevance_score, x.confidence_score), reverse=True)
        return RankingOutput(ranked_knowledge=out[:12])

    def run_diagnostic_reasoning(self, state: ConsultationState) -> ReasoningOutput:
        observations: list[str] = []
        if state.history.symptoms:
            observations.append("Симптомы: " + ", ".join(state.history.symptoms[:6]) + ".")
        lab_signals: list[str] = []
        if interpret_labs:
            try:
                lab_signals = interpret_labs(state.parsed_labs)
                for sig in lab_signals:
                    observations.append(f"Лабораторный сигнал: {sig}.")
            except Exception:
                pass
        for lab in state.parsed_labs[:8]:
            if lab.status in {"high", "low"}:
                observations.append(f"{lab.name}: {lab.status} ({lab.value} {lab.unit}).")
        if not observations:
            observations.append("Данных пока недостаточно для устойчивых наблюдений.")

        hypotheses: list[HypothesisItem] = []
        if rank_diseases and state.history.symptoms:
            try:
                ranked = rank_diseases(state.history.symptoms)
                for score, disease in ranked[:5]:
                    name = disease.get("name") or disease.get("id", "")
                    if name and not any(h.name == name for h in hypotheses):
                        hypotheses.append(
                            HypothesisItem(
                                name=name,
                                likelihood="high" if score >= 10 else "medium" if score >= 5 else "low",
                                supports=[f"Совпадение симптомов (score={score})"],
                                against=[],
                                missing_data=[],
                            )
                        )
            except Exception:
                pass
        seed_names: list[str] = []
        for item in state.ranked_knowledge:
            text = (item.knowledge_summary or "").lower()
            if "анем" in text:
                seed_names.append("железодефицитная анемия")
            if "диаб" in text or "глюкоз" in text:
                seed_names.append("сахарный диабет")
            if "печен" in text or "гепат" in text:
                seed_names.append("гепатит или поражение печени")
            if "почеч" in text:
                seed_names.append("почечное поражение / ХБП")
        for name in list(dict.fromkeys(seed_names))[:5]:
            supports = [o for o in observations if any(k in o.lower() for k in name.split()[:2])]
            hypotheses.append(
                HypothesisItem(
                    name=name,
                    likelihood="medium" if supports else "low",
                    supports=supports[:3],
                    against=[] if supports else ["Недостаточно специфичных признаков в текущих данных."],
                    missing_data=["возраст", "пол"] if (state.user_profile.age is None or not state.user_profile.sex) else [],
                )
            )
        if len(hypotheses) < 3:
            fallback = [
                "воспалительный/инфекционный процесс",
                "метаболическое нарушение",
                "функциональное расстройство",
            ]
            for name in fallback:
                if len(hypotheses) >= 3:
                    break
                if any(h.name == name for h in hypotheses):
                    continue
                hypotheses.append(HypothesisItem(name=name, likelihood="low", missing_data=["нужны доп. данные"]))

        red_flags = list(dict.fromkeys(state.red_flags))
        recommended_questions: list[str] = []
        if generate_questions and state.history.symptoms:
            try:
                recommended_questions.extend(generate_questions(state.history.symptoms))
            except Exception:
                pass
        if state.next_question:
            recommended_questions.append(state.next_question.question)
        if not recommended_questions:
            recommended_questions.append("Уточните, пожалуйста, динамику симптомов за последние 24 часа.")

        recommended_tests: list[str] = []
        for lab in state.parsed_labs:
            if lab.status in {"high", "low"}:
                if lab.analyte_id in {"hgb", "rbc", "mcv", "ferritin", "iron"}:
                    recommended_tests.extend(["MCV", "MCH", "ОЖСС/трансферрин"])
                if lab.analyte_id in {"glucose", "hba1c"}:
                    recommended_tests.extend(["повторная глюкоза натощак", "общий анализ мочи"])
        if not recommended_tests:
            recommended_tests.extend(["ОАК", "базовая биохимия"])

        return ReasoningOutput(
            observations=list(dict.fromkeys(observations)),
            differential_hypotheses=hypotheses[:5],
            recommended_questions=list(dict.fromkeys(recommended_questions))[:4],
            recommended_tests=list(dict.fromkeys(recommended_tests))[:6],
            red_flags=red_flags,
        )

    def run_evidence_weighting(self, state: ConsultationState) -> WeightingOutput:
        weighted: list[WeightedHypothesisItem] = []
        abnormal_labs = [x for x in state.parsed_labs if x.status in {"high", "low"}]
        for hyp in state.hypotheses[:5]:
            name_low = hyp.name.lower()
            symptom_score = 0.75 if any(s and s in name_low for s in state.history.symptoms[:3]) else 0.55
            lab_score = 0.35
            if "анем" in name_low and any(x.analyte_id in {"hgb", "rbc", "ferritin", "mcv"} for x in abnormal_labs):
                lab_score = 0.9
            elif "диаб" in name_low and any(x.analyte_id in {"glucose", "hba1c"} for x in abnormal_labs):
                lab_score = 0.88
            elif "печен" in name_low and any(x.analyte_id in {"alt", "ast", "bilirubin_total"} for x in abnormal_labs):
                lab_score = 0.82
            elif abnormal_labs:
                lab_score = 0.6
            risk_score = 0.5 if state.history.chronic_conditions else 0.35
            demographic_score = 0.7 if (state.user_profile.age is not None and state.user_profile.sex) else 0.4
            guideline_score = 0.8 if any(k.source_type == "clinical_guidelines" for k in state.ranked_knowledge) else 0.6
            diagnosis_score = (
                symptom_score * 0.35
                + lab_score * 0.30
                + risk_score * 0.15
                + demographic_score * 0.10
                + guideline_score * 0.10
            )
            confidence = "high" if diagnosis_score >= 0.75 else ("medium" if diagnosis_score >= 0.5 else "low")
            weighted.append(
                WeightedHypothesisItem(
                    diagnosis=hyp.name,
                    diagnosis_score=round(diagnosis_score, 3),
                    symptom_score=round(symptom_score, 3),
                    lab_score=round(lab_score, 3),
                    risk_score=round(risk_score, 3),
                    demographic_score=round(demographic_score, 3),
                    guideline_score=round(guideline_score, 3),
                    confidence_level=confidence,  # type: ignore[arg-type]
                )
            )
        weighted.sort(key=lambda x: x.diagnosis_score, reverse=True)
        return WeightingOutput(weighted_hypotheses=weighted[:3])

    def run_clinical_safety_guardrail(self, state: ConsultationState) -> SafetyOutput:
        disclaimer = "Информация носит справочный характер и не заменяет консультацию врача."
        urgent_notice = None
        is_safe = True
        removed: list[str] = []
        safety_notes: list[str] = []
        if state.red_flags:
            is_safe = False
            urgent_notice = "Есть признаки состояния, требующего срочной медицинской помощи."
        for rec in list(state.safe_recommendations):
            rec_low = rec.lower()
            if "антибиот" in rec_low or "дозиров" in rec_low or "рецепт" in rec_low:
                removed.append(rec)
        if removed:
            is_safe = False
            safety_notes.append("Убраны потенциально опасные рекомендации по самолечению.")
        if not safety_notes:
            safety_notes.append("Не начинать самостоятельный прием лекарств без очной оценки врача.")
        return SafetyOutput(
            is_safe=is_safe,
            urgent_notice=urgent_notice,
            unsafe_elements_removed=removed,
            final_safety_notes=safety_notes,
            disclaimer=disclaimer,
        )

    def run_clinical_reasoning_v4(self, state: ConsultationState) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        """V4: clinical_reason(symptoms) + detect_red_flags_from_text. Возвращает (diagnosis_candidates, differential_diagnosis, red_flags_from_text)."""
        diagnosis_candidates: list[dict[str, Any]] = []
        differential: list[dict[str, Any]] = []
        red_flags_text: list[str] = []
        symptoms = list(state.history.symptoms or []) if state.history.symptoms else []
        if clinical_reason and symptoms:
            try:
                diagnosis_candidates, differential = clinical_reason(symptoms)
            except Exception:
                pass
        text = self._to_text_context(state)
        if detect_red_flags_from_text and text:
            try:
                red_flags_text = detect_red_flags_from_text(text)
            except Exception:
                pass
        return diagnosis_candidates, differential, red_flags_text

    def run_probabilistic_diagnosis_v5(self, state: ConsultationState) -> list[dict[str, Any]]:
        """V5: Bayesian + lab evidence. Возвращает список {disease, probability}."""
        if not probabilistic_diagnosis:
            return []
        symptoms = list(state.history.symptoms or [])
        labs: dict[str, Any] = {}
        for lab in state.parsed_labs or []:
            aid = getattr(lab, "analyte_id", None) or (lab.get("analyte_id") if isinstance(lab, dict) else None)
            val = getattr(lab, "value", None) if hasattr(lab, "value") else (lab.get("value") if isinstance(lab, dict) else None)
            if aid is not None and val is not None:
                try:
                    labs[str(aid)] = float(val)
                except (TypeError, ValueError):
                    pass
        try:
            return probabilistic_diagnosis(symptoms, labs)
        except Exception:
            return []

    def run_final_answer_generator(self, state: ConsultationState) -> FinalAnswerOutput:
        top = [
            {"name": h.diagnosis, "confidence": h.confidence_level}
            for h in state.weighted_hypotheses[:3]
        ]
        known = list(dict.fromkeys(state.history.symptoms))[:5]
        known_lines = []
        if known:
            known_lines.append("Есть жалобы: " + ", ".join(known) + ".")
        for lab in state.parsed_labs:
            if lab.status in {"high", "low"}:
                known_lines.append(f"{lab.name} {lab.status}: {lab.value} {lab.unit}.")

        final: dict[str, Any] = {
            "what_is_known": known_lines or ["Недостаточно данных по симптомам и анализам."],
            "what_is_important": [
                "Нужно сопоставить клинику, анализы и факторы риска перед очным подтверждением диагноза."
            ],
            "top_hypotheses": top,
            "questions_to_clarify": [state.next_question.question] if state.next_question else [],
            "recommended_tests": list(dict.fromkeys([q for q in (state.safe_recommendations or []) if q]))[:6],
            "safe_actions_before_doctor": state.safe_recommendations[:5],
            "urgent_flags": state.red_flags,
            "plain_language_summary": "Это предварительная оценка. Для точного диагноза нужна очная консультация врача.",
        }
        if getattr(state, "diagnosis_candidates", None):
            final["diagnosis_candidates"] = state.diagnosis_candidates
        if getattr(state, "differential_diagnosis", None):
            final["differential_diagnosis"] = state.differential_diagnosis
        if getattr(state, "diagnosis_probabilities", None):
            final["diagnosis_probabilities"] = state.diagnosis_probabilities
            final["differential"] = state.diagnosis_probabilities[:3]
        elif getattr(state, "differential_diagnosis", None):
            final["differential"] = state.differential_diagnosis[:3]
        if getattr(state, "care_level", None) and state.care_level not in ("", "undetermined"):
            final["care_level"] = state.care_level
        final["red_flags"] = list(dict.fromkeys(state.red_flags))
        final["questions"] = final.get("questions_to_clarify", [])
        final["recommended_tests"] = final.get("recommended_tests", [])
        return FinalAnswerOutput(final_answer=final)

    def init_state(self, session_id: str | None = None) -> ConsultationState:
        return ConsultationState(session_id=session_id or str(uuid.uuid4()))

    def apply_adaptive_routing(self, output: AdaptiveQuestionOutput) -> str:
        return route_after_adaptive(output)
