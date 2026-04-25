"""Маршрутизация документов по типам."""
from app.services.document_routes.organic_acids_route import route_organic_acids, build_organic_acids_report

__all__ = ["route_organic_acids", "build_organic_acids_report"]
