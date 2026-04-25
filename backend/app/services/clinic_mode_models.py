"""
Модели B2B / Clinic: аккаунт клиники, настройки отчётов, контекст доступа.
Подготовка к white-label и брендированным отчётам.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ClinicAccount:
    clinic_id: str = ""
    name: str = ""
    branding: Optional[Dict[str, Any]] = None  # logo_url, primary_color, etc.
    seats: int = 0
    enabled_features: List[str] = field(default_factory=list)


@dataclass
class ClinicReportPreferences:
    logo_url: Optional[str] = None
    clinic_name: Optional[str] = None
    doctor_footer: Optional[str] = None
    show_branding: bool = True
    export_format_preferences: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClinicAccessContext:
    clinic_id: Optional[str] = None
    operator_user_id: Optional[str] = None
    role: str = "member"  # admin / member / viewer
    permissions: List[str] = field(default_factory=list)
