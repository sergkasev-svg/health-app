"""
Модели GTM / позиционирования: ValueProp, AudienceSegment, PricingTierCard, OfferMessage,
LaunchChecklistItem, GTMRoadmapItem.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ValueProp(BaseModel):
    id: str = ""
    audience: str = ""
    title: str = ""
    description: str = ""
    proof_points: List[str] = Field(default_factory=list)
    priority: int = 0


class AudienceSegment(BaseModel):
    segment_id: str = ""
    name: str = ""
    description: str = ""
    pains: List[str] = Field(default_factory=list)
    desired_outcomes: List[str] = Field(default_factory=list)
    key_features: List[str] = Field(default_factory=list)


class PricingTierCard(BaseModel):
    tier_id: str = ""
    title: str = ""
    subtitle: Optional[str] = None
    monthly_price: Optional[float] = None
    yearly_price: Optional[float] = None
    currency: Optional[str] = None
    bullet_points: List[str] = Field(default_factory=list)
    recommended: bool = False
    cta: Optional[str] = None
    target_audience: List[str] = Field(default_factory=list)


class OfferMessage(BaseModel):
    offer_id: str = ""
    title: str = ""
    body: str = ""
    cta: str = ""
    placement: str = ""
    audience: List[str] = Field(default_factory=list)


class LaunchChecklistItem(BaseModel):
    item_id: str = ""
    area: str = ""
    title: str = ""
    description: str = ""
    status: str = "pending"  # pending | done | blocked
    priority: str = "high"  # high | medium | low


class GTMRoadmapItem(BaseModel):
    phase: str = ""   # 30d | 60d | 90d
    stream: str = ""  # product | growth | content | b2b | ops | analytics
    title: str = ""
    description: str = ""
    owner_hint: Optional[str] = None
    priority: str = "high"
