"""
Единый интерфейс клинического профиля для «За Здоровье».
Все профили (CBC, Urinalysis, Biochemistry, Lipids, Glucose, Iron, Thyroid, и т.д.)
реализуют один контракт для согласованной сборки отчёта.

Реестр экземпляров: profile_registry.get_all_profiles() / get_profile_registry().
Каталог приоритетов и roadmap: profile_catalog.PROFILE_CATALOG, docs/CLINICAL_PROFILE_ROADMAP.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.services.clinical_engine.contracts import Finding, LabValue, OverallRisk


class ClinicalProfile(ABC):
    """
    Контракт профиля анализа.
    values — результат extract_values (List[LabValue] или profile-specific dict).
    """

    # Идентификаторы профиля
    profile_key: str = ""
    document_type: str = ""
    priority: int = 3  # P0=0, P1=1, P2=2, P3=3

    def extract_values(self, text: str) -> Any:
        """
        Извлечь значения из сырого текста.
        Возвращает List[LabValue] или dict (для CBC/urinalysis — profile-specific).
        """
        raise NotImplementedError

    def classify_subprofile(self, values: Any, text: str) -> str:
        """
        Уточнить подпрофиль по значениям и тексту (например cbc -> cbc_with_reticulocytes).
        Возвращает profile_key подпрофиля или self.profile_key.
        """
        return self.profile_key

    def build_findings(self, values: Any) -> List[Finding]:
        """Собрать клинические находки (abnormal/borderline)."""
        raise NotImplementedError

    def build_group_interpretation(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        """
        Групповая интерпретация: список {group, markers, interpretation}.
        Не должен быть пустым для нормального UX — хотя бы группы «в норме».
        """
        raise NotImplementedError

    def build_hypotheses(self, values: Any, findings: List[Finding]) -> List[str]:
        """Рабочие гипотезы для врача."""
        raise NotImplementedError

    def build_next_steps(self, values: Any, findings: List[Finding]) -> List[Dict[str, Any]]:
        """Рекомендации: список {direction, check, why, priority}."""
        raise NotImplementedError

    def build_risk(self, values: Any, findings: List[Finding], hypotheses: List[str]) -> Optional[OverallRisk]:
        """Оценка риска (overall_level, primary_domain, summary_text, urgency)."""
        raise NotImplementedError

    def build_legacy_report(self, extracted_text: str, filename: str = "") -> Optional[Dict[str, Any]]:
        """
        Собрать legacy-словарь отчёта для physician_report.
        По умолчанию — не реализовано; существующие движки (cbc_engine, urinalysis_engine, pipeline)
        возвращают legacy сами. После миграции сюда переносится сборка из 6 методов выше.
        """
        return None
