from sqlalchemy import BigInteger, Integer, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from .base import Base, TimestampMixin


class Referral(Base, TimestampMixin):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referred_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    bonus_days: Mapped[int] = mapped_column(Integer, default=0)
    is_rewarded: Mapped[bool] = mapped_column(Boolean, default=False)
    payment_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    referrer: Mapped["User"] = relationship("User", foreign_keys=[referrer_id])
    referred: Mapped["User"] = relationship("User", foreign_keys=[referred_id])

    def __repr__(self) -> str:
        return f"<Referral referrer={self.referrer_id} referred={self.referred_id}>"


class ReferralCode(Base, TimestampMixin):
    __tablename__ = "referral_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    total_referrals: Mapped[int] = mapped_column(Integer, default=0)
    total_bonus_days: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ReferralCode user={self.user_id} code={self.code}>"
