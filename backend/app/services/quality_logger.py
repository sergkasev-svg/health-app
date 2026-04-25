"""
Quality Logger: формирование clinical event, детекция failure cases, funnel metrics.
Compact summaries, без гигантских raw payload.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from app.services.quality_models import (
    ClinicalQualityEvent,
    FailureCase,
    FunnelMetric,
    compute_session_quality_score,
)
from app.services.quality_rules import (
    detect_bad_triage_failure,
    detect_duplicate_questions_failure,
    detect_gating_issue_failure,
    detect_hallucination_failure,
    detect_parsing_failure,
    detect_weak_answer_failure,
)
from app.services.quality_store import QualityStore, _generate_id


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class QualityLogger:
    """
    Сбор событий и провалов после ответа Михаила. Не влияет на medical response.
    """

    def __init__(self, store: Optional[QualityStore] = None):
        self._store = store or QualityStore()

    def build_clinical_event(
        self,
        orchestrator_input: Any,
        orchestrator_output: Any,
        context: Any,
    ) -> ClinicalQualityEvent:
        """Compact event из input/output/context."""
        event_id = _generate_id("ev")
        now = _now_iso()
        inp = orchestrator_input
        out = orchestrator_output
        ctx = context

        user_id = getattr(inp, "user_id", None) if inp else None
        session_id = getattr(inp, "session_id", None) if inp else None
        state = getattr(out, "state", None) if out else None
        urgency = getattr(out, "urgency", None) if out else None
        red_flags = getattr(ctx, "red_flags", None) or []
        symptoms = getattr(ctx, "normalized_symptoms", None) or []
        hypotheses = getattr(ctx, "user_hypotheses", None) or (getattr(out, "user_hypotheses", None) or [])
        user_hypotheses = getattr(out, "user_hypotheses", None) or []
        recommended_labs = getattr(out, "recommended_labs", None) or []
        had_uploaded = bool(getattr(inp, "uploaded_files", None) or getattr(inp, "raw_lab_rows", None))
        file_types: List[str] = []
        if getattr(ctx, "parsed_documents", None):
            for d in ctx.parsed_documents[:5]:
                if isinstance(d, dict) and d.get("type"):
                    file_types.append(str(d.get("type")))
        physician_report_generated = bool(getattr(out, "physician_report", None))
        care_plan_generated = bool(getattr(out, "care_plan", None))
        followup_used = bool(context.memory and getattr(context.memory, "prior_states", None))
        gated = (getattr(out, "product", None) or {}).get("gated_features") or []
        debug_summary = {
            "extracted_symptoms": (getattr(ctx, "debug", None) or {}).get("extracted_symptoms"),
            "red_flags": red_flags[:5],
            "parsed_doc_types": file_types[:5],
            "chosen_state": state,
            "top_hypotheses": (user_hypotheses or hypotheses)[:3],
            "gated_features": gated[:5],
        }
        tags: List[str] = []
        if not red_flags and state not in ("emergency",):
            tags.append("clean_case")
        if state == "emergency":
            tags.append("emergency_case")
        if had_uploaded and len(file_types) > 1:
            tags.append("multi_file_case")
        if followup_used:
            tags.append("followup_case")
        if had_uploaded and not (getattr(ctx, "lab_rows", None)):
            tags.append("parsing_risky")
        if gated:
            tags.append("gated_case")

        return ClinicalQualityEvent(
            event_id=event_id,
            timestamp=now,
            user_id=user_id,
            session_id=session_id,
            state=state,
            urgency=urgency,
            red_flags=list(red_flags)[:10],
            symptoms=list(symptoms)[:10],
            hypotheses=list(hypotheses)[:5],
            user_hypotheses=list(user_hypotheses)[:5],
            recommended_labs=list(recommended_labs)[:5],
            had_uploaded_files=had_uploaded,
            file_types=file_types,
            physician_report_generated=physician_report_generated,
            care_plan_generated=care_plan_generated,
            followup_used=followup_used,
            gated_features=list(gated)[:10],
            debug_summary=debug_summary,
            quality_tags=tags,
        )

    def maybe_log_failure_case(
        self,
        orchestrator_input: Any,
        orchestrator_output: Any,
        context: Any,
        event: ClinicalQualityEvent,
    ) -> List[FailureCase]:
        """Проверить правила, залогировать failure cases. Возвращает список найденных."""
        failures: List[FailureCase] = []
        inp = orchestrator_input
        out = orchestrator_output
        ctx = context
        user_id = event.user_id
        session_id = event.session_id
        ts = event.timestamp
        eid = event.event_id
        raw_ctx = event.debug_summary or {}

        f = detect_hallucination_failure(
            event.user_hypotheses,
            raw_ctx,
            eid,
            ts,
            user_id,
            session_id,
        )
        if f:
            failures.append(f)
            event.quality_tags = list(set(event.quality_tags + ["suspected_hallucination"]))

        f = detect_bad_triage_failure(
            event.red_flags,
            event.state or "",
            event.urgency or "",
            eid,
            ts,
            user_id,
            session_id,
        )
        if f:
            failures.append(f)

        f = detect_parsing_failure(
            event.had_uploaded_files,
            event.file_types,
            len(getattr(ctx, "lab_rows", None) or []),
            bool(getattr(out, "physician_report", None) and (out.physician_report or {}).get("assessment")),
            eid,
            ts,
            user_id,
            session_id,
        )
        if f:
            failures.append(f)

        msg = getattr(out, "final_user_message", None) or ""
        f = detect_weak_answer_failure(
            event.state or "",
            len(msg),
            bool(getattr(out, "questions", None)),
            event.care_plan_generated,
            event.physician_report_generated,
            bool(event.symptoms or event.had_uploaded_files),
            eid,
            ts,
            user_id,
            session_id,
        )
        if f:
            failures.append(f)
            event.quality_tags = list(set(event.quality_tags + ["weak_answer_case"]))

        answered: List[str] = []
        if getattr(ctx, "memory", None) and getattr(ctx.memory, "asked_questions", None):
            for aq in ctx.memory.asked_questions:
                if getattr(aq, "answered", False) and getattr(aq, "question", None):
                    answered.append(aq.question)
        f = detect_duplicate_questions_failure(
            getattr(out, "questions", None) or [],
            answered,
            eid,
            ts,
            user_id,
            session_id,
        )
        if f:
            failures.append(f)

        gated_pr = "physician_report" in (event.gated_features or [])
        f = detect_gating_issue_failure(
            event.state or "",
            event.urgency or "",
            event.red_flags,
            event.physician_report_generated,
            gated_pr and (event.state == "emergency" or event.red_flags),
            eid,
            ts,
            user_id,
            session_id,
        )
        if f:
            failures.append(f)

        for failure in failures:
            if not failure.case_id.startswith(("hall_", "triage_", "parse_", "weak_", "dup_", "gate_")):
                failure.case_id = f"{failure.category}_{eid}"
            self._store.log_failure_case(failure)
        return failures

    def build_funnel_metrics(
        self,
        orchestrator_input: Any,
        orchestrator_output: Any,
        onboarding: Optional[Dict[str, Any]],
        product: Optional[Dict[str, Any]],
    ) -> List[FunnelMetric]:
        """Метрики воронки из onboarding/product."""
        metrics: List[FunnelMetric] = []
        now = _now_iso()
        inp = orchestrator_input
        user_id = getattr(inp, "user_id", None) if inp else None
        session_id = getattr(inp, "session_id", None) if inp else None

        ob = onboarding or {}
        if ob.get("first_value_reached"):
            metrics.append(FunnelMetric(_generate_id("fn"), now, user_id, session_id, "first_value", ob))
        if ob.get("is_new_user") and not ob.get("first_value_reached"):
            metrics.append(FunnelMetric(_generate_id("fn"), now, user_id, session_id, "onboarding_started", ob))
        if getattr(inp, "uploaded_files", None) or getattr(inp, "raw_lab_rows", None):
            metrics.append(FunnelMetric(_generate_id("fn"), now, user_id, session_id, "first_upload", {}))
        if ob.get("return_guidance"):
            metrics.append(FunnelMetric(_generate_id("fn"), now, user_id, session_id, "returned", ob))
        prod = product or {}
        if prod.get("upgrade_prompts"):
            metrics.append(FunnelMetric(_generate_id("fn"), now, user_id, session_id, "upgrade_prompt_shown", prod))
        return metrics
