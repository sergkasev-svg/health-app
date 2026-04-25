"""Сервис подписок: проверка уровня доступа, создание/обновление подписок."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Subscription, User


def get_user_subscription(db: Session, user_id: int) -> Optional[Subscription]:
    """Получить активную подписку пользователя."""
    sub = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .first()
    )
    if sub and sub.status == "cancelled":
        return None
    return sub


def get_user_tier(db: Session, user_id: int) -> str:
    """Получить уровень доступа: free, premium, subscription."""
    sub = get_user_subscription(db, user_id)
    if not sub:
        return "free"
    if sub.status == "premium":
        return "premium"
    if sub.status == "subscription":
        if sub.expires_at and sub.expires_at < datetime.utcnow():
            return "free"
        return "subscription"
    return "free"


def can_access_premium(db: Session, user_id: int) -> bool:
    """Проверка доступа к премиум-функциям (premium или subscription)."""
    tier = get_user_tier(db, user_id)
    return tier in ("premium", "subscription")


def create_subscription(
    db: Session,
    user_id: int,
    status: str,
    plan: str,
    stripe_subscription_id: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> Subscription:
    """Создать или обновить подписку."""
    existing = get_user_subscription(db, user_id)
    if existing:
        existing.status = status
        existing.plan = plan
        if stripe_subscription_id:
            existing.stripe_subscription_id = stripe_subscription_id
        if stripe_customer_id:
            existing.stripe_customer_id = stripe_customer_id
        if expires_at:
            existing.expires_at = expires_at
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return existing
    sub = Subscription(
        user_id=user_id,
        status=status,
        plan=plan,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
        expires_at=expires_at,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub
