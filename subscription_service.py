from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from bot.models.payment import Payment, PaymentStatus
from bot.repositories.base import BaseRepository
from datetime import datetime, timezone


class PaymentRepository(BaseRepository[Payment]):
    def __init__(self, session: AsyncSession):
        super().__init__(Payment, session)

    async def get_pending_for_group(self, group_id: int) -> List[Payment]:
        result = await self.session.execute(
            select(Payment).where(
                and_(
                    Payment.group_id == group_id,
                    Payment.status == PaymentStatus.PENDING.value,
                )
            ).order_by(Payment.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_pending_all(self) -> List[Payment]:
        result = await self.session.execute(
            select(Payment).where(
                Payment.status == PaymentStatus.PENDING.value
            ).order_by(Payment.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_by_user_group(self, user_id: int, group_id: int) -> List[Payment]:
        result = await self.session.execute(
            select(Payment).where(
                and_(Payment.user_id == user_id, Payment.group_id == group_id)
            ).order_by(Payment.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_user_pending(self, user_id: int, group_id: int) -> Optional[Payment]:
        result = await self.session.execute(
            select(Payment).where(
                and_(
                    Payment.user_id == user_id,
                    Payment.group_id == group_id,
                    Payment.status == PaymentStatus.PENDING.value,
                )
            ).order_by(Payment.created_at.desc())
        )
        return result.scalar_one_or_none()

    async def approve(
        self,
        payment_id: int,
        reviewer_id: int,
        note: Optional[str] = None,
    ) -> Optional[Payment]:
        now = datetime.now(timezone.utc)
        return await self.update_by_id(
            payment_id,
            status=PaymentStatus.APPROVED.value,
            reviewer_id=reviewer_id,
            reviewed_at=now,
            admin_note=note,
        )

    async def reject(
        self,
        payment_id: int,
        reviewer_id: int,
        note: Optional[str] = None,
    ) -> Optional[Payment]:
        now = datetime.now(timezone.utc)
        return await self.update_by_id(
            payment_id,
            status=PaymentStatus.REJECTED.value,
            reviewer_id=reviewer_id,
            reviewed_at=now,
            admin_note=note,
        )

    async def get_group_stats(self, group_id: int) -> dict:
        total = await self.session.execute(
            select(func.count(Payment.id)).where(Payment.group_id == group_id)
        )
        approved = await self.session.execute(
            select(func.count(Payment.id), func.sum(Payment.amount)).where(
                and_(
                    Payment.group_id == group_id,
                    Payment.status == PaymentStatus.APPROVED.value,
                )
            )
        )
        row = approved.one()
        return {
            "total": total.scalar() or 0,
            "approved_count": row[0] or 0,
            "total_revenue": float(row[1] or 0),
        }

    async def get_all_stats(self) -> dict:
        approved = await self.session.execute(
            select(func.count(Payment.id), func.sum(Payment.amount)).where(
                Payment.status == PaymentStatus.APPROVED.value
            )
        )
        row = approved.one()
        pending_count = await self.session.execute(
            select(func.count(Payment.id)).where(
                Payment.status == PaymentStatus.PENDING.value
            )
        )
        return {
            "approved_count": row[0] or 0,
            "total_revenue": float(row[1] or 0),
            "pending_count": pending_count.scalar() or 0,
        }
