from __future__ import annotations


REGRESSION_CASES_FOOD = [
    {
        "id": "food_001",
        "text": "После жареной картошки и семечек подташнивает и болит голова",
        "recurrent": False,
        "expected_zone": "systemic_zone",
        "expected_top_causes_any": [
            "fatty_food_systemic_overload",
            "postprandial_vascular_pattern",
            "fatty_food_overload",
        ],
        "expected_care_level_any": ["home", "routine_doctor"],
    },
    {
        "id": "food_002",
        "text": "После молока и мороженого раздуло живот, урчит и жидкий стул",
        "recurrent": True,
        "expected_zone": "bowel_zone",
        "expected_top_causes_any": [
            "dairy_lactose_pattern",
        ],
        "expected_care_level_any": ["routine_doctor", "home"],
    },
    {
        "id": "food_003",
        "text": "После позднего ужина жжение, кислая отрыжка и хуже когда ложусь",
        "recurrent": True,
        "expected_zone": "upper_gi_zone",
        "expected_top_causes_any": [
            "reflux_pattern",
            "functional_dyspepsia",
        ],
        "expected_care_level_any": ["routine_doctor", "home"],
    },
    {
        "id": "food_004",
        "text": "После жирного тянет справа под ребром и горечь во рту",
        "recurrent": True,
        "expected_zone": "right_upper_abdominal_zone",
        "expected_top_causes_any": [
            "biliary_pattern",
        ],
        "expected_care_level_any": ["routine_doctor", "urgent"],
    },
    {
        "id": "food_005",
        "text": "После вина и сыра болит голова, краснеет лицо и сердце колотится",
        "recurrent": True,
        "expected_zone": "systemic_zone",
        "expected_top_causes_any": [
            "histamine_conditional_pattern",
            "alcohol_related_pattern",
        ],
        "expected_care_level_any": ["routine_doctor", "home"],
    },
    {
        "id": "food_006",
        "text": "Рвота, понос, температура после подозрительной еды",
        "recurrent": False,
        "expected_zone": "urgent_route",
        "expected_top_causes_any": [
            "urgent_general_route",
        ],
        "expected_care_level_any": ["urgent"],
    },
    {
        "id": "food_007",
        "text": "Сильная боль в животе, черный стул и слабость",
        "recurrent": False,
        "expected_zone": "urgent_route",
        "expected_top_causes_any": [
            "urgent_general_route",
        ],
        "expected_care_level_any": ["emergency", "urgent"],
    },
]

