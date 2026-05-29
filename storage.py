from sqlalchemy import BigInteger, String, Boolean, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from .base import Base, TimestampMixin


class Group(Base, TimestampMixin):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(20), nullable=False, default="supergroup")
    member_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    access_control_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_unauthorized: Mapped[bool] = mapped_column(Boolean, default=True)

    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    welcome_delete_after: Mapped[int] = mapped_column(Integer, default=0)

    anti_spam_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    anti_flood_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    flood_limit: Mapped[int] = mapped_column(Integer, default=5)
    flood_mute_duration: Mapped[int] = mapped_column(Integer, default=60)

    delete_joins: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_links: Mapped[bool] = mapped_column(Boolean, default=False)
    delete_forwards: Mapped[bool] = mapped_column(Boolean, default=False)

    notification_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    payment_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    owner: Mapped["User"] = relationship("User", back_populates="groups")
    tariffs: Mapped[List["Tariff"]] = relationship(
        "Tariff", back_populates="group", lazy="selectin"
    )
    scheduled_posts: Mapped[List["ScheduledPost"]] = relationship(
        "ScheduledPost", back_populates="group", lazy="selectin"
    )

    @property
    def active_tariffs(self) -> List["Tariff"]:
        return [t for t in self.tariffs if t.is_active]

    @property
    def link(self) -> str:
        if self.username:
            return f"https://t.me/{self.username}"
        return f"tg://openmessage?chat_id={self.id}"

    def __repr__(self) -> str:
        return f"<Group id={self.id} title={self.title}>"
