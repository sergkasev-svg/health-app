"""P1 клинические паттерны (связки маркеров)."""

from app.services.clinical_engine.clinical_rules.p1_patterns.glucose_patterns import run_glucose_patterns
from app.services.clinical_engine.clinical_rules.p1_patterns.hematology_patterns import run_hematology_patterns
from app.services.clinical_engine.clinical_rules.p1_patterns.inflammation_patterns import run_inflammation_patterns
from app.services.clinical_engine.clinical_rules.p1_patterns.lipid_patterns import run_lipid_patterns
from app.services.clinical_engine.clinical_rules.p1_patterns.vitamin_patterns import run_vitamin_patterns

__all__ = [
    "run_hematology_patterns",
    "run_lipid_patterns",
    "run_glucose_patterns",
    "run_vitamin_patterns",
    "run_inflammation_patterns",
]
