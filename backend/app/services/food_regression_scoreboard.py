from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.food_consultation_engine import FoodConsultationEngine, FoodRoutingContext, TriggerMemoryState

# Подключай те наборы, которые у тебя реально есть.
# Можно оставить только hard-pack, если пока есть только он.
try:
    from app.services.food_regression_cases_200 import REGRESSION_CASES_FOOD_200
except Exception:
    REGRESSION_CASES_FOOD_200 = []

try:
    from app.services.food_regression_cases_hard_100 import REGRESSION_CASES_FOOD_HARD_100
except Exception:
    REGRESSION_CASES_FOOD_HARD_100 = []

# Fallback: если есть только legacy большой пак.
if not REGRESSION_CASES_FOOD_200:
    try:
        from app.services.regression_cases_food_large import REGRESSION_CASES_FOOD_LARGE
    except Exception:
        REGRESSION_CASES_FOOD_LARGE = []
else:
    REGRESSION_CASES_FOOD_LARGE = []

# Если потом сделаешь отдельные easy/medium наборы — просто импортируй их сюда.
try:
    from app.services.regression_cases_food_easy import REGRESSION_CASES_FOOD_EASY
except Exception:
    REGRESSION_CASES_FOOD_EASY = []

try:
    from app.services.regression_cases_food_medium import REGRESSION_CASES_FOOD_MEDIUM
except Exception:
    REGRESSION_CASES_FOOD_MEDIUM = []


@dataclass
class CaseEvaluation:
    case_id: str
    tier: str
    ok: bool
    zone_ok: bool
    cause_ok: bool
    care_ok: bool
    expected_zone: str
    actual_zone: str
    expected_causes_any: list[str]
    actual_ranked_causes: list[str]
    expected_care_any: list[str]
    actual_care: str
    text: str


@dataclass
class TierStats:
    name: str
    total: int = 0
    passed: int = 0
    zone_ok: int = 0
    cause_ok: int = 0
    care_ok: int = 0
    failed_cases: list[CaseEvaluation] = field(default_factory=list)

    def add(self, ev: CaseEvaluation) -> None:
        self.total += 1
        if ev.ok:
            self.passed += 1
        if ev.zone_ok:
            self.zone_ok += 1
        if ev.cause_ok:
            self.cause_ok += 1
        if ev.care_ok:
            self.care_ok += 1
        if not ev.ok:
            self.failed_cases.append(ev)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.total - self.passed,
            "pass_rate": self._pct(self.passed, self.total),
            "zone_accuracy": self._pct(self.zone_ok, self.total),
            "cause_accuracy": self._pct(self.cause_ok, self.total),
            "care_accuracy": self._pct(self.care_ok, self.total),
        }

    @staticmethod
    def _pct(x: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round((x / total) * 100, 1)


@dataclass
class ScoreboardResult:
    overall: dict[str, Any]
    tiers: dict[str, dict[str, Any]]
    common_failures: list[dict[str, Any]]
    failed_cases: list[dict[str, Any]]


class FoodRegressionScoreboard:
    """
    Runs regression packs and produces:
      - overall metrics
      - per-tier metrics
      - zone/cause/care accuracy
      - most common failure patterns
      - failed case details
    """

    def __init__(self, engine: FoodConsultationEngine) -> None:
        self.engine = engine

    def run(self) -> ScoreboardResult:
        packs = self._collect_packs()

        tier_stats: dict[str, TierStats] = {tier: TierStats(name=tier) for tier in packs.keys()}

        all_evals: list[CaseEvaluation] = []
        memory = TriggerMemoryState()

        for tier_name, cases in packs.items():
            for case in cases:
                ev, memory = self._evaluate_case(case, tier_name, memory)
                tier_stats[tier_name].add(ev)
                all_evals.append(ev)

        overall = self._build_overall(all_evals)
        tiers = {name: stats.summary() for name, stats in tier_stats.items()}
        common_failures = self._build_common_failures(all_evals)
        failed_cases = self._serialize_failed_cases(all_evals)

        return ScoreboardResult(
            overall=overall,
            tiers=tiers,
            common_failures=common_failures,
            failed_cases=failed_cases,
        )

    def _collect_packs(self) -> dict[str, list[dict[str, Any]]]:
        packs: dict[str, list[dict[str, Any]]] = {}

        if REGRESSION_CASES_FOOD_EASY:
            packs["easy"] = REGRESSION_CASES_FOOD_EASY
        if REGRESSION_CASES_FOOD_MEDIUM:
            packs["medium"] = REGRESSION_CASES_FOOD_MEDIUM
        if REGRESSION_CASES_FOOD_HARD_100:
            packs["hard"] = REGRESSION_CASES_FOOD_HARD_100

        # Если нет easy/medium, но есть 200-pack — считаем его medium.
        if "medium" not in packs and REGRESSION_CASES_FOOD_200:
            packs["medium"] = REGRESSION_CASES_FOOD_200

        # Legacy fallback: если нет 200-pack, но есть старый большой пак.
        if "medium" not in packs and REGRESSION_CASES_FOOD_LARGE:
            packs["medium"] = REGRESSION_CASES_FOOD_LARGE

        # Если вообще ничего нет — пустой набор.
        if not packs:
            packs["medium"] = []

        return packs

    def _evaluate_case(
        self,
        case: dict[str, Any],
        tier_name: str,
        memory: TriggerMemoryState,
    ) -> tuple[CaseEvaluation, TriggerMemoryState]:
        result = self.engine.consult(
            case["text"],
            context=FoodRoutingContext(
                recurrent=case["recurrent"],
                debug=False,
                ask_followups=True,
                doctor_safe=True,
            ),
            memory_state=memory,
        )

        memory = result["memory_state"]

        doctor_view = result.get("doctor_view", {}) or {}
        patient_view = result.get("patient_view", {}) or {}

        actual_zone = str(doctor_view.get("zone", ""))
        actual_ranked_causes = list(doctor_view.get("ranked_causes", []))
        actual_care = str(patient_view.get("care_level", ""))

        expected_zone = str(case["expected_zone"])
        expected_causes_any = list(case["expected_top_causes_any"])
        expected_care_any = list(case["expected_care_level_any"])

        zone_ok = actual_zone == expected_zone
        cause_ok = any(cause in actual_ranked_causes for cause in expected_causes_any)
        care_ok = actual_care in expected_care_any
        ok = zone_ok and cause_ok and care_ok

        ev = CaseEvaluation(
            case_id=str(case["id"]),
            tier=tier_name,
            ok=ok,
            zone_ok=zone_ok,
            cause_ok=cause_ok,
            care_ok=care_ok,
            expected_zone=expected_zone,
            actual_zone=actual_zone,
            expected_causes_any=expected_causes_any,
            actual_ranked_causes=actual_ranked_causes,
            expected_care_any=expected_care_any,
            actual_care=actual_care,
            text=str(case["text"]),
        )
        return ev, memory

    def _build_overall(self, evals: list[CaseEvaluation]) -> dict[str, Any]:
        total = len(evals)
        passed = sum(1 for x in evals if x.ok)
        zone_ok = sum(1 for x in evals if x.zone_ok)
        cause_ok = sum(1 for x in evals if x.cause_ok)
        care_ok = sum(1 for x in evals if x.care_ok)

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": self._pct(passed, total),
            "zone_accuracy": self._pct(zone_ok, total),
            "cause_accuracy": self._pct(cause_ok, total),
            "care_accuracy": self._pct(care_ok, total),
        }

    def _build_common_failures(self, evals: list[CaseEvaluation]) -> list[dict[str, Any]]:
        failure_buckets: dict[str, int] = {}

        for ev in evals:
            if ev.ok:
                continue

            labels: list[str] = []
            if not ev.zone_ok:
                labels.append("zone_mismatch")
            if not ev.cause_ok:
                labels.append("cause_mismatch")
            if not ev.care_ok:
                labels.append("care_mismatch")

            key = "+".join(labels) if labels else "unknown_failure"
            failure_buckets[key] = failure_buckets.get(key, 0) + 1

        ranked = sorted(failure_buckets.items(), key=lambda x: x[1], reverse=True)

        return [{"failure_type": key, "count": count} for key, count in ranked]

    def _serialize_failed_cases(self, evals: list[CaseEvaluation]) -> list[dict[str, Any]]:
        failed = [ev for ev in evals if not ev.ok]
        return [
            {
                "id": ev.case_id,
                "tier": ev.tier,
                "text": ev.text,
                "zone_ok": ev.zone_ok,
                "cause_ok": ev.cause_ok,
                "care_ok": ev.care_ok,
                "expected_zone": ev.expected_zone,
                "actual_zone": ev.actual_zone,
                "expected_causes_any": ev.expected_causes_any,
                "actual_ranked_causes": ev.actual_ranked_causes,
                "expected_care_any": ev.expected_care_any,
                "actual_care": ev.actual_care,
            }
            for ev in failed
        ]

    @staticmethod
    def _pct(x: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return round((x / total) * 100, 1)


def print_scoreboard(result: ScoreboardResult) -> None:
    print("\n================ OVERALL ================")
    for k, v in result.overall.items():
        print(f"{k}: {v}")

    print("\n================ TIERS ==================")
    for tier_name, stats in result.tiers.items():
        print(f"\n--- {tier_name.upper()} ---")
        for k, v in stats.items():
            print(f"{k}: {v}")

    print("\n=========== COMMON FAILURES =============")
    if not result.common_failures:
        print("No failures")
    else:
        for item in result.common_failures:
            print(item)

    print("\n============= FAILED CASES ==============")
    if not result.failed_cases:
        print("No failed cases")
    else:
        for item in result.failed_cases:
            print(item)


if __name__ == "__main__":
    engine = FoodConsultationEngine()
    scoreboard = FoodRegressionScoreboard(engine)
    result = scoreboard.run()
    print_scoreboard(result)

