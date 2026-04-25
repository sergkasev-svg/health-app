from __future__ import annotations

import os
from typing import Any

from app.services.lab_network.base import LabNetworkAdapter


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes")


class InvitroAdapter(LabNetworkAdapter):
    id = "invitro"
    title = "Инвитро"

    def status(self) -> dict[str, Any]:
        ready = _flag("LAB_INVITRO_READY")
        return {
            "integration": "stub",
            "ready": ready,
            "docs": "Требуются договорённость с сетью и REST/OAuth-ключи (см. docs/product_mobile_store).",
        }


class GemotestAdapter(LabNetworkAdapter):
    id = "gemotest"
    title = "Гемотест"

    def status(self) -> dict[str, Any]:
        ready = _flag("LAB_GEMOTEST_READY")
        return {
            "integration": "stub",
            "ready": ready,
            "docs": "Адаптер-заглушка до выдачи API.",
        }


class HelixAdapter(LabNetworkAdapter):
    id = "helix"
    title = "Helix"

    def status(self) -> dict[str, Any]:
        ready = _flag("LAB_HELIX_READY")
        return {
            "integration": "stub",
            "ready": ready,
            "docs": "Адаптер-заглушка до выдачи API.",
        }
