from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LabBridgeResult:
    suggested_lab_modules: list[str]
    suggested_tests: list[str]
    rationale: list[str]


class LabMappingBridge:
    """
    Bridges complaint patterns to lab / imaging modules.

    Not a diagnosis tool.
    Just says which modules are logically relevant if symptoms repeat.
    """

    def map(
        self,
        *,
        ranked_causes: list[str],
        recurrent: bool,
        care_level: str,
    ) -> LabBridgeResult:
        modules: list[str] = []
        tests: list[str] = []
        rationale: list[str] = []

        cause_set = set(ranked_causes)

        if "biliary_pattern" in cause_set or "fatty_food_overload" in cause_set:
            modules.append("hepatobiliary_module")
            tests.extend(["АЛТ", "АСТ", "билирубин", "ГГТ", "УЗИ ОБП"])
            rationale.append("жирная пища / желчный паттерн")

        if "pancreatic_warning_if_severe" in cause_set:
            modules.append("pancreatic_module")
            tests.extend(["амилаза", "липаза"])
            rationale.append("панкреатический настораживающий паттерн")

        if "dairy_lactose_pattern" in cause_set:
            modules.append("food_intolerance_module")
            rationale.append("молочный / лактозный паттерн")
            tests.extend(["пищевой дневник", "клиническая оценка переносимости молочного"])

        if "reflux_pattern" in cause_set or "functional_dyspepsia" in cause_set:
            modules.append("upper_gi_module")
            rationale.append("верхний ЖКТ / диспепсия / рефлюкс")
            tests.extend(["оценка H. pylori по показаниям"])

        if "histamine_conditional_pattern" in cause_set:
            modules.append("histamine_pattern_module")
            rationale.append("гистаминоподобный повторяющийся паттерн")
            tests.extend(["обсуждать только при типичной повторяемости"])

        if care_level in {"urgent", "emergency"}:
            rationale.append("приоритет - очная оценка, а не амбулаторный скрининг")

        if not recurrent:
            tests = [test for test in tests if test in {"пищевой дневник"}]

        return LabBridgeResult(
            suggested_lab_modules=list(dict.fromkeys(modules)),
            suggested_tests=list(dict.fromkeys(tests)),
            rationale=list(dict.fromkeys(rationale)),
        )

