from sqlalchemy import BigInteger, Integer, Boolean, ForeignKey, String, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from .base import Base, TimestampMixin


class Tariff(Base, TimestampMixin):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("groups.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_lifetime: Mapped[bool] = mapped_column(Boolean, default=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="RUB")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    payment_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    qr_code_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    group: Mapped[Optional["Group"]] = relationship("Group", back_populates="tariffs")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="tariff")
    accesses: Mapped[List["UserAccess"]] = relationship("UserAccess", back_populates="tariff")

    @property
    def duration_label(self) -> str:
        if self.is_lifetime:
            return "Бессрочно"
        if not self.duration_days:
            return "Не указано"
        if self.duration_days % 365 == 0:
            years = self.duration_days // 365
            return f"{years} год" if years == 1 else f"{years} лет"
        if self.duration_days % 30 == 0:
            months = self.duration_days // 30
            return f"{months} мес."
        return f"{self.duration_days} дн."

    @property
    def price_label(self) -> str:
        if self.price == 0:
            return "Бесплатно"
        return f"{int(self.price)}₽"

    def __repr__(self) -> str:
        return f"<Tariff id={self.id} name={self.name} group={self.group_id}>"
