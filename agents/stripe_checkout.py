"""Stripe embedded Checkout for the Concierge's paid plan, TEST MODE ONLY (mirrors the Fetch.ai stripe-horoscope agent).

Env (agents/.env, gitignored): STRIPE_SECRET_KEY (`sk_test_…`, a live key is refused), STRIPE_PUBLISHABLE_KEY
(`pk_test_…`), STRIPE_AMOUNT_CENTS (100), STRIPE_CURRENCY (usd), STRIPE_PRODUCT_NAME, STRIPE_SUCCESS_URL,
STRIPE_CHECKOUT_EXPIRES_SECONDS (1800, clamped to [1800, 86400] as Stripe requires).
No card data passes through here: the owner pays inside Stripe's embedded page; we keep only the Checkout Session id.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class StripeConfig:
    secret_key: str
    publishable_key: str
    amount_cents: int
    currency: str
    product_name: str
    success_url: str
    expires_s: int

    @classmethod
    def from_env(cls) -> StripeConfig | None:
        """None when Stripe is not set up, or the keys are not test keys: the paid plan is then simply unavailable."""
        secret = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        publishable = os.environ.get("STRIPE_PUBLISHABLE_KEY", "").strip()
        if not secret.startswith("sk_test_") or not publishable.startswith("pk_test_"):
            return None
        return cls(
            secret_key=secret,
            publishable_key=publishable,
            amount_cents=int(os.environ.get("STRIPE_AMOUNT_CENTS", "100")),
            currency=(os.environ.get("STRIPE_CURRENCY") or "usd").strip().lower(),
            product_name=os.environ.get("STRIPE_PRODUCT_NAME") or "WattWise: Claude handles your escalations",
            success_url=os.environ.get("STRIPE_SUCCESS_URL") or "https://agentverse.ai/payment-success",
            expires_s=max(1800, min(24 * 60 * 60, int(os.environ.get("STRIPE_CHECKOUT_EXPIRES_SECONDS", "1800")))),
        )

    @property
    def amount(self) -> str:
        """The price as `Funds.amount` writes it ("1.00")."""
        return f"{self.amount_cents / 100:.2f}"


class StripeCheckout:
    """The two Stripe calls the payment flow needs. Blocking (the SDK is sync): call through asyncio.to_thread."""

    def __init__(self, config: StripeConfig):
        self.config = config

    def _sdk(self):
        import stripe

        stripe.api_key = self.config.secret_key
        return stripe

    def create_session(self, *, user_address: str, chat_session_id: str, description: str) -> dict[str, str]:
        """An embedded Checkout Session; the dict rides in `RequestPayment.metadata["stripe"]` (never the secret key)."""
        cfg = self.config
        session = self._sdk().checkout.Session.create(
            ui_mode="embedded",
            redirect_on_completion="if_required",
            payment_method_types=["card"],
            mode="payment",
            return_url=(f"{cfg.success_url}?session_id={{CHECKOUT_SESSION_ID}}"
                        f"&chat_session_id={chat_session_id}&user={user_address}"),
            expires_at=int(time.time()) + cfg.expires_s,
            line_items=[{
                "price_data": {
                    "currency": cfg.currency,
                    "product_data": {"name": cfg.product_name, "description": description},
                    "unit_amount": cfg.amount_cents,
                },
                "quantity": 1,
            }],
            metadata={"user_address": user_address, "session_id": chat_session_id, "service": "wattwise_authority"},
        )
        # Every value a string: RequestPayment.metadata is dict[str, str | dict[str, str]].
        return {
            "client_secret": session.client_secret,
            "id": session.id,
            "checkout_session_id": session.id,
            "publishable_key": cfg.publishable_key,
            "currency": cfg.currency,
            "amount_cents": str(cfg.amount_cents),
            "ui_mode": "embedded",
        }

    def is_paid(self, checkout_session_id: str) -> bool:
        session = self._sdk().checkout.Session.retrieve(checkout_session_id)
        return getattr(session, "payment_status", None) == "paid"
