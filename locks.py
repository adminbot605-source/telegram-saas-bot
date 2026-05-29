import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    BOT_TOKEN: str
    BOT_USERNAME: str = "@zarabot_botbot"
    CREATOR_USER_ID: int

    WEBHOOK_HOST: str = "https://your-domain.com"
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = "supersecretwebhook123"

    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "saas_bot"
    POSTGRES_USER: str = "botuser"
    POSTGRES_PASSWORD: str = "botpassword123secure"

    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None

    WEB_SERVER_HOST: str = "0.0.0.0"
    WEB_SERVER_PORT: int = 8080

    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    THROTTLE_RATE: float = 0.3
    ACCESS_CACHE_TTL: int = 3600
    ACCESS_CACHE_KEY_PREFIX: str = "access"

    FREE_GROUPS_LIMIT: int = 1
    BASIC_GROUPS_LIMIT: int = 5
    PRO_GROUPS_LIMIT: int = 20

    PAYMENT_SUPPORT_USERNAME: str = "@support"
    REFERRAL_BONUS_DAYS: int = 7

    AUTO_MIGRATE: bool = True

    DELETE_WORKERS: int = 4
    SHARD_COUNT: int = 1
    SHARD_ID: int = 0

    @field_validator("BOT_TOKEN")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if not v or v == "your_bot_token_here":
            print("ERROR: BOT_TOKEN is not set!", file=sys.stderr)
            sys.exit(1)
        return v

    @field_validator("CREATOR_USER_ID")
    @classmethod
    def validate_creator(cls, v: int) -> int:
        if v == 0:
            print("ERROR: CREATOR_USER_ID is not set!", file=sys.stderr)
            sys.exit(1)
        return v

    @property
    def webhook_url(self) -> str:
        return f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


settings = Settings()
