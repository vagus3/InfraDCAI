from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INCIDENTOPS_", env_file=".env", extra="ignore")

    db_path: Path = Path("incidentops/data/incidentops.db")
    artifact_dir: Path = Path("incidentops/data/artifacts")
    triage_webhook_url: str | None = None
    fix_webhook_url: str | None = None
    notify_webhook_url: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_starttls: bool = True

    latency_alert_seconds: float = 5.0
    error_rate_alert_ratio: float = 0.05
    relative_latency_regression_ratio: float = 1.5
    correlation_window_minutes: int = 30


settings = Settings()
