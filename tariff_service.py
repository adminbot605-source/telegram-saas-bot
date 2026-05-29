from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from bot.models.tariff import Tariff
from bot.repositories.base import BaseRepository


class TariffRepository(BaseRepository[Tariff]):
    def __init__(self, session: AsyncSession):
        super().__init__(Tariff, session)

    async def get_group_tariffs(self, group_id: int, active_only: bool = True) -> List[Tariff]:
        q = select(Tariff).where(Tariff.group_id == group_id)
        if active_only:
            q = q.where(Tariff.is_active == True)
        q = q.order_by(Tariff.position.asc(), Tariff.price.asc())
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def get_active(self, tariff_id: int) -> Optional[Tariff]:
        result = await self.session.execute(
            select(Tariff).where(
                and_(Tariff.id == tariff_id, Tariff.is_active == True)
            )
        )
        return result.scalar_one_or_none()
