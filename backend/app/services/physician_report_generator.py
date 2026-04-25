"""
Генератор врачебного отчёта: структурированный SOAP/Assessment/Plan из данных оркестратора.
Отделение user-facing от doctor-facing; фильтр мусорных диагнозов.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.physician_report_models import (
    ClinicalAssessment,
    ClinicalPlan,
    LabFinding,
    PatientInfo,
    PhysicianReport,
    SymptomSummary,
)


# Диагнозы/гипотезы, которые убираем без явной связи с данными
NOISE_HYPOTHESES = [
    "малярия",
    "сепсис",
    "импетиго",
    "covid",
    "ковид",
    "sars-cov",
    "лихорадка денге",
    "эбола",
    "менингококц",
    "дифтерия",
    "столбняк",
]


def _float_or_none(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class PhysicianReportGenerator:
    """
    Строит PhysicianReport из orchestrator output, context и memory.
    Только клинически релевантное; без галлюцинаций и мусора.
    """

    MAX_SYMPTOMS = 5
    MAX_LABS = 10
    MAX_HYPOTHESES = 3
    MAX_DIFFERENTIAL = 3

    def generate(
        self,
        orchestrator_output: Any,
        context: Any,
        memory: Optional[Any] = None,
    ) -> PhysicianReport:
        """Главный метод: собрать отчёт из доступных данных."""
        report = PhysicianReport(
            patient_info=self._extract_patient_info(context),
            symptoms=self._build_symptom_summary(context, memory),
            labs=self._build_lab_findings(context, memory),
            assessment=ClinicalAssessment(),
            plan=ClinicalPlan(),
            red_flags=self._red_flags_from_context(context),
            notes=None,
        )
        report.assessment = self._build_assessment(orchestrator_output, context)
        report.plan = self._build_plan(orchestrator_output, context)
        report = self._filter_noise(report)
        return self._finalize_report(report)

    def _extract_patient_info(self, context: Any) -> PatientInfo:
        age = None
        sex = None
        if context is None:
            return PatientInfo(age=age, sex=sex)
        profile = getattr(context, "profile", None) or (context if isinstance(context, dict) else {}).get("profile") or {}
        if isinstance(profile, dict):
            a = profile.get("age") or profile.get("birth_year")
            if a is not None:
                try:
                    age = int(a)
                    if profile.get("birth_year") and age > 0 and age < 150:
                        from datetime import datetime
                        age = datetime.now().year - int(profile["birth_year"])
                except (TypeError, ValueError):
                    pass
            sex = profile.get("sex") or profile.get("gender")
        return PatientInfo(age=age, sex=sex)

    def _build_symptom_summary(self, context: Any, memory: Optional[Any]) -> SymptomSummary:
        key_symptoms: List[str] = []
        duration: Optional[str] = None
        progression: Optional[str] = None

        norm = getattr(context, "normalized_symptoms", None) or (context if isinstance(context, dict) else {}).get("normalized_symptoms") or []
        for s in norm[: self.MAX_SYMPTOMS]:
            if s and isinstance(s, str) and s.strip():
                key_symptoms.append(s.strip())

        if memory and getattr(memory, "symptoms", None):
            seen = {x.lower() for x in key_symptoms}
            for rec in memory.symptoms:
                name = getattr(rec, "name", None) or (rec if isinstance(rec, dict) else {}).get("name") or ""
                if name and name.strip().lower() not in seen:
                    key_symptoms.append(name.strip())
                    seen.add(name.strip().lower())
                    if len(key_symptoms) >= self.MAX_SYMPTOMS:
                        break

        key_symptoms = key_symptoms[: self.MAX_SYMPTOMS]
        return SymptomSummary(key_symptoms=key_symptoms, duration=duration, progression=progression)

    def _build_lab_findings(self, context: Any, memory: Optional[Any]) -> List[LabFinding]:
        findings: List[LabFinding] = []
        rows = getattr(context, "lab_rows", None) or (context if isinstance(context, dict) else {}).get("lab_rows") or []

        for row in rows[: self.MAX_LABS * 2]:
            if not isinstance(row, dict):
                continue
            title = (row.get("title") or row.get("marker_name") or row.get("name") or "").strip()
            if not title:
                continue
            value = _float_or_none(row.get("value"))
            unit = row.get("unit")
            flag = row.get("flag")
            ref_low = _float_or_none(row.get("ref_low"))
            ref_high = _float_or_none(row.get("ref_high"))

            if flag is None and value is not None:
                if ref_low is not None and value < ref_low:
                    flag = "low"
                elif ref_high is not None and value > ref_high:
                    flag = "high"
                else:
                    flag = "normal"

            interp = self._interpret_marker(title, value, flag, ref_low, ref_high)
            findings.append(
                LabFinding(marker=title, value=value, unit=unit, flag=flag, interpretation=interp)
            )
            if len(findings) >= self.MAX_LABS:
                break

        if len(findings) < self.MAX_LABS and memory and getattr(memory, "labs", None):
            seen_markers = {f.marker.lower() for f in findings}
            for lab in memory.labs:
                mn = getattr(lab, "marker_name", None) or (lab.marker_name if hasattr(lab, "marker_name") else "") or ""
                if not mn or mn.lower() in seen_markers:
                    continue
                val = getattr(lab, "value", None)
                flag = getattr(lab, "flag", None)
                interp = self._interpret_marker(mn, val, flag, None, None)
                findings.append(LabFinding(marker=mn, value=val, unit=getattr(lab, "unit", None), flag=flag, interpretation=interp))
                seen_markers.add(mn.lower())
                if len(findings) >= self.MAX_LABS:
                    break

        return findings[: self.MAX_LABS]

    def _interpret_marker(
        self,
        marker: str,
        value: Optional[float],
        flag: Optional[str],
        ref_low: Optional[float],
        ref_high: Optional[float],
    ) -> Optional[str]:
        m = (marker or "").lower()
        if not m:
            return None
        if flag == "normal":
            return None
        if "гемоглобин" in m or "hemoglobin" in m or "hgb" in m or "hb " in m:
            return "↓ возможно анемия" if flag == "low" else ("↑ полицитемия?" if flag == "high" else None)
        if "mch" in m:
            return "↓ возможен дефицит железа" if flag == "low" else None
        if "tsh" in m or "тиреотроп" in m:
            return "↑ гипотиреоз вероятен" if flag == "high" else ("↓ гипертиреоз?" if flag == "low" else None)
        if "свободный т4" in m or "free t4" in m or "ft4" in m:
            return "↑ гипертиреоз?" if flag == "high" else ("↓ гипотиреоз?" if flag == "low" else None)
        if "эозинофил" in m or "eosinophil" in m:
            return "↑ возможен аллергический процесс" if flag == "high" else None
        if "ферритин" in m or "ferritin" in m:
            return "↓ железодефицит вероятен" if flag == "low" else None
        if "лейкоцит" in m or "wbc" in m:
            return "↑ возможен инфекционный/воспалительный процесс" if flag == "high" else None
        if flag == "low":
            return "↓ ниже нормы"
        if flag == "high":
            return "↑ выше нормы"
        return None

    def _build_assessment(self, orchestrator_output: Any, context: Any) -> ClinicalAssessment:
        main: List[str] = []
        evidence: List[str] = []
        differential: List[str] = []

        out = orchestrator_output
        if out is None:
            return ClinicalAssessment(main_hypotheses=main, supporting_evidence=evidence, differential=differential)

        hyps = getattr(out, "user_hypotheses", None) or getattr(out, "likely_hypotheses", None) or (out if isinstance(out, dict) else {}).get("user_hypotheses") or (out if isinstance(out, dict) else {}).get("likely_hypotheses") or []
        for h in hyps[: self.MAX_HYPOTHESES * 2]:
            text = (h if isinstance(h, str) else (h.get("name") or h.get("title") or "")).strip()
            if not text:
                continue
            if self._is_noise_hypothesis(text):
                continue
            main.append(f"Данные могут соответствовать: {text}." if not text.startswith("Данные") and not text.startswith("Вероятно") else text)
            if len(main) >= self.MAX_HYPOTHESES:
                break

        struct = getattr(context, "structured_lab_report", None) or (context if isinstance(context, dict) else {}).get("structured_lab_report") or {}
        topics = (struct.get("hidden_debug") or struct.get("debug") or {}).get("topics") or []
        for t in topics[:3]:
            if t == "iron_deficiency":
                if not any("желез" in x.lower() or "анемия" in x.lower() for x in main):
                    main.append("Данные могут соответствовать железодефициту.")
                evidence.append("Hb/MCH/ферритин — паттерн ЖДА.")
            elif t == "thyroid_hypo":
                if not any("щитовид" in x.lower() or "гипотиреоз" in x.lower() for x in main):
                    main.append("Данные могут соответствовать гипотиреозу. Требует подтверждения.")
                evidence.append("TSH ↑ — контроль свободного T4.")
            elif t == "thyroid_hyper":
                if not any("гипертиреоз" in x.lower() or "тиреотоксикоз" in x.lower() for x in main):
                    main.append("Данные могут соответствовать гиперфункции щитовидной железы. Требует подтверждения.")
                evidence.append("TSH ↓, T4/T3 — консультация эндокринолога.")
            elif t == "possible_allergy":
                evidence.append("Эозинофилы ↑ — возможен аллергический компонент.")
            elif t == "infection_pattern":
                evidence.append("Лейкоциты/СРБ — возможен инфекционный процесс.")

        norm = getattr(context, "normalized_symptoms", None) or (context if isinstance(context, dict) else {}).get("normalized_symptoms") or []
        for s in norm[:3]:
            if s:
                evidence.append(f"Жалобы: {s}.")

        main = main[: self.MAX_HYPOTHESES]
        differential = self._differential_for_topics(topics, main)[: self.MAX_DIFFERENTIAL]
        return ClinicalAssessment(main_hypotheses=main, supporting_evidence=evidence, differential=differential)

    def _differential_for_topics(self, topics: List[str], main: List[str]) -> List[str]:
        diff: List[str] = []
        if "iron_deficiency" in topics or any("желез" in (m or "").lower() or "анемия" in (m or "").lower() for m in main):
            diff.extend(["Хроническое воспаление (анемия хронических болезней)", "B12/фолиеводефицитная анемия"])
        if "thyroid_hypo" in topics:
            diff.append("Вторичный гипотиреоз (исключить патологию гипофиза)")
        if "possible_allergy" in topics:
            diff.append("Другие причины эозинофилии (паразитозы — по эпиданамнезу)")
        return diff

    def _build_plan(self, orchestrator_output: Any, context: Any) -> ClinicalPlan:
        recommended_tests: List[str] = []
        referrals: List[str] = []
        follow_up: Optional[str] = None

        out = orchestrator_output
        if out:
            labs = getattr(out, "recommended_labs", None) or (out if isinstance(out, dict) else {}).get("recommended_labs") or []
            recommended_tests = [str(x).strip() for x in labs if x][:7]

        struct = getattr(context, "structured_lab_report", None) or (context if isinstance(context, dict) else {}).get("structured_lab_report") or {}
        topics = (struct.get("hidden_debug") or struct.get("debug") or {}).get("topics") or []
        state = getattr(out, "state", None) if out else (out.get("state") if isinstance(out, dict) else None)

        if "thyroid_hypo" in topics or "thyroid_hyper" in topics:
            referrals.append("Эндокринолог")
        if "iron_deficiency" in topics or "anemia_pattern" in topics:
            if "Терапевт" not in referrals and "терапевт" not in str(referrals).lower():
                referrals.append("Терапевт/гематолог при необходимости")
        if state == "doctor_soon" and not referrals:
            referrals.append("Терапевт")

        if state == "request_labs":
            follow_up = "Повторная оценка после получения анализов."
        elif state == "doctor_soon":
            follow_up = "Контроль после очной консультации."
        elif state == "self_care":
            follow_up = "Контроль через 3–7 дней при сохранении жалоб."

        return ClinicalPlan(recommended_tests=recommended_tests, referrals=referrals[:5], follow_up=follow_up)

    def _red_flags_from_context(self, context: Any) -> List[str]:
        flags = getattr(context, "red_flags", None) or (context if isinstance(context, dict) else {}).get("red_flags") or []
        return [str(f).strip() for f in flags if f][:10]

    def _is_noise_hypothesis(self, text: str) -> bool:
        t = (text or "").lower()
        return any(n in t for n in NOISE_HYPOTHESES)

    def _filter_noise(self, report: PhysicianReport) -> PhysicianReport:
        report.assessment.main_hypotheses = [h for h in report.assessment.main_hypotheses if not self._is_noise_hypothesis(h)]
        report.assessment.differential = [d for d in report.assessment.differential if not self._is_noise_hypothesis(d)]
        report.assessment.main_hypotheses = report.assessment.main_hypotheses[: self.MAX_HYPOTHESES]
        report.assessment.differential = report.assessment.differential[: self.MAX_DIFFERENTIAL]
        return report

    def _finalize_report(self, report: PhysicianReport) -> PhysicianReport:
        return report
