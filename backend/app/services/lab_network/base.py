from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LabNetworkAdapter(ABC):
    id: str
    title: str

    @abstractmethod
    def status(self) -> dict[str, Any]:
        """Состояние интеграции для UI."""

    def authorize_url(self, redirect_uri: str) -> dict[str, Any]:
        return {"ok": False, "error": "not_configured", "message": "OAuth не настроен."}

    def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        return {"ok": False, "error": "not_configured"}

    def list_orders(self, access_token: str) -> dict[str, Any]:
        return {"ok": False, "error": "not_configured", "items": []}

    def fetch_result_pdf(self, access_token: str, order_id: str) -> dict[str, Any]:
        return {"ok": False, "error": "not_configured"}
