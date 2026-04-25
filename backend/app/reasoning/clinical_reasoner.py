# -*- coding: utf-8 -*-
"""
Clinical reasoner: объединяет граф диагнозов, confidence, объяснения и дифференциальный диагноз.
"""
from __future__ import annotations

from typing import Any

try:
    from app.reasoning.medical_graph_engine import rank_diseases, symptom_to_id
except Exception:
    rank_diseases = symptom_to_id = None
try:
    from app.reasoning.confidence_engine import calculate_confidence
except Exception:
    calculate_confidence = None
try:
    from app.reasoning.differential_diagnosis_engine import differential_diagnosis
except Exception:
    differential_diagnosis = None
try:
    from app.reasoning.explainable_engine import explain_diagnosis
except Exception:
    explain_diagnosis = None


def clinical_reason(symptoms: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Симптомы (русские фразы или id) → ранжирование, confidence, объяснения, дифференциал.
    Возвращает (diagnosis_candidates, differential).
    """
    if not rank_diseases:
        return [], []
    ranked = rank_diseases(symptoms or [])
    if not ranked:
        return [], []

    symptom_ids: list[str] = []
    if symptom_to_id:
        for s in symptoms or []:
            sid = symptom_to_id(s)
            if sid and sid not in symptom_ids:
                symptom_ids.append(sid)

    results: list[dict[str, Any]] = []
    for score, disease in ranked:
        confidence_val = 0.0
        if calculate_confidence:
            try:
                confidence_val = calculate_confidence(symptom_ids, disease)
            except Exception:
                confidence_val = min(1.0, score / 20.0)
        else:
            confidence_val = min(1.0, score / 20.0)

        explanation: list[str] = []
        if explain_diagnosis:
            try:
                explanation = explain_diagnosis(disease, symptom_ids)
            except Exception:
                pass

        results.append({
            "disease": disease.get("name") or disease.get("id", ""),
            "confidence": round(confidence_val, 2),
            "explanation": explanation,
        })

    differential: list[dict[str, Any]] = []
    if differential_diagnosis:
        try:
            differential = differential_diagnosis(ranked)
        except Exception:
            differential = [
                {"disease": d.get("name") or d.get("id", ""), "score": sc, "confidence": min(1.0, sc / 20.0)}
                for sc, d in ranked
            ]
    else:
        differential = [
            {"disease": d.get("name") or d.get("id", ""), "score": sc, "confidence": min(1.0, sc / 20.0)}
            for sc, d in ranked
        ]

    return results, differential
