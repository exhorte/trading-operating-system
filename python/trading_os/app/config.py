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

from trading_os.domain.market.sessions import parse_trading_windows
from trading_os.domain.risk.n8 import percent_to_units
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

    # MT5. False = simulated mode (FakeMt5.demo): no terminal; the worker process still runs, against an in-memory one.
    mt5_enabled: bool = True
    trading_mode: TradingMode = TradingMode.OBSERVE
    active_account_id: str | None = None
    # S02 (ADR 0024): "off" evaluates nothing, "measure" records what it sees and proposes nothing to the Risk Engine, "trade" acts like
    # S01 does. Turning it to "trade" is the user's act, never a default.
    strategy_s02: Literal["off", "measure", "trade"] = "off"
    # The hours each strategy looks for a setup (ADR 0030), **New York local time** — the zone moves them with daylight saving, so no
    # offset is ever written here — as ``name=HH:MM-HH:MM`` separated by commas: ``london=02:00-05:00,new_york_am=08:30-11:00``.
    # Empty = the strategy's own defaults (S01: 02:00–05:00 and 07:00–10:00; S02: 02:00–05:00 and 08:30–11:00). A malformed value
    # stops the core at start: it is never guessed.
    strategy_s01_windows: str = ""
    strategy_s02_windows: str = ""

    # Account Guardian (ADR 0032). OFF by default — a new automatic behaviour, the user's to switch on: the core's resting orders on a symbol whose
    # spread is over the cap he wrote for it (``max_spread_by_symbol``) are cancelled. Positions are never closed for a spread.
    guardian_cancel_orders_on_wide_spread: bool = False

    # N8 « Drawdown Flatlining » (ADR 0031): a reduction of the risk of the next trade — it can only LOWER it, never raise it, and it cannot go
    # round any limit (the final risk is the smallest of all the caps). Off by default, and inert until its smallest unit is written: the notes
    # do not give that value, and it is not guessed. The unit is in multiples of 0.1 %; 0 means « no new trade » while a trigger holds.
    risk_n8_enabled: bool = False
    risk_n8_minimum_percent: float | None = Field(default=None, ge=0)
    risk_n8_reduce_after_loss: bool = True  # N8 §j.3: one loss → the smallest unit until a trade wins
    risk_n8_wins_before_minimum: int = Field(
        default=5, ge=0
    )  # N8 §j.4: after 5 wins in a row the next trade is at the smallest unit; 0 = off
    risk_n8_reduce_below_starting_equity: bool = True  # N8 §j.2: equity under the starting capital → the smallest unit

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
    # How many M1 bars are read from the terminal when an account connects (about a day: the strategy needs context at once).
    market_backfill_bars: int = Field(default=1500, ge=10, le=20_000)

    @field_validator("allowed_origins")
    @classmethod
    def _strip(cls, value: str) -> str:
        return ",".join(part.strip() for part in value.split(",") if part.strip())

    @field_validator("strategy_s01_windows", "strategy_s02_windows")
    @classmethod
    def _windows_are_well_formed(cls, value: str) -> str:
        if value.strip():
            parse_trading_windows(value)  # raises ValueError, which pydantic reports against the setting's name
        return value.strip()

    @field_validator("risk_n8_minimum_percent")
    @classmethod
    def _n8_minimum_is_a_whole_unit(cls, value: float | None) -> float | None:
        if value is not None:
            percent_to_units(value)  # raises ValueError: a value between two 0.1 % units is refused, never rounded
        return value

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
