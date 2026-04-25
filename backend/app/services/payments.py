"""Платежи (Stripe Checkout). Ключ и URL из настроек."""
from datetime import datetime, timedelta
from typing import Optional

from app.core.settings import get_settings

try:
    import stripe
    _STRIPE_AVAILABLE = True
except ImportError:
    _STRIPE_AVAILABLE = False
    stripe = None


def create_payment_link(
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> str:
    """Создаёт ссылку на Stripe Checkout для «Персональный план» (разовый платёж). Без ключа возвращает пустую строку."""
    if not _STRIPE_AVAILABLE or stripe is None:
        return ""
    s = get_settings()
    key = getattr(s, "STRIPE_SECRET_KEY", None) or ""
    if not key:
        return ""
    stripe.api_key = key
    base = getattr(s, "STRIPE_BASE_URL", "") or "https://your-site"
    success = success_url or getattr(s, "STRIPE_SUCCESS_URL", None) or f"{base}/success"
    cancel = cancel_url or getattr(s, "STRIPE_CANCEL_URL", None) or f"{base}/cancel"
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Персональный план"},
                "unit_amount": 999,  # $9.99
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success,
        cancel_url=cancel,
    )
    return session.url or ""


def create_subscription_link(
    price_id: str,
    customer_id: Optional[str] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> str:
    """Создаёт ссылку на Stripe Checkout для подписки. Без ключа возвращает пустую строку."""
    if not _STRIPE_AVAILABLE or stripe is None:
        return ""
    s = get_settings()
    key = getattr(s, "STRIPE_SECRET_KEY", None) or ""
    if not key:
        return ""
    stripe.api_key = key
    base = getattr(s, "STRIPE_BASE_URL", "") or "https://your-site"
    success = success_url or getattr(s, "STRIPE_SUCCESS_URL", None) or f"{base}/success"
    cancel = cancel_url or getattr(s, "STRIPE_CANCEL_URL", None) or f"{base}/cancel"
    session_params = {
        "payment_method_types": ["card"],
        "line_items": [{
            "price": price_id,
            "quantity": 1,
        }],
        "mode": "subscription",
        "success_url": success,
        "cancel_url": cancel,
    }
    if customer_id:
        session_params["customer"] = customer_id
    session = stripe.checkout.Session.create(**session_params)
    return session.url or ""
