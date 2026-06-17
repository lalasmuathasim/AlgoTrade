from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrategyTuningConfig(BaseModel):
    lookbackCandles: int = 20
    maxGapPercent: float = 0.5
    minSwingDistance: float = 1.0
    buyVolumeMultiplier: float = 1.0
    sellVolumeMultiplier: float = 1.0
    entryBufferTicks: float = 0.05
    stopLossBufferTicks: float = 0.05


class Settings(BaseSettings):
    database_url: str
    webhook_secret: str
    redis_url: str
    jwt_secret: str
    signal_queue_name: str = "trading_signals_queue"
    mock_data: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    app_port: int = 8095
    log_level: str = "INFO"
    worker_poll_timeout: int = 5
    worker_max_retries: int = 3
    access_token_expire_minutes: int = 720
    session_cookie_name: str = "trading_session"
    session_cookie_secure: bool = False
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    initial_admin_name: str | None = "Platform Administrator"
    totp_issuer: str = "AlgoTrade Control Center"
    strategy_tuning: StrategyTuningConfig = Field(default_factory=StrategyTuningConfig)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
