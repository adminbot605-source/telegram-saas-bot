from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, and_
from aiogram.types import Chat
from bot.models.group import Group
from bot.repositories.base import BaseRepository


class GroupRepository(BaseRepository[Group]):
    def __init__(self, session: AsyncSession):
        super().__init__(Group, session)

    async def get_by_owner(self, owner_id: int) -> List[Group]:
        result = await self.session.execute(
            select(Group).where(
                and_(Group.owner_id == owner_id, Group.is_active == True)
            )
        )
        return list(result.scalars().all())

    async def get_by_owner_count(self, owner_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Group.id)).where(
                and_(Group.owner_id == owner_id, Group.is_active == True)
            )
        )
        return result.scalar() or 0

    async def register_or_update(self, chat: Chat, owner_id: int) -> tuple[Group, bool]:
        result = await self.session.execute(select(Group).where(Group.id == chat.id))
        group = result.scalar_one_or_none()

        if group:
            group.title = chat.title or group.title
            group.username = chat.username
            group.is_active = True
            if group.owner_id != owner_id:
                group.owner_id = owner_id
            await self.session.flush()
            return group, False

        group = Group(
            id=chat.id,
            owner_id=owner_id,
            title=chat.title or "Без названия",
            username=chat.username,
            chat_type=chat.type,
        )
        self.session.add(group)
        await self.session.flush()
        return group, True

    async def get_all_access_controlled(self) -> List[Group]:
        result = await self.session.execute(
            select(Group).where(
                and_(Group.is_active == True, Group.access_control_enabled == True)
            )
        )
        return list(result.scalars().all())

    async def get_stats(self) -> dict:
        total = await self.session.execute(select(func.count(Group.id)))
        active = await self.session.execute(
            select(func.count(Group.id)).where(Group.is_active == True)
        )
        controlled = await self.session.execute(
            select(func.count(Group.id)).where(
                and_(Group.is_active == True, Group.access_control_enabled == True)
            )
        )
        return {
            "total": total.scalar() or 0,
            "active": active.scalar() or 0,
            "access_controlled": controlled.scalar() or 0,
        }
