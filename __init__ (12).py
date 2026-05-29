import enum
from sqlalchemy import BigInteger, Integer, Boolean, ForeignKey, String, Text, Numeric, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from datetime import datetime
from .base import Base, TimestampMixin


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PaymentReceiptType(str, enum.Enum):
    PHOTO = "photo"
    DOCUMENT = "document"
    TEXT = "text"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

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
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.PENDING.value, index=True
    )
    receipt_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    receipt_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    user_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    admin_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    referral_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    access_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("user_access.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship("User", lazy="selectin")
    group: Mapped["Group"] = relationship("Group", lazy="selectin")
    tariff: Mapped[Optional["Tariff"]] = relationship("Tariff", back_populates="payments")

    @property
    def status_label(self) -> str:
        labels = {
            PaymentStatus.PENDING.value: "⏳ На проверке",
            PaymentStatus.APPROVED.value: "✅ Одобрен",
            PaymentStatus.REJECTED.value: "❌ Отклонён",
            PaymentStatus.EXPIRED.value: "⌛ Истёк",
        }
        return labels.get(self.status, self.status)

    def __repr__(self) -> str:
        return f"<Payment id={self.id} user={self.user_id} status={self.status}>"
