# -*- coding: utf-8 -*-
"""
Bayesian inference для диагностики: обновление вероятности по симптомам.
"""
from __future__ import annotations

from typing import Any


def bayes_update(prior: float, likelihood: float) -> float:
    """Обновление апостериорной вероятности по одному признаку."""
    numerator = prior * likelihood
    denominator = numerator + (1.0 - prior) * (1.0 - likelihood)
    if denominator == 0:
        return prior
    return numerator / denominator


def disease_probability(symptom_ids: list[str], disease: dict[str, Any]) -> float:
    """
    Вероятность болезни по списку id симптомов.
    prior и symptom_likelihoods берутся из disease; при отсутствии — дефолты.
    """
    prior = float(disease.get("prior", 0.01))
    likelihoods = disease.get("symptom_likelihoods") or {}
    prob = prior
    for s in symptom_ids or []:
        likelihood = float(likelihoods.get(s, 0.2))
        prob = bayes_update(prob, likelihood)
    return prob


def bayesian_rank(
    symptom_ids: list[str],
    diseases: list[dict[str, Any]],
) -> list[tuple[float, dict[str, Any]]]:
    """Ранжирует болезни по апостериорной вероятности. Возвращает до 5 пар (prob, disease)."""
    ranked: list[tuple[float, dict[str, Any]]] = []
    for d in diseases or []:
        p = disease_probability(symptom_ids, d)
        ranked.append((p, d))
    ranked.sort(key=lambda x: -x[0])
    return ranked[:5]
