"""
Реестр клинических маршрутов: LAB / SYMPTOM / META.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RouteSpec:
    route_id: str
    title: str
    allowed_rule_sets: list[str] = field(default_factory=list)
    blocked_rule_sets: list[str] = field(default_factory=list)
    allowed_hypothesis_tags: list[str] = field(default_factory=list)
    blocked_hypothesis_tags: list[str] = field(default_factory=list)
    allowed_question_tags: list[str] = field(default_factory=list)
    blocked_question_tags: list[str] = field(default_factory=list)
    master_loader_hook: str | None = None


def _routes() -> dict[str, RouteSpec]:
    return {
        # --- LAB ---
        "cbc_route": RouteSpec(
            route_id="cbc_route",
            title="Общий анализ крови",
            allowed_rule_sets=["anemia_rules", "cbc_inflammation_rules", "platelet_rules", "allergy_pattern_rules"],
            blocked_rule_sets=["organic_acids_rules", "lipid_rules", "urinary_infection_rules"],
            allowed_hypothesis_tags=["anemia", "inflammation", "allergy_pattern", "platelet"],
            blocked_hypothesis_tags=["organic_acids", "lipid_primary", "uti", "thyroid_primary"],
            allowed_question_tags=["symptoms", "fatigue", "bleeding", "infection_signs"],
            blocked_question_tags=["food_trigger_wine_chocolate", "thyroid_symptoms_only"],
        ),
        "thyroid_route": RouteSpec(
            route_id="thyroid_route",
            title="Щитовидная железа",
            allowed_rule_sets=["thyroid_rules", "endocrine_rules"],
            blocked_rule_sets=["urinary_infection_rules", "organic_acids_rules"],
            allowed_hypothesis_tags=["thyroid", "endocrine"],
            blocked_hypothesis_tags=["uti", "cystitis", "organic_acids"],
            allowed_question_tags=["thyroid_symptoms", "weight_energy", "cold_heat"],
            blocked_question_tags=["urinary_symptoms", "food_trigger_wine_chocolate"],
        ),
        "lipid_route": RouteSpec(
            route_id="lipid_route",
            title="Липидный профиль",
            allowed_rule_sets=["lipid_rules", "cardio_risk_rules"],
            blocked_rule_sets=["organic_acids_rules", "urinary_infection_rules", "iron_rules"],
            allowed_hypothesis_tags=["dyslipidemia", "cardiovascular_risk"],
            blocked_hypothesis_tags=["uti", "organic_acids", "iron_deficiency_primary"],
            allowed_question_tags=["diet", "exercise", "family_history_cvd"],
            blocked_question_tags=["urinary_symptoms"],
        ),
        "iron_route": RouteSpec(
            route_id="iron_route",
            title="Железо / ферритин",
            allowed_rule_sets=["iron_rules", "anemia_rules"],
            blocked_rule_sets=["lipid_rules", "organic_acids_rules"],
            allowed_hypothesis_tags=["iron", "anemia"],
            blocked_hypothesis_tags=["organic_acids", "uti"],
            allowed_question_tags=["fatigue", "diet_iron", "menstrual"],
            blocked_question_tags=["food_trigger_wine_chocolate"],
        ),
        "biochemistry_basic_route": RouteSpec(
            route_id="biochemistry_basic_route",
            title="Биохимия (печень/почки/глюкоза)",
            allowed_rule_sets=["liver_rules", "kidney_rules", "glucose_rules"],
            blocked_rule_sets=["organic_acids_rules", "thyroid_rules"],
            allowed_hypothesis_tags=["liver", "kidney", "metabolic_glucose"],
            blocked_hypothesis_tags=["organic_acids", "thyroid_primary"],
            allowed_question_tags=["medications", "alcohol", "diabetes_symptoms"],
            blocked_question_tags=["food_trigger_wine_chocolate"],
        ),
        "urine_general_route": RouteSpec(
            route_id="urine_general_route",
            title="Общий анализ мочи",
            allowed_rule_sets=["urinary_rules", "kidney_rules"],
            blocked_rule_sets=["organic_acids_rules", "lipid_rules", "thyroid_rules"],
            allowed_hypothesis_tags=["uti", "kidney_urine", "inflammation_urine"],
            blocked_hypothesis_tags=["organic_acids", "thyroid_primary", "lipid_primary"],
            allowed_question_tags=["dysuria", "fever_uti", "flank_pain"],
            blocked_question_tags=["thyroid_symptoms_only"],
        ),
        "organic_acids_route": RouteSpec(
            route_id="organic_acids_route",
            title="Органические кислоты в моче",
            allowed_rule_sets=[
                "organic_acids_rules",
                "metabolic_pattern_rules",
                "vitamin_cofactor_rules",
                "toxic_exposure_rules",
            ],
            blocked_rule_sets=[
                "urinary_infection_rules",
                "histamine_food_trigger_rules",
                "migraine_food_rules",
                "lipid_rules",
                "thyroid_rules",
            ],
            allowed_hypothesis_tags=["metabolic", "cofactor", "energy_exchange", "toxic_exposure"],
            blocked_hypothesis_tags=["uti", "histamine", "food_allergy_like", "migraine_trigger", "lipid", "thyroid"],
            allowed_question_tags=["diet_general", "vitamins", "medications", "chemical_exposure", "dynamics"],
            blocked_question_tags=["food_trigger_beans_wine_chocolate_citrus", "urinary_symptoms"],
        ),
        "vitamin_deficiency_route": RouteSpec(
            route_id="vitamin_deficiency_route",
            title="Витамины / микроэлементы",
            allowed_rule_sets=["vitamin_rules", "mineral_rules"],
            blocked_rule_sets=["organic_acids_rules", "urinary_infection_rules"],
            allowed_hypothesis_tags=["vitamin", "mineral"],
            blocked_hypothesis_tags=["uti", "organic_acids"],
            allowed_question_tags=["diet", "supplements", "sun_exposure"],
            blocked_question_tags=["urinary_symptoms"],
        ),
        # --- SYMPTOM ---
        "respiratory_route": RouteSpec(
            route_id="respiratory_route",
            title="Дыхательные симптомы",
            allowed_rule_sets=["respiratory_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["respiratory", "infection_upper"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["cough", "fever", "breathing"],
            blocked_question_tags=[],
        ),
        "urinary_route": RouteSpec(
            route_id="urinary_route",
            title="Мочеполовые симптомы",
            allowed_rule_sets=["urinary_symptom_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["urinary_symptom"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["dysuria", "frequency"],
            blocked_question_tags=[],
        ),
        "abdominal_route": RouteSpec(
            route_id="abdominal_route",
            title="Боль в животе / ЖКТ",
            allowed_rule_sets=["gi_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["gi", "ibs_like"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["pain_site", "stool", "nausea"],
            blocked_question_tags=[],
        ),
        "food_reaction_master_route": RouteSpec(
            route_id="food_reaction_master_route",
            title="Пищевые реакции (master route)",
            allowed_rule_sets=["food_reaction_master"],
            blocked_rule_sets=["histamine_default_route"],
            allowed_hypothesis_tags=[
                "fatty_fried_overload",
                "functional_dyspepsia_or_gastric_irritation",
                "biliary_reaction",
                "pancreatic_overload",
                "reflux_trigger",
                "dairy_lactose_or_milk_sensitivity",
                "ibs_food_trigger",
                "histamine_trigger_conditional",
            ],
            blocked_hypothesis_tags=["histamine_as_default"],
            allowed_question_tags=["food_timing", "trigger_product", "red_flags", "stool_pattern", "reflux_pattern"],
            blocked_question_tags=["non_food_irrelevant_followup"],
            master_loader_hook="food_reaction_master",
        ),
        "upper_abdominal_master_route": RouteSpec(
            route_id="upper_abdominal_master_route",
            title="Верхняя часть живота (patient-safe master)",
            allowed_rule_sets=["upper_abdominal_pain_master"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=[
                "functional_dyspepsia_or_gastric_irritation",
                "fatty_food_overload",
                "reflux_or_postprandial_reflux",
                "biliary_pattern",
                "simple_overeating",
                "ulcer_or_gastritis_risk_pattern",
                "pancreatic_warning_pattern",
                "urgent_general_abdominal_route",
            ],
            blocked_hypothesis_tags=["ibs_as_primary_without_bowel_pattern"],
            allowed_question_tags=["epigastric_pain", "meal_timing", "reflux_pattern", "ruq_pattern", "red_flags"],
            blocked_question_tags=["non_gi_irrelevant_followup"],
            master_loader_hook="upper_abdominal_master",
        ),
        "postmeal_bloating_master_route": RouteSpec(
            route_id="postmeal_bloating_master_route",
            title="После еды: вздутие/понос (patient-safe master)",
            allowed_rule_sets=["postmeal_bloating_diarrhea_master"],
            blocked_rule_sets=["dysbiosis_default_route"],
            allowed_hypothesis_tags=[
                "simple_overeating_or_fast_eating",
                "lactose_or_dairy_pattern",
                "fodmap_fermentation_pattern",
                "food_triggered_ibs_pattern",
                "fatty_food_bowel_trigger",
                "acute_infectious_gastroenteritis_pattern",
                "carbohydrate_malabsorption_pattern",
                "bile_acid_or_post_cholecystectomy_pattern_conditional",
                "alarm_non_functional_bowel_route",
            ],
            blocked_hypothesis_tags=["ibs_single_episode", "dysbiosis_default"],
            allowed_question_tags=["dairy_trigger", "fodmap_trigger", "stool_change", "dehydration_red_flags"],
            blocked_question_tags=["rare_exotic_without_pattern"],
            master_loader_hook="postmeal_bloating_master",
        ),
        "postmeal_systemic_master_route": RouteSpec(
            route_id="postmeal_systemic_master_route",
            title="После еды: тошнота/слабость/голова (patient-safe master)",
            allowed_rule_sets=["postmeal_nausea_weakness_headache_master"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=[
                "fatty_food_systemic_overload",
                "postprandial_vascular_reaction",
                "sugar_glucose_reaction",
                "simple_overeating",
                "mild_dehydration_pattern",
                "histamine_conditional_pattern",
                "alcohol_related_pattern",
                "combined_food_trigger_pattern",
                "alarm_systemic_route",
            ],
            blocked_hypothesis_tags=["histamine_as_default"],
            allowed_question_tags=["fatty_trigger", "sugar_trigger", "vascular_symptoms", "systemic_red_flags"],
            blocked_question_tags=["narrow_gi_only_assumption"],
            master_loader_hook="postmeal_systemic_master",
        ),
        "food_symptom_super_master_route": RouteSpec(
            route_id="food_symptom_super_master_route",
            title="Единый food symptom super master",
            allowed_rule_sets=["food_symptom_super_master"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=[
                "functional_dyspepsia",
                "fatty_food_overload",
                "reflux_pattern",
                "biliary_pattern",
                "dairy_lactose_pattern",
                "fodmap_fermentation_pattern",
                "postprandial_vascular_pattern",
                "simple_overeating",
                "urgent_general_route",
            ],
            blocked_hypothesis_tags=["histamine_as_default", "ibs_single_episode", "dysbiosis_default"],
            allowed_question_tags=["zone_detection", "trigger_detection", "red_flags", "recurrent_pattern"],
            blocked_question_tags=["overdiagnosis_rare_patterns"],
            master_loader_hook="food_symptom_super_master",
        ),
        "neuro_route": RouteSpec(
            route_id="neuro_route",
            title="Неврологические симптомы",
            allowed_rule_sets=["neuro_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["neuro", "headache"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["headache_onset", "neuro_deficit"],
            blocked_question_tags=[],
        ),
        "allergy_route": RouteSpec(
            route_id="allergy_route",
            title="Аллергия / сыпь",
            allowed_rule_sets=["allergy_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["allergy", "urticaria"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["rash", "food_exposure", "medications_allergy"],
            blocked_question_tags=[],
        ),
        "endocrine_route": RouteSpec(
            route_id="endocrine_route",
            title="Эндокринные жалобы",
            allowed_rule_sets=["endocrine_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["endocrine", "thyroid_symptom"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["weight", "heat_cold", "thirst"],
            blocked_question_tags=[],
        ),
        "constitutional_route": RouteSpec(
            route_id="constitutional_route",
            title="Слабость / утомляемость (неспецифично)",
            allowed_rule_sets=["constitutional_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["fatigue", "constitutional"],
            blocked_hypothesis_tags=[],
            allowed_question_tags=["sleep", "stress", "duration"],
            blocked_question_tags=[],
        ),
        # --- META ---
        "emergency_route": RouteSpec(
            route_id="emergency_route",
            title="Срочная помощь",
            allowed_rule_sets=["emergency_triage_rules"],
            blocked_rule_sets=["*"],
            allowed_hypothesis_tags=["emergency"],
            blocked_hypothesis_tags=["*"],
            allowed_question_tags=["emergency_only"],
            blocked_question_tags=["food_trigger_wine_chocolate", "routine_labs"],
        ),
        "generic_safe_route": RouteSpec(
            route_id="generic_safe_route",
            title="Безопасный общий маршрут",
            allowed_rule_sets=["generic_safe_rules"],
            blocked_rule_sets=["specialized_invasive_rules"],
            allowed_hypothesis_tags=["general", "needs_more_data"],
            blocked_hypothesis_tags=["severe_rare_without_evidence"],
            allowed_question_tags=["clarification", "timeline", "severity"],
            blocked_question_tags=["food_trigger_wine_chocolate"],
        ),
        "physician_report_only_route": RouteSpec(
            route_id="physician_report_only_route",
            title="Только врачебный отчёт по документу",
            allowed_rule_sets=["physician_report_rules"],
            blocked_rule_sets=[],
            allowed_hypothesis_tags=["document_grounded"],
            blocked_hypothesis_tags=["speculative_cross_domain"],
            allowed_question_tags=["follow_up_clinician"],
            blocked_question_tags=[],
        ),
    }


ROUTES: dict[str, RouteSpec] = _routes()


def get_route_spec(route_id: str) -> RouteSpec | None:
    return ROUTES.get(route_id)
