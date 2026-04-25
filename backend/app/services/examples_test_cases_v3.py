from __future__ import annotations

from app.services.food_router_v3 import FoodRoutingContext, FoodSymptomRouterV3
from app.services.food_rules_loader import FoodRulesLoader
from app.services.reasoning_debug import print_reasoning_debug


TEST_CASES = [
    {
        "name": "fatty_headache_nausea",
        "text": "После жареной картошки и семечек немного подташнивает и болит голова",
        "recurrent": False,
    },
    {
        "name": "dairy_bloating",
        "text": "После молока и мороженого раздуло живот, урчит и жидкий стул",
        "recurrent": True,
    },
    {
        "name": "reflux_case",
        "text": "После позднего ужина жжение, кислая отрыжка и хуже когда ложусь",
        "recurrent": True,
    },
    {
        "name": "biliary_case",
        "text": "После жирной еды мутит и тянет справа под ребром, горечь во рту",
        "recurrent": True,
    },
    {
        "name": "histamine_like_case",
        "text": "После вина и сыра болит голова, краснеет лицо и сердце колотится",
        "recurrent": True,
    },
    {
        "name": "acute_infectious_case",
        "text": "Рвота, понос, температура после подозрительной еды",
        "recurrent": False,
    },
    {
        "name": "urgent_bleeding_case",
        "text": "Сильная боль в животе, черный стул и слабость",
        "recurrent": False,
    },
]


def main() -> None:
    # Run from backend root: python -m app.services.examples_test_cases_v3
    configs = FoodRulesLoader("./app/knowledge").load_all()
    router = FoodSymptomRouterV3(configs)

    for case in TEST_CASES:
        print(f"\n===== CASE: {case['name']} =====")
        result = router.route(
            case["text"],
            context=FoodRoutingContext(
                recurrent=case["recurrent"],
                debug=True,
                doctor_safe=True,
            ),
        )
        print(result["text"])

        if "debug" in result:
            print_reasoning_debug(result["debug"])

        if "doctor_safe" in result:
            print("DOCTOR SAFE:")
            print(result["doctor_safe"])


if __name__ == "__main__":
    main()

