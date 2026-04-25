# -*- coding: utf-8 -*-
"""
Probability Update Engine (V7): обновляет symptom_likelihoods в графе по подтверждённому диагнозу.
"""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2].parent
GRAPH_PATH = _PROJECT_ROOT / "medical_knowledge" / "symptom_cause_graph" / "graph.json"
_CAUSES_DIR = _PROJECT_ROOT / "medical_knowledge" / "symptom_cause_graph" / "causes"


def _build_graph_from_causes() -> dict:
    """Собирает граф из causes/*.json, если graph.json отсутствует."""
    diseases: list[dict] = []
    if not _CAUSES_DIR.exists():
        return {"diseases": diseases}
    for fp in sorted(_CAUSES_DIR.glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            major = list(data.get("common_symptoms", []))
            minor = list(data.get("minor_symptoms", []))
            likelihoods: dict[str, float] = {s: 0.7 for s in major}
            for s in minor:
                likelihoods.setdefault(s, 0.4)
            diseases.append({
                "name": data.get("id", fp.stem),
                "id": data.get("id", fp.stem),
                "prior": 0.02 if data.get("red_flag_condition") else 0.01,
                "major_symptoms": major,
                "minor_symptoms": minor,
                "symptom_likelihoods": likelihoods,
                "lab_markers": dict(data.get("lab_markers", {})),
            })
        except Exception:
            continue
    return {"diseases": diseases}


def update_probabilities(symptoms: list[str], confirmed_disease: str) -> None:
    if not confirmed_disease:
        return
    from app.reasoning.medical_graph_engine import symptom_to_id
    symptom_ids: list[str] = []
    for s in symptoms or []:
        if not s:
            continue
        sid = symptom_to_id(s)
        if sid and sid not in symptom_ids:
            symptom_ids.append(sid)
        elif s.strip() and s not in symptom_ids:
            symptom_ids.append(s.strip())
    if not symptom_ids:
        return
    if GRAPH_PATH.exists():
        graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    else:
        graph = _build_graph_from_causes()
        GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
    diseases = graph.get("diseases", [])
    for disease in diseases:
        if disease.get("name") == confirmed_disease or disease.get("id") == confirmed_disease:
            likelihoods = dict(disease.get("symptom_likelihoods", {}))
            for s in symptom_ids:
                likelihoods[s] = min(0.95, likelihoods.get(s, 0.2) + 0.05)
            disease["symptom_likelihoods"] = likelihoods
            break
    GRAPH_PATH.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
