from __future__ import annotations

from app.services.food_router_v5 import FoodRoutingContext, FoodSymptomRouterV5
from app.services.food_rules_loader import FoodRulesLoader
from app.services.trigger_memory import TriggerMemoryState


TEST_CASES = [
    {
        "name": "episode_1_fatty",
        "text": "После жареной картошки и семечек подташнивает и болит голова",
        "recurrent": False,
    },
    {
        "name": "episode_2_fatty_repeat",
        "text": "Опять после жирной еды мутит, слабость и тяжесть",
        "recurrent": True,
    },
    {
        "name": "episode_3_dairy",
        "text": "После молока и мороженого раздуло живот и жидкий стул",
        "recurrent": True,
    },
    {
        "name": "episode_4_biliary",
        "text": "После жирного тянет справа под ребром и горечь во рту",
        "recurrent": True,
    },
]


def main() -> None:
    configs = FoodRulesLoader("app/knowledge").load_all()
    router = FoodSymptomRouterV5(configs)
    memory = TriggerMemoryState()

    for case in TEST_CASES:
        print(f"\n===== CASE: {case['name']} =====")
        result = router.route(
            case["text"],
            context=FoodRoutingContext(
                recurrent=case["recurrent"],
                debug=True,
                doctor_safe=True,
                ask_followups=True,
                memory_state=memory,
            ),
        )

        print(result["text"])
        print("\nDOCTOR SAFE:")
        print(result["doctor_safe"])

        memory = result["memory_state"]


if __name__ == "__main__":
    main()

