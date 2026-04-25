from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.clinical_engine.contracts_api import AggregateClinicalReportPayload, PatientInfo
from app.services.clinical_engine.example_payload import build_demo_core
from app.services.clinical_engine.report_api_service import build_api_payload_from_current_result
from app.services.clinical_engine.serializers import build_aggregate_payload


router = APIRouter(prefix="/api/reports", tags=["reports"])


class CurrentPipelinePayload(BaseModel):
    result: dict
    patient: dict | None = None


@router.get("/summary/demo", response_model=AggregateClinicalReportPayload)
def get_summary_demo():
    core = build_demo_core()
    payload = build_aggregate_payload(
        core=core,
        patient=PatientInfo(
            display_name="Константинова М. Д.",
            sex="Ж",
            age=47,
        ),
    )
    return payload


@router.post("/summary/from-current", response_model=AggregateClinicalReportPayload)
def get_summary_from_current(payload: CurrentPipelinePayload):
    return build_api_payload_from_current_result(
        current_result=payload.result,
        patient_info=payload.patient,
    )
