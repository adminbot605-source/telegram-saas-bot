from typing import TypeVar, Generic, Type, Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from bot.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, id_: Any) -> Optional[ModelType]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id_)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> List[ModelType]:
        result = await self.session.execute(select(self.model))
        return list(result.scalars().all())

    async def create(self, **kwargs) -> ModelType:
        obj = self.model(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def update_by_id(self, id_: Any, **kwargs) -> Optional[ModelType]:
        await self.session.execute(
            update(self.model).where(self.model.id == id_).values(**kwargs)
        )
        await self.session.flush()
        return await self.get_by_id(id_)

    async def delete_by_id(self, id_: Any) -> bool:
        result = await self.session.execute(
            delete(self.model).where(self.model.id == id_).returning(self.model.id)
        )
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def count(self) -> int:
        from sqlalchemy import func
        result = await self.session.execute(select(func.count(self.model.id)))
        return result.scalar() or 0
