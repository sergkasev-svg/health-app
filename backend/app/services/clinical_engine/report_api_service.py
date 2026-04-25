from __future__ import annotations

from typing import Any

from app.services.clinical_engine.contracts_api import AggregateClinicalReportPayload, PatientInfo
from app.services.clinical_engine.api_report_adapter import adapt_current_pipeline_result_to_core
from app.services.clinical_engine.serializers import build_aggregate_payload


def build_api_payload_from_current_result(
    current_result: dict[str, Any],
    patient_info: dict[str, Any] | None = None,
) -> AggregateClinicalReportPayload:
    core = adapt_current_pipeline_result_to_core(current_result)
    patient = PatientInfo(
        display_name=(patient_info or {}).get("display_name"),
        sex=(patient_info or {}).get("sex"),
        age=(patient_info or {}).get("age"),
    )
    html_full = str(current_result.get("physician_report_html") or "").strip()
    return build_aggregate_payload(core=core, patient=patient, physician_report_html_full=html_full)
