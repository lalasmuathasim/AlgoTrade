from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    redis_queue_prefix: str = "qubitx"

    zerodha_api_key: str | None = None
    zerodha_api_secret: str | None = None
    zerodha_access_token: str | None = None
    zerodha_redirect_url: str | None = None

    zerodha_live_trading_enabled: bool = False
    paper_trading_enabled: bool = True

    jwt_secret: str

    daily_scan_time: str = "15:45"
    market_timezone: str = "Asia/Kolkata"

    buy_volume_multiplier: float = 5.0
    sell_volume_multiplier: float = 3.0
    entry_buffer_ticks: float = 0.05
    stop_buffer_ticks: float = 0.05

    daily_candle_lookback: int = 100
    swing_window: int = 2
    max_gap_percent: float = 0.5
    min_swing_distance: float = 1.0

    api_host_port: int = 8095
    api_host_bind: str = "127.0.0.1"
    log_level: str = "INFO"

    worker_poll_timeout: int = 5
    worker_max_retries: int = 3
    scheduler_poll_interval_seconds: int = 30
    reconciliation_poll_interval_seconds: int = 300
    live_engine_runtime_ttl_seconds: int = 180

    access_token_expire_minutes: int = 720
    session_cookie_name: str = "qubitx_session"
    session_cookie_secure: bool = False
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    initial_admin_name: str | None = "Platform Administrator"
    totp_issuer: str = "Qubitx Control Center"

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    mock_data: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def signal_dispatch_queue_name(self) -> str:
        return f"{self.redis_queue_prefix}:signal_dispatch"

    @property
    def scheduler_queue_name(self) -> str:
        return f"{self.redis_queue_prefix}:scheduler"

    @property
    def live_engine_runtime_key(self) -> str:
        return f"{self.redis_queue_prefix}:live_engine_runtime"


class DependencyStatus(BaseModel):
    database: bool
    redis: bool


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
