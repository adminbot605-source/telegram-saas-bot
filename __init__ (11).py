from sqlalchemy import BigInteger, Integer, Boolean, ForeignKey, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from datetime import datetime
from .base import Base, TimestampMixin


class UserAccess(Base, TimestampMixin):
    __tablename__ = "user_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tariff_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tariffs.id", ondelete="SET NULL"), nullable=True
    )
    payment_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )
    granted_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_lifetime: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], lazy="selectin")
    group: Mapped["Group"] = relationship("Group", lazy="selectin")
    tariff: Mapped[Optional["Tariff"]] = relationship("Tariff", lazy="selectin")

    @property
    def is_expired(self) -> bool:
        if self.is_lifetime or self.expires_at is None:
            return False
        from datetime import timezone
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_valid(self) -> bool:
        return self.is_active and not self.is_expired

    def __repr__(self) -> str:
        return f"<UserAccess user={self.user_id} group={self.group_id} active={self.is_active}>"
