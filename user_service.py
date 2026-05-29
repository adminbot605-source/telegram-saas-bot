from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from aiogram.types import User as TgUser
from bot.models.user import User
from bot.repositories.base import BaseRepository
import secrets
import string


def generate_referral_code(user_id: int) -> str:
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"REF{user_id}{suffix}"


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_or_create(self, tg_user: TgUser) -> tuple[User, bool]:
        result = await self.session.execute(select(User).where(User.id == tg_user.id))
        user = result.scalar_one_or_none()

        if user:
            changed = False
            if user.username != tg_user.username:
                user.username = tg_user.username
                changed = True
            if user.first_name != tg_user.first_name:
                user.first_name = tg_user.first_name
                changed = True
            if user.last_name != tg_user.last_name:
                user.last_name = tg_user.last_name
                changed = True
            if changed:
                await self.session.flush()
            return user, False

        ref_code = generate_referral_code(tg_user.id)
        user = User(
            id=tg_user.id,
            username=tg_user.username,
            first_name=tg_user.first_name,
            last_name=tg_user.last_name,
            language_code=tg_user.language_code,
            is_bot=tg_user.is_bot,
            referral_code=ref_code,
        )
        self.session.add(user)
        await self.session.flush()
        return user, True

    async def get_by_referral_code(self, code: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.referral_code == code)
        )
        return result.scalar_one_or_none()

    async def increment_deleted_messages(self, user_id: int) -> None:
        await self.session.execute(
            update(User).where(User.id == user_id).values(
                messages_deleted=User.messages_deleted + 1
            )
        )

    async def get_stats(self) -> dict:
        total = await self.session.execute(select(func.count(User.id)))
        blocked = await self.session.execute(
            select(func.count(User.id)).where(User.is_blocked == True)
        )
        today_count = await self.session.execute(
            select(func.count(User.id)).where(
                func.date(User.created_at) == func.current_date()
            )
        )
        return {
            "total": total.scalar() or 0,
            "blocked": blocked.scalar() or 0,
            "today": today_count.scalar() or 0,
        }

    async def get_all_ids(self, exclude_blocked: bool = True) -> List[int]:
        q = select(User.id)
        if exclude_blocked:
            q = q.where(User.is_blocked == False)
        result = await self.session.execute(q)
        return [row[0] for row in result.all()]
