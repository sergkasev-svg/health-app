"""Адаптеры лабораторных сетей (пока заглушки до выдачи API-партнёрами ключей)."""

from app.services.lab_network.registry import (
    LABS,
    get_adapter,
    list_lab_meta,
)

__all__ = ["LABS", "get_adapter", "list_lab_meta"]
