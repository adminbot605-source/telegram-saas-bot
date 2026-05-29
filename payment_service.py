from typing import Optional, List, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_, func
from datetime import datetime, timezone
from bot.models.access import UserAccess
from bot.repositories.base import BaseRepository


class AccessRepository(BaseRepository[UserAccess]):
    def __init__(self, session: AsyncSession):
        super().__init__(UserAccess, session)

    async def get_user_group_access(self, user_id: int, group_id: int) -> Optional[UserAccess]:
        result = await self.session.execute(
            select(UserAccess).where(
                and_(
                    UserAccess.user_id == user_id,
                    UserAccess.group_id == group_id,
                    UserAccess.is_active == True,
                )
            ).order_by(UserAccess.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def is_user_authorized(self, user_id: int, group_id: int) -> bool:
        access = await self.get_user_group_access(user_id, group_id)
        if not access:
            return False
        return access.is_valid

    async def get_group_authorized_users(self, group_id: int) -> Set[int]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(UserAccess.user_id).where(
                and_(
                    UserAccess.group_id == group_id,
                    UserAccess.is_active == True,
                    (UserAccess.expires_at == None) | (UserAccess.expires_at > now),
                )
            )
        )
        return {row[0] for row in result.all()}

    async def get_expired_accesses(self) -> List[UserAccess]:
        now = datetime.now(timezone.utc)
        result = await self.session.execute(
            select(UserAccess).where(
                and_(
                    UserAccess.is_active == True,
                    UserAccess.is_lifetime == False,
                    UserAccess.expires_at != None,
                    UserAccess.expires_at <= now,
                )
            )
        )
        return list(result.scalars().all())

    async def get_expiring_soon(self, hours: int = 24) -> List[UserAccess]:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=hours)
        result = await self.session.execute(
            select(UserAccess).where(
                and_(
                    UserAccess.is_active == True,
                    UserAccess.is_lifetime == False,
                    UserAccess.expires_at != None,
                    UserAccess.expires_at > now,
                    UserAccess.expires_at <= deadline,
                )
            )
        )
        return list(result.scalars().all())

    async def grant_access(
        self,
        user_id: int,
        group_id: int,
        tariff_id: Optional[int],
        expires_at: Optional[datetime],
        is_lifetime: bool,
        granted_by: Optional[int],
        payment_id: Optional[int] = None,
        note: Optional[str] = None,
    ) -> UserAccess:
        await self.session.execute(
            update(UserAccess).where(
                and_(
                    UserAccess.user_id == user_id,
                    UserAccess.group_id == group_id,
                    UserAccess.is_active == True,
                )
            ).values(is_active=False)
        )

        access = UserAccess(
            user_id=user_id,
            group_id=group_id,
            tariff_id=tariff_id,
            payment_id=payment_id,
            granted_by=granted_by,
            is_active=True,
            is_lifetime=is_lifetime,
            expires_at=expires_at,
            note=note,
        )
        self.session.add(access)
        await self.session.flush()
        await self.session.refresh(access)
        return access

    async def revoke_access(self, user_id: int, group_id: int) -> bool:
        result = await self.session.execute(
            update(UserAccess).where(
                and_(
                    UserAccess.user_id == user_id,
                    UserAccess.group_id == group_id,
                    UserAccess.is_active == True,
                )
            ).values(is_active=False).returning(UserAccess.id)
        )
        await self.session.flush()
        return result.scalar_one_or_none() is not None

    async def expire_batch(self, access_ids: List[int]) -> int:
        if not access_ids:
            return 0
        result = await self.session.execute(
            update(UserAccess).where(
                UserAccess.id.in_(access_ids)
            ).values(is_active=False).returning(UserAccess.id)
        )
        await self.session.flush()
        return len(result.all())

    async def get_group_access_stats(self, group_id: int) -> dict:
        now = datetime.now(timezone.utc)
        total = await self.session.execute(
            select(func.count(UserAccess.id)).where(
                and_(UserAccess.group_id == group_id, UserAccess.is_active == True)
            )
        )
        lifetime = await self.session.execute(
            select(func.count(UserAccess.id)).where(
                and_(
                    UserAccess.group_id == group_id,
                    UserAccess.is_active == True,
                    UserAccess.is_lifetime == True,
                )
            )
        )
        expired_today = await self.session.execute(
            select(func.count(UserAccess.id)).where(
                and_(
                    UserAccess.group_id == group_id,
                    UserAccess.is_active == False,
                    UserAccess.expires_at != None,
                )
            )
        )
        return {
            "total_active": total.scalar() or 0,
            "lifetime": lifetime.scalar() or 0,
            "expired_total": expired_today.scalar() or 0,
        }

    async def get_user_accesses(self, user_id: int) -> List[UserAccess]:
        result = await self.session.execute(
            select(UserAccess).where(
                and_(UserAccess.user_id == user_id, UserAccess.is_active == True)
            )
        )
        return list(result.scalars().all())
