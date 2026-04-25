# Profiles определяют, какие rules применять для данного document_type/profile.
from app.services.clinical_engine.profiles.biochemistry_blood import interpret_biochemistry_blood
from app.services.clinical_engine.profiles.lipid_panel import interpret_lipids
from app.services.clinical_engine.profiles.organic_acids_urine import interpret_organic_acids_urine
from app.services.clinical_engine.profiles.fallback_generic_lab import interpret_fallback_generic

__all__ = [
    "interpret_lipids",
    "interpret_biochemistry_blood",
    "interpret_organic_acids_urine",
    "interpret_fallback_generic",
]
