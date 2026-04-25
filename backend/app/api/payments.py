"""Платежи: ссылка на оплату полного плана и подписки."""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.deps_auth import get_optional_access_context
from app.database import get_db
from app.models import User
from app.services.auth_models import AccessContext
from app.services.payments import create_payment_link, create_subscription_link
from app.services.subscription_service import create_subscription as create_subscription_db

router = APIRouter(prefix="/api", tags=["payments"])


def _get_or_create_db_user(db: Session, ctx: AccessContext) -> Optional[User]:
    """Получить или создать User в БД из AccessContext."""
    if not ctx.user_id or ctx.user_id == "default":
        return None
    try:
        user_id_int = int(ctx.user_id) if ctx.user_id.isdigit() else None
        if not user_id_int:
            return None
        user = db.query(User).filter(User.id == user_id_int).first()
        if not user:
            user = User(id=user_id_int)
            db.add(user)
            db.commit()
            db.refresh(user)
        return user
    except Exception:
        return None


@router.get("/buy")
def buy(
    ctx: AccessContext = Depends(get_optional_access_context),
    db: Session = Depends(get_db),
):
    """Разовый платёж за персональный план (premium)."""
    url = create_payment_link()
    if not url:
        raise HTTPException(status_code=503, detail="Платежи временно недоступны")
    return {"url": url}


@router.get("/subscribe")
def subscribe(
    plan: str = "monthly",  # monthly, yearly
    ctx: AccessContext = Depends(get_optional_access_context),
    db: Session = Depends(get_db),
):
    """Подписка (monthly/yearly). Требуется price_id в настройках."""
    from app.core.settings import get_settings
    settings = get_settings()
    price_id = getattr(settings, f"STRIPE_PRICE_ID_{plan.upper()}", None) or ""
    if not price_id:
        raise HTTPException(status_code=400, detail=f"План {plan} не настроен")
    user = _get_or_create_db_user(db, ctx)
    customer_id = None
    if user:
        # Получить stripe_customer_id из подписки если есть
        from app.services.subscription_service import get_user_subscription
        sub = get_user_subscription(db, user.id)
        if sub and sub.stripe_customer_id:
            customer_id = sub.stripe_customer_id
    url = create_subscription_link(price_id, customer_id=customer_id)
    if not url:
        raise HTTPException(status_code=503, detail="Платежи временно недоступны")
    return {"url": url}


@router.post("/webhook/stripe")
async def stripe_webhook(
    payload: dict,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """Webhook от Stripe для обработки событий (payment, subscription)."""
    # TODO: верификация подписи, обработка событий checkout.session.completed, customer.subscription.*
    # Обновление подписки в БД через subscription_service
    return {"received": True}
