# -*- coding: utf-8 -*-
"""
Probabilistic diagnosis: Bayesian ранжирование + учёт лабораторий.
"""
from __future__ import annotations

from typing import Any

try:
    from app.reasoning.bayesian_diagnosis_engine import bayesian_rank
except Exception:
    bayesian_rank = None
try:
    from app.reasoning.lab_evidence_engine import lab_weight
except Exception:
    lab_weight = None
try:
    from app.reasoning.medical_graph_engine import get_diseases_for_bayesian, symptom_to_id
except Exception:
    get_diseases_for_bayesian = symptom_to_id = None


def _symptoms_to_ids(symptoms: list[str]) -> list[str]:
    ids: list[str] = []
    for s in symptoms or []:
        if not symptom_to_id:
            ids.append((s or "").strip().lower())
            continue
        sid = symptom_to_id(s)
        if sid and sid not in ids:
            ids.append(sid)
    return ids


def probabilistic_diagnosis(
    symptoms: list[str],
    labs: dict[str, Any] | None = None,
    diseases: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Симптомы (русские или id), labs (marker -> value), опционально список diseases.
    Возвращает до 5 записей {disease, probability}.
    """
    if not bayesian_rank:
        return []
    symptom_ids = _symptoms_to_ids(symptoms or [])
    if diseases is None and get_diseases_for_bayesian:
        try:
            diseases = get_diseases_for_bayesian()
        except Exception:
            diseases = []
    if not diseases:
        return []
    labs = labs or {}
    ranked = bayesian_rank(symptom_ids, diseases)
    results: list[dict[str, Any]] = []
    for prob, disease in ranked:
        add = 0.0
        if lab_weight:
            try:
                add = lab_weight(labs, disease)
            except Exception:
                pass
        results.append({
            "disease": disease.get("name") or disease.get("id", ""),
            "probability": round(min(1.0, prob + add), 4),
        })
    results.sort(key=lambda x: -x["probability"])
    return results[:5]
