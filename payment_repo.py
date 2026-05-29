import enum
from sqlalchemy import BigInteger, String, Integer, Boolean, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import DateTime
from typing import Optional
from datetime import datetime
from .base import Base, TimestampMixin


class SubscriptionPlan(str, enum.Enum):
    FREE = "free"
    BASIC = "basic"
    PRO = "pro"


PLAN_CONFIG = {
    SubscriptionPlan.FREE: {
        "name": "Бесплатный",
        "emoji": "🆓",
        "groups_limit": 1,
        "scheduled_posts": 5,
        "welcome_message": True,
        "anti_spam": False,
        "analytics": False,
        "price_month": 0,
        "price_year": 0,
    },
    SubscriptionPlan.BASIC: {
        "name": "Базовый",
        "emoji": "⭐",
        "groups_limit": 5,
        "scheduled_posts": 50,
        "welcome_message": True,
        "anti_spam": True,
        "analytics": True,
        "price_month": 299,
        "price_year": 2990,
    },
    SubscriptionPlan.PRO: {
        "name": "Профессиональный",
        "emoji": "💎",
        "groups_limit": 20,
        "scheduled_posts": 999,
        "welcome_message": True,
        "anti_spam": True,
        "analytics": True,
        "price_month": 799,
        "price_year": 7990,
    },
}


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SubscriptionPlan.FREE.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount_paid: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="subscriptions")

    @property
    def plan_config(self) -> dict:
        return PLAN_CONFIG.get(SubscriptionPlan(self.plan), PLAN_CONFIG[SubscriptionPlan.FREE])

    @property
    def plan_name(self) -> str:
        return self.plan_config["name"]

    @property
    def plan_emoji(self) -> str:
        return self.plan_config["emoji"]

    @property
    def groups_limit(self) -> int:
        return self.plan_config["groups_limit"]

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        from datetime import timezone
        return datetime.now(timezone.utc) > self.expires_at

    def __repr__(self) -> str:
        return f"<Subscription user_id={self.user_id} plan={self.plan}>"
