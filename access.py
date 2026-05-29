"""
Security utilities:
  - Webhook signature validation
  - HMAC-signed callback data (prevent forgery)
  - Owner/creator permission checks
  - Anti-exploit validations
"""

import hashlib
import hmac
import time
import re
from typing import Optional
from aiohttp import web
from loguru import logger

from bot.config import settings


# --- Webhook signature ---

def verify_webhook_signature(secret: str, body: bytes, header_token: Optional[str]) -> bool:
    if not header_token:
        logger.warning("Webhook: missing X-Telegram-Bot-Api-Secret-Token header")
        return False
    expected = hashlib.sha256(secret.encode()).hexdigest()
    ok = hmac.compare_digest(header_token, expected)
    if not ok:
        logger.warning(f"Webhook: invalid signature token")
    return ok


# --- HMAC-signed callback data ---

_CB_SEP = "|"
_CB_VERSION = "1"


def sign_callback(action: str, entity_id: int | str, user_id: int, ttl: int = 300) -> str:
    """
    Create HMAC-signed callback data.
    Format: v1|action|entity_id|user_id|expires|hmac
    """
    expires = int(time.time()) + ttl
    payload = f"{_CB_VERSION}{_CB_SEP}{action}{_CB_SEP}{entity_id}{_CB_SEP}{user_id}{_CB_SEP}{expires}"
    sig = _hmac_sign(payload)
    return f"{payload}{_CB_SEP}{sig}"


def verify_callback(data: str, caller_user_id: int) -> Optional[tuple[str, str]]:
    """
    Verify signed callback. Returns (action, entity_id) or None on failure.
    """
    try:
        parts = data.split(_CB_SEP)
        if len(parts) != 6:
            return None
        version, action, entity_id, user_id_str, expires_str, sig = parts
        if version != _CB_VERSION:
            return None
        if int(expires_str) < time.time():
            logger.debug(f"Callback expired: {action}")
            return None
        if int(user_id_str) != caller_user_id:
            logger.warning(f"Callback user mismatch: expected {user_id_str} got {caller_user_id}")
            return None
        payload = _CB_SEP.join(parts[:5])
        if not hmac.compare_digest(sig, _hmac_sign(payload)):
            logger.warning("Callback HMAC mismatch")
            return None
        return action, entity_id
    except Exception as e:
        logger.debug(f"verify_callback error: {e}")
        return None


def _hmac_sign(payload: str) -> str:
    return hmac.new(
        settings.WEBHOOK_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


# --- Permission checks ---

def require_creator(user_id: int) -> bool:
    return user_id == settings.CREATOR_USER_ID


def require_owner_or_creator(user_id: int, group_owner_id: int) -> bool:
    return user_id == group_owner_id or user_id == settings.CREATOR_USER_ID


# --- Anti-exploit ---

def validate_user_id(raw: str) -> Optional[int]:
    """Parse and validate a Telegram user ID from user input."""
    raw = raw.strip()
    if not re.fullmatch(r"\d{5,15}", raw):
        return None
    uid = int(raw)
    if uid <= 0 or uid > 10**15:
        return None
    return uid


def validate_group_id(raw: str) -> Optional[int]:
    """Parse and validate a Telegram group/channel ID."""
    raw = raw.strip().lstrip("-")
    if not re.fullmatch(r"\d{5,20}", raw):
        return None
    gid = -int(raw)
    return gid


def sanitize_html(text: str, max_length: int = 4096) -> str:
    """Basic HTML sanitizer for user-provided text."""
    text = text[:max_length]
    text = text.replace("<script", "&lt;script").replace("javascript:", "")
    return text


def validate_payment_amount(raw: str) -> Optional[float]:
    try:
        amount = float(raw.replace(",", ".").replace(" ", ""))
        if amount < 0 or amount > 1_000_000:
            return None
        return round(amount, 2)
    except (ValueError, TypeError):
        return None
