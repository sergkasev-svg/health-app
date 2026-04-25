# -*- coding: utf-8 -*-
"""
Системный triage: приоритет ветки при сочетании системных признаков (инфекция) и органа.
Например: температура + поясница/почки → urinary.
"""
from __future__ import annotations

try:
    from app.services.symptom_cluster_engine import detect_clusters
except Exception:
    detect_clusters = None


def triage_priority(text: str) -> str | None:
    """
    Возвращает приоритетную ветку при системных признаках и органе, иначе None.
    """
    if not text or not detect_clusters:
        return None
    clusters = detect_clusters(text)
    if clusters.get("systemic") and clusters.get("kidney"):
        return "urinary"
    if clusters.get("systemic") and clusters.get("urinary"):
        return "urinary"
    return None
