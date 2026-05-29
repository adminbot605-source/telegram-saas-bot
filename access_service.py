"""
QR code storage backend.

Primary: PostgreSQL bytea (no external deps).
Optional: S3-compatible (MinIO/Backblaze) via boto3.

Cache: Redis with configurable TTL.
"""

import hashlib
import io
from typing import Optional
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from loguru import logger

from bot.models.qr_code import QRCode
from bot.qr.generator import QRGenerator


QR_CACHE_PREFIX = "qr:cache"
QR_CACHE_TTL = 86400  # 24 hours


class QRStorage:
    def __init__(self, redis: Redis):
        self.redis = redis
        self._generator = QRGenerator()

    async def get_or_generate(
        self,
        session: AsyncSession,
        tariff_id: int,
        payment_details: str,
        group_title: str,
        tariff_name: str,
        amount: float,
        currency: str = "RUB",
        force_regen: bool = False,
    ) -> tuple[bytes, bool]:
        """
        Returns (qr_bytes, is_from_cache).
        Tries: Redis cache → PostgreSQL → Generate & store.
        """
        cache_key = f"{QR_CACHE_PREFIX}:{tariff_id}"

        if not force_regen:
            cached = await self.redis.get(cache_key)
            if cached:
                return bytes(cached), True

        stored = await self._load_from_db(session, tariff_id)
        if stored and not force_regen:
            await self.redis.setex(cache_key, QR_CACHE_TTL, stored)
            return stored, False

        qr_bytes = QRGenerator.generate_payment_qr(
            payment_details=payment_details,
            group_title=group_title,
            tariff_name=tariff_name,
            amount=amount,
            currency=currency,
        )

        await self._save_to_db(session, tariff_id, qr_bytes, payment_details)
        await self.redis.setex(cache_key, QR_CACHE_TTL, qr_bytes)
        logger.info(f"QR generated and stored for tariff {tariff_id}")
        return qr_bytes, False

    async def store_custom_qr(
        self,
        session: AsyncSession,
        tariff_id: int,
        qr_bytes: bytes,
        payment_details: Optional[str] = None,
    ) -> None:
        """Store a custom (user-uploaded) QR image."""
        if not QRGenerator.validate_qr_bytes(qr_bytes):
            raise ValueError("Invalid PNG image data")
        if len(qr_bytes) > 5 * 1024 * 1024:
            raise ValueError("QR image too large (max 5MB)")
        await self._save_to_db(session, tariff_id, qr_bytes, payment_details, is_custom=True)
        cache_key = f"{QR_CACHE_PREFIX}:{tariff_id}"
        await self.redis.setex(cache_key, QR_CACHE_TTL, qr_bytes)

    async def invalidate(self, tariff_id: int) -> None:
        await self.redis.delete(f"{QR_CACHE_PREFIX}:{tariff_id}")

    async def delete(self, session: AsyncSession, tariff_id: int) -> None:
        await session.execute(
            update(QRCode).where(QRCode.tariff_id == tariff_id).values(is_active=False)
        )
        await self.invalidate(tariff_id)

    async def _load_from_db(self, session: AsyncSession, tariff_id: int) -> Optional[bytes]:
        result = await session.execute(
            select(QRCode.image_data).where(
                QRCode.tariff_id == tariff_id, QRCode.is_active == True
            )
        )
        row = result.scalar_one_or_none()
        return bytes(row) if row else None

    async def _save_to_db(
        self,
        session: AsyncSession,
        tariff_id: int,
        qr_bytes: bytes,
        payment_details: Optional[str],
        is_custom: bool = False,
    ) -> None:
        checksum = hashlib.md5(qr_bytes).hexdigest()
        existing = await session.execute(select(QRCode).where(QRCode.tariff_id == tariff_id))
        obj = existing.scalar_one_or_none()

        if obj:
            obj.image_data = qr_bytes
            obj.checksum = checksum
            obj.payment_details_snapshot = payment_details
            obj.is_custom = is_custom
            obj.is_active = True
        else:
            obj = QRCode(
                tariff_id=tariff_id,
                image_data=qr_bytes,
                checksum=checksum,
                payment_details_snapshot=payment_details,
                is_custom=is_custom,
                is_active=True,
            )
            session.add(obj)
        await session.flush()
