from sqlalchemy import Integer, Boolean, ForeignKey, Text, String, LargeBinary
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional
from .base import Base, TimestampMixin


class QRCode(Base, TimestampMixin):
    __tablename__ = "qr_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tariff_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tariffs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    image_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    payment_details_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_file_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tariff: Mapped["Tariff"] = relationship("Tariff", lazy="selectin")

    def __repr__(self) -> str:
        return f"<QRCode tariff={self.tariff_id} custom={self.is_custom}>"
