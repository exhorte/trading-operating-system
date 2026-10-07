"""Configuration — environment variables and the gitignored ``04_code/.env`` (never committed).

Secrets are ``SecretStr`` and are registered with the log masker the moment settings are loaded, so even an
accidental ``print(settings)`` or a library echoing a URL cannot leak them.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trading_os.shared.logging.redaction import register_secret

# python/trading_os/app/config.py -> repo root (04_code)
REPO_ROOT = Path(__file__).resolve().parents[3]


class TradingMode(StrEnum):
    """The autonomy ladder (domain/autonomy/state.py owns the transitions). Here it is only the **ceiling**:
    the system can never run above it. Default OBSERVE: nothing is ever sent anywhere."""

    OFF = "OFF"
    OBSERVE = "OBSERVE"
    PAPER = "PAPER"
    CONFIRM = "CONFIRM"
    ARMED = "ARMED"
    AUTONOMOUS = "AUTONOMOUS"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        case_sensitive=False,
    )

    trading_env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"

    # Database. No default: the password is not in the code. scripts/start.ps1 writes it to .env.
    database_url: SecretStr | None = None

    # MT5. False = simulated mode (FakeMt5): no terminal, no worker process.
    mt5_enabled: bool = True
    trading_mode: TradingMode = TradingMode.OBSERVE
    active_account_id: str | None = None

    # Network surface — loopback only.
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    ea_link_host: str = "127.0.0.1"
    ea_link_port: int = 9765
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Secrets (separate from the configuration above).
    trading_os_cockpit_token: SecretStr | None = Field(default=None, validation_alias="TRADINGOS_COCKPIT_TOKEN")
    trading_os_agent_token: SecretStr | None = Field(default=None, validation_alias="TRADINGOS_AGENT_TOKEN")
    fred_api_key: SecretStr | None = None

    # Credentials of broker accounts: "none" (ADR 0013 default — nothing stored), "windows" (OS vault, opt-in),
    # "env" (development only: MT5_PASSWORD_<ACCOUNT_ID>).
    credential_store: Literal["none", "windows", "env"] = "none"

    # Tuning (seconds). Kept configurable so tests can run fast; defaults are the production values.
    ea_ping_interval_s: float = 5.0
    ea_silent_after_s: float = 30.0
    heartbeat_interval_s: float = 2.0
    supervisor_interval_s: float = 2.0
    positions_poll_interval_s: float = 2.0
    tick_poll_interval_s: float = 1.0

    @field_validator("allowed_origins")
    @classmethod
    def _strip(cls, value: str) -> str:
        return ",".join(part.strip() for part in value.split(",") if part.strip())

    @property
    def origins(self) -> list[str]:
        return [o for o in self.allowed_origins.split(",") if o]

    def secret_values(self) -> list[str]:
        values = [self.database_url, self.trading_os_cockpit_token, self.trading_os_agent_token, self.fred_api_key]
        return [v.get_secret_value() for v in values if v is not None]

    def register_secrets(self) -> None:
        for value in self.secret_values():
            register_secret(value)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.register_secrets()
    return settings
