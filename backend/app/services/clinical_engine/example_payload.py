from app.services.clinical_engine.contracts_api import (
    ClinicalCoreResult,
    DerivedIndex,
    Finding,
    Hypothesis,
    LabValue,
    NextStep,
    PatientInfo,
    RiskAssessment,
    SourceDocumentSummary,
)
from app.services.clinical_engine.serializers import build_aggregate_payload


def build_demo_core() -> ClinicalCoreResult:
    return ClinicalCoreResult(
        material="mixed",
        material_confidence=0.99,
        document_type="aggregate",
        profile="aggregate",
        summary_level="multi_document",
        normalized_values={
            "ldl_cholesterol": LabValue(code="ldl_cholesterol", label="ЛПНП", value=6.09, unit="ммоль/л"),
            "total_cholesterol": LabValue(code="total_cholesterol", label="Общий холестерин", value=9.54, unit="ммоль/л"),
            "fructosamine": LabValue(code="fructosamine", label="Фруктозамин", value=301.79, unit="мкмоль/л"),
            "hba1c": LabValue(code="hba1c", label="HbA1c", value=5.1, unit="%"),
        },
        documents=[
            SourceDocumentSummary(
                document_id="doc_1",
                document_type="biochemistry_blood",
                material="blood",
                title="Биохимия крови",
                main_conclusion="Выраженная дислипидемия",
                priority="high",
            ),
            SourceDocumentSummary(
                document_id="doc_2",
                document_type="urinalysis",
                material="urine",
                title="Общий анализ мочи",
                main_conclusion="Без признаков ИМП; слабый сигнал по крови",
                priority="medium",
            ),
            SourceDocumentSummary(
                document_id="doc_3",
                document_type="cbc",
                material="blood",
                title="Общий анализ крови",
                main_conclusion="Без анемии и выраженного воспалительного сдвига",
                priority="low",
            ),
        ],
        final_findings=[
            Finding(
                code="marked_ldl_elevation",
                title="Значимое повышение ЛПНП",
                group="Липидный обмен",
                severity="high",
                document_id="doc_1",
                primary_marker="ldl_cholesterol",
                value="6.09",
                reference="<3.0",
                comment="Повышенный атерогенный риск",
            ),
            Finding(
                code="severe_hypercholesterolemia",
                title="Выраженная гиперхолестеринемия",
                group="Липидный обмен",
                severity="high",
                document_id="doc_1",
                primary_marker="total_cholesterol",
                value="9.54",
                reference="3.5–6.2",
                comment="Клинически значимая дислипидемия",
            ),
            Finding(
                code="fructosamine_elevated",
                title="Повышен фруктозамин",
                group="Углеводный обмен",
                severity="mild",
                document_id="doc_1",
                primary_marker="fructosamine",
                value="301.79",
                reference="205–285",
                comment="Оценка углеводного обмена в динамике",
            ),
        ],
        group_interpretations=[
            {
                "group": "Липидный обмен",
                "supporting_markers": ["Общий холестерин", "ЛПНП"],
                "interpretation": "Выраженная атерогенная дислипидемия",
            },
            {
                "group": "Углеводный обмен",
                "supporting_markers": ["HbA1c", "Фруктозамин"],
                "interpretation": "HbA1c в пределах референса, но фруктозамин повышен",
            },
            {
                "group": "Мочевой осадок",
                "supporting_markers": ["лейкоциты", "нитриты", "бактерии"],
                "interpretation": "Признаков воспалительного процесса не выявлено",
            },
            {
                "group": "Эритроциты, гемоглобин",
                "supporting_markers": ["Hb", "RBC", "Hct"],
                "interpretation": "Признаков анемии не выявлено",
            },
        ],
        working_hypotheses=[
            Hypothesis(code="atherogenic_dyslipidemia", label="Атерогенная дислипидемия", confidence=0.95),
            Hypothesis(
                code="possible_familial_hypercholesterolemia",
                label="Возможна первичная/семейная гиперхолестеринемия",
                confidence=0.7,
            ),
        ],
        next_steps=[
            NextStep(
                domain="Липидный обмен",
                what="Повторная липидограмма натощак",
                why="Подтверждение стойкости отклонений",
                priority="high",
            ),
            NextStep(
                domain="Липидный обмен",
                what="ApoB / Липопротеин(a)",
                why="Уточнение атерогенной нагрузки",
                priority="medium",
            ),
            NextStep(
                domain="Эндокринология",
                what="ТТГ",
                why="Исключение вторичных причин дислипидемии",
                priority="medium",
            ),
            NextStep(
                domain="Углеводный обмен",
                what="Глюкоза натощак",
                why="Уточнение углеводного обмена",
                priority="medium",
            ),
        ],
        derived_indices=[
            DerivedIndex(
                code="bmi",
                title="ИМТ",
                value=20.7,
                unit="кг/м²",
                status="normal",
                interpretation="Норма",
                required_markers=["height_cm", "weight_kg"],
                confidence="established",
                patient_visible=True,
            ),
            DerivedIndex(
                code="nlr",
                title="NLR",
                value=0.95,
                status="low_range",
                interpretation="Без признаков выраженного системного воспалительного сигнала",
                required_markers=["neutrophils_abs", "lymphocytes_abs"],
                confidence="supportive",
                patient_visible=False,
            ),
        ],
        risk=[
            RiskAssessment(
                domain="cardiometabolic",
                level="high",
                score=7,
                label="Высокий кардиометаболический риск",
                drivers=["ЛПНП 6.09", "Общий холестерин 9.54"],
                summary="Основной риск связан с выраженной дислипидемией",
            )
        ],
        limitations=[
            "Интерпретация не заменяет очную оценку врача.",
            "Изолированные лабораторные данные не позволяют установить диагноз без клинического контекста.",
        ],
        urgency=[
            "Срочно обращаться за помощью нужно при боли в груди, выраженной одышке или резком ухудшении состояния.",
        ],
    )


if __name__ == "__main__":
    core = build_demo_core()
    payload = build_aggregate_payload(
        core=core,
        patient=PatientInfo(display_name="Константинова М. Д.", sex="Ж", age=47),
    )
    print(payload.model_dump_json(indent=2, exclude_none=True))
