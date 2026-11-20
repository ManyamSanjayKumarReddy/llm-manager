"""Application settings, read from environment variables and validated by Pydantic."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from llm_manager.core.models_config import EngineConfig


class Settings(BaseSettings):
    """Security and infrastructure settings. Models are registered in the dashboard."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), extra="ignore", case_sensitive=False
    )

    database_url: str = Field(description="postgres://user:password@host:5432/dbname")
    web_dist_path: Path | None = Field(
        None, description="built dashboard (web/dist); served by the API when it exists"
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Scheduler timings (the defaults suit most setups)
    queue_timeout_s: float = Field(120.0, gt=0, description="longest a request waits for its model")
    wake_timeout_s: float = Field(90.0, gt=0, description="one wake-up call")
    sleep_timeout_s: float = Field(60.0, gt=0, description="one sleep call")
    min_awake_s: float = Field(10.0, ge=0, description="turn length when another model waits")
    priority_hold_s: float = Field(10.0, ge=0, description="protects a busy higher-priority model")
    preempt_after_s: float | None = Field(
        None,
        gt=0,
        description="after a request waited this long, stop lower-priority running requests",
    )
    reaper_interval_s: float = Field(15.0, gt=0, description="how often idle models are checked")
    sleep_level: int = Field(1, ge=1, le=2, description="1 keeps weights in CPU RAM (fast wake)")

    # Sessions and cookies
    cookie_secure: bool = True  # False only for plain-HTTP local testing
    session_hours: float = Field(12.0, gt=0, description="absolute session lifetime")
    session_idle_minutes: float = Field(30.0, gt=0, description="idle timeout")

    # Login protection
    lockout_attempts: int = Field(5, ge=1, description="wrong passwords before locking")
    lockout_minutes: float = Field(15.0, gt=0)
    login_ip_limit_per_min: int = Field(20, ge=1)
    min_password_length: int = Field(12, ge=8)

    # Data retention
    retention_days: int = Field(30, ge=1, description="request log and event history")
    audit_retention_days: int = Field(365, ge=30)
    usage_retention_days: int = Field(730, ge=30, description="daily token and request totals")

    # The agent that clients install on their GPU servers (see /install-agent.sh)
    agent_docker_image: str = Field(
        "wakeful/agent:latest",
        description="Docker image the install command pulls; set it to the one you published",
    )

    vllm_image: str = Field(
        "mockdigilabs/vllm-openai-abortsleep-0.10.1:latest",
        description="vLLM image GPU servers use (the build whose /sleep aborts requests); the "
        "install command lets the agent start only this repository and downloads it once",
    )

    # Reverse proxy
    trust_proxy: bool = False  # take the client IP from X-Real-IP (only behind a proxy you control)
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated list in the environment."""
        if isinstance(value, str):
            return [o.strip().rstrip("/") for o in value.split(",") if o.strip()]
        return value

    @property
    def engine(self) -> EngineConfig:
        """The scheduler's timings."""
        return EngineConfig(
            queue_timeout_s=self.queue_timeout_s,
            wake_timeout_s=self.wake_timeout_s,
            sleep_timeout_s=self.sleep_timeout_s,
            min_awake_s=self.min_awake_s,
            priority_hold_s=self.priority_hold_s,
            preempt_after_s=self.preempt_after_s,
            reaper_interval_s=self.reaper_interval_s,
            sleep_level=self.sleep_level,
        )

    @property
    def session_cookie_name(self) -> str:
        """``__Host-`` pins the cookie to this host over HTTPS; it requires ``Secure``."""
        return "__Host-lm_session" if self.cookie_secure else "lm_session"


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process."""
    return Settings()
