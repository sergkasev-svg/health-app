# -*- coding: utf-8 -*-
"""
Knowledge Graph диагностика: симптомы → болезни.
Использует medical_knowledge/symptom_cause_graph (causes/*.json, symptoms/*.json).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_GRAPH: list[dict[str, Any]] = []
_ALIAS_TO_SYMPTOM_ID: dict[str, str] = {}
_LOADED = False


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2].parent


def load_graph() -> None:
    """Загружает причины (causes) и алиасы симптомов (symptoms) из symptom_cause_graph."""
    global _GRAPH, _ALIAS_TO_SYMPTOM_ID, _LOADED
    if _LOADED:
        return
    root = _project_root()
    base = root / "medical_knowledge" / "symptom_cause_graph"
    diseases: list[dict[str, Any]] = []
    for fp in sorted((base / "causes").glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            diseases.append({
                "id": data.get("id", fp.stem),
                "name": data.get("name", fp.stem),
                "major_symptoms": list(data.get("common_symptoms", [])),
                "minor_symptoms": list(data.get("minor_symptoms", [])),
                "category": data.get("category", ""),
                "red_flag_condition": bool(data.get("red_flag_condition", False)),
                "lab_markers": dict(data.get("lab_markers", {})),
            })
        except Exception:
            continue
    _GRAPH = diseases

    for fp in sorted((base / "symptoms").glob("*.json")):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            sid = str(data.get("id", fp.stem)).strip()
            for alias in data.get("aliases", []):
                a = str(alias or "").strip().lower()
                if a:
                    _ALIAS_TO_SYMPTOM_ID[a] = sid
            _ALIAS_TO_SYMPTOM_ID[sid.lower()] = sid
        except Exception:
            continue
    _LOADED = True


def symptom_to_id(symptom: str) -> str | None:
    """Преобразует текст симптома (русский или id) в id из графа."""
    load_graph()
    s = (symptom or "").strip().lower()
    if not s:
        return None
    if s in _ALIAS_TO_SYMPTOM_ID:
        return _ALIAS_TO_SYMPTOM_ID[s]
    for alias, sid in _ALIAS_TO_SYMPTOM_ID.items():
        if alias in s or s in alias:
            return sid
    return None


def score_disease(symptom_ids: list[str], disease: dict[str, Any]) -> int:
    major = set(disease.get("major_symptoms") or [])
    minor = set(disease.get("minor_symptoms") or [])
    score = 0
    for sid in symptom_ids:
        if sid in major:
            score += 5
        elif sid in minor:
            score += 2
    return score


def rank_diseases(symptoms: list[str]) -> list[tuple[int, dict[str, Any]]]:
    """
    Ранжирует болезни по списку симптомов (русские фразы или id).
    Возвращает до 5 пар (score, disease).
    """
    load_graph()
    ids: list[str] = []
    for s in symptoms or []:
        sid = symptom_to_id(s)
        if sid and sid not in ids:
            ids.append(sid)
    if not ids:
        for s in symptoms or []:
            s_low = (s or "").strip().lower()
            if s_low and s_low not in _ALIAS_TO_SYMPTOM_ID:
                for alias, sid in _ALIAS_TO_SYMPTOM_ID.items():
                    if alias in s_low or s_low in alias:
                        if sid not in ids:
                            ids.append(sid)
                        break
    ranked: list[tuple[int, dict[str, Any]]] = []
    for d in _GRAPH:
        sc = score_disease(ids, d)
        if sc > 0:
            ranked.append((sc, d))
    ranked.sort(key=lambda x: -x[0])
    return ranked[:5]


def get_diseases_for_bayesian() -> list[dict[str, Any]]:
    """
    Возвращает список болезней в формате для Bayesian/Lab evidence.
    Если есть graph.json (V7 self-learning), использует его symptom_likelihoods.
    """
    graph_path = _project_root() / "medical_knowledge" / "symptom_cause_graph" / "graph.json"
    if graph_path.exists():
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            diseases = graph.get("diseases", [])
            if diseases:
                return [
                    {
                        "id": d.get("id"),
                        "name": d.get("name"),
                        "major_symptoms": list(d.get("major_symptoms") or []),
                        "minor_symptoms": list(d.get("minor_symptoms") or []),
                        "prior": float(d.get("prior", 0.01)),
                        "symptom_likelihoods": dict(d.get("symptom_likelihoods") or {}),
                        "lab_markers": dict(d.get("lab_markers") or {}),
                        "category": d.get("category", ""),
                    }
                    for d in diseases
                ]
        except Exception:
            pass
    load_graph()
    out: list[dict[str, Any]] = []
    for d in _GRAPH:
        major = list(d.get("major_symptoms") or [])
        minor = list(d.get("minor_symptoms") or [])
        likelihoods: dict[str, float] = {s: 0.7 for s in major}
        for s in minor:
            likelihoods.setdefault(s, 0.4)
        prior = float(d.get("prior", 0.02 if d.get("red_flag_condition") else 0.01))
        lab_markers = dict(d.get("lab_markers") or {}) if d.get("lab_markers") else {}
        out.append({
            "id": d.get("id"),
            "name": d.get("name"),
            "major_symptoms": major,
            "minor_symptoms": minor,
            "prior": prior,
            "symptom_likelihoods": likelihoods,
            "lab_markers": lab_markers,
            "category": d.get("category", ""),
        })
    return out
