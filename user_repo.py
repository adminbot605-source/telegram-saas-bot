from sqlalchemy import BigInteger, String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional, List
from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    referred_by: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    messages_deleted: Mapped[int] = mapped_column(Integer, default=0)

    groups: Mapped[List["Group"]] = relationship(
        "Group", back_populates="owner", lazy="selectin"
    )
    accesses: Mapped[List["UserAccess"]] = relationship(
        "UserAccess", foreign_keys="UserAccess.user_id", back_populates="user", lazy="selectin"
    )

    @property
    def full_name(self) -> str:
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name

    @property
    def mention_html(self) -> str:
        return f"<a href='tg://user?id={self.id}'>{self.full_name}</a>"

    @property
    def mention(self) -> str:
        if self.username:
            return f"@{self.username}"
        return self.mention_html

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username}>"
