from __future__ import annotations

from typing import Any

from app.services.lab_network.base import LabNetworkAdapter
from app.services.lab_network.stubs import InvitroAdapter, GemotestAdapter, HelixAdapter

LABS: dict[str, type[LabNetworkAdapter]] = {
    "invitro": InvitroAdapter,
    "gemotest": GemotestAdapter,
    "helix": HelixAdapter,
}


def get_adapter(lab_id: str) -> LabNetworkAdapter | None:
    cls = LABS.get((lab_id or "").strip().lower())
    if not cls:
        return None
    return cls()


def list_lab_meta() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for lid, cls in LABS.items():
        inst = cls()
        st = inst.status()
        out.append({"id": lid, "title": getattr(inst, "title", lid), **st})
    return out
