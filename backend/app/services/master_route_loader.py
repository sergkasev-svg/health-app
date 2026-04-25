from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.services.food_reaction_master_loader import (
    load_food_reaction_master,
    master_red_flags,
    prioritize_food_causes,
    recurrent_food_tests,
    single_episode_tests_not_needed_message,
)
from app.services.food_symptom_super_master_loader import (
    classify_super,
    detect_red_flags as detect_food_super_red_flags,
    load_food_symptom_super_master,
    rank_causes as rank_food_super_causes,
    recurrent_fatty_ruq_tests,
    single_mild_message as food_super_single_mild_message,
)
from app.services.postmeal_bloating_master_loader import (
    detect_red_flags as detect_postmeal_bloating_red_flags,
    load_postmeal_bloating_master,
    prioritize_causes as prioritize_postmeal_bloating_causes,
    single_mild_message as postmeal_bloating_single_mild_message,
)
from app.services.postmeal_systemic_master_loader import (
    detect_red_flags as detect_postmeal_systemic_red_flags,
    load_postmeal_systemic_master,
    prioritize_causes as prioritize_postmeal_systemic_causes,
    recurrent_tests as postmeal_systemic_recurrent_tests,
)
from app.services.upper_abdominal_master_loader import (
    detect_upper_abdominal_red_flags,
    load_upper_abdominal_master,
    prioritize_upper_abdominal_causes,
    recurrent_fatty_or_ruq_tests,
    single_episode_message as upper_abdominal_single_episode_message,
    upper_abdominal_red_flags,
)


@dataclass(frozen=True)
class MasterRouteHook:
    route_id: str
    loader_key: str
    load_config: Callable[[], dict[str, Any]]
    rank_causes: Callable[[str, int, bool], list[dict[str, Any]]]
    detect_red_flags: Callable[[str], list[str]]
    single_episode_message: Callable[[], str]
    recurrent_tests: Callable[[], list[str]]
    enrich: Callable[[str, bool], dict[str, Any]] | None = None


def _food_red_flags(_: str) -> list[str]:
    return master_red_flags()


def _upper_abdominal_red_flags(_: str) -> list[str]:
    return upper_abdominal_red_flags()


def _no_recurrent_tests() -> list[str]:
    return []


def _identity_enrich(_: str, __: bool) -> dict[str, Any]:
    return {}


def _postmeal_systemic_single_episode_message() -> str:
    return "При единичном лёгком эпизоде без красных флагов обычно достаточно наблюдения и питьевого режима."


def _rank_food_route(message: str, limit: int, _: bool) -> list[dict[str, Any]]:
    return prioritize_food_causes(message, limit=max(1, int(limit or 1)))


def _rank_upper_abdominal_route(message: str, limit: int, _: bool) -> list[dict[str, Any]]:
    return prioritize_upper_abdominal_causes(message, limit=max(1, int(limit or 1)))


def _rank_postmeal_bloating_route(message: str, limit: int, _: bool) -> list[dict[str, Any]]:
    return prioritize_postmeal_bloating_causes(message, limit=max(1, int(limit or 1)))


def _rank_postmeal_systemic_route(message: str, limit: int, _: bool) -> list[dict[str, Any]]:
    return prioritize_postmeal_systemic_causes(message, limit=max(1, int(limit or 1)))


def _rank_food_super_route(message: str, limit: int, recurrent: bool) -> list[dict[str, Any]]:
    parsed = classify_super(message, recurrent=recurrent)
    cluster = str(parsed.get("cluster") or "")
    trigger_groups = list(parsed.get("trigger_groups") or [])
    return rank_food_super_causes(
        message,
        cluster=cluster,
        trigger_groups=trigger_groups,
        recurrent=recurrent,
        limit=max(1, int(limit or 1)),
    )


MASTER_ROUTE_HOOKS: dict[str, MasterRouteHook] = {
    "food_reaction_master_route": MasterRouteHook(
        route_id="food_reaction_master_route",
        loader_key="food_reaction_master",
        load_config=load_food_reaction_master,
        rank_causes=_rank_food_route,
        detect_red_flags=_food_red_flags,
        single_episode_message=single_episode_tests_not_needed_message,
        recurrent_tests=recurrent_food_tests,
        enrich=_identity_enrich,
    ),
    "upper_abdominal_master_route": MasterRouteHook(
        route_id="upper_abdominal_master_route",
        loader_key="upper_abdominal_master",
        load_config=load_upper_abdominal_master,
        rank_causes=_rank_upper_abdominal_route,
        detect_red_flags=detect_upper_abdominal_red_flags,
        single_episode_message=upper_abdominal_single_episode_message,
        recurrent_tests=recurrent_fatty_or_ruq_tests,
        enrich=_identity_enrich,
    ),
    "postmeal_bloating_master_route": MasterRouteHook(
        route_id="postmeal_bloating_master_route",
        loader_key="postmeal_bloating_master",
        load_config=load_postmeal_bloating_master,
        rank_causes=_rank_postmeal_bloating_route,
        detect_red_flags=detect_postmeal_bloating_red_flags,
        single_episode_message=postmeal_bloating_single_mild_message,
        recurrent_tests=_no_recurrent_tests,
        enrich=_identity_enrich,
    ),
    "postmeal_systemic_master_route": MasterRouteHook(
        route_id="postmeal_systemic_master_route",
        loader_key="postmeal_systemic_master",
        load_config=load_postmeal_systemic_master,
        rank_causes=_rank_postmeal_systemic_route,
        detect_red_flags=detect_postmeal_systemic_red_flags,
        single_episode_message=_postmeal_systemic_single_episode_message,
        recurrent_tests=postmeal_systemic_recurrent_tests,
        enrich=_identity_enrich,
    ),
    "food_symptom_super_master_route": MasterRouteHook(
        route_id="food_symptom_super_master_route",
        loader_key="food_symptom_super_master",
        load_config=load_food_symptom_super_master,
        rank_causes=_rank_food_super_route,
        detect_red_flags=detect_food_super_red_flags,
        single_episode_message=food_super_single_mild_message,
        recurrent_tests=recurrent_fatty_ruq_tests,
        enrich=lambda message, recurrent: classify_super(message, recurrent=recurrent),
    ),
}


def get_master_route_hook(route_id: str) -> MasterRouteHook | None:
    return MASTER_ROUTE_HOOKS.get(route_id)


def list_master_routes() -> list[str]:
    return list(MASTER_ROUTE_HOOKS.keys())


def run_master_route(
    *,
    route_id: str,
    message: str,
    recurrent: bool = False,
    cause_limit: int = 4,
) -> dict[str, Any]:
    hook = get_master_route_hook(route_id)
    if not hook:
        return {}

    ranked = hook.rank_causes(message, max(1, int(cause_limit or 1)), recurrent)
    red_flags = hook.detect_red_flags(message)
    tests = hook.recurrent_tests() if recurrent else []
    single_episode = hook.single_episode_message()
    extra = (hook.enrich or _identity_enrich)(message, recurrent)

    return {
        "route_id": route_id,
        "loader_key": hook.loader_key,
        "ranked_causes": ranked,
        "red_flags_detected": red_flags,
        "single_episode_message": single_episode,
        "recurrent_tests": tests,
        "recurrent": bool(recurrent),
        **extra,
    }
