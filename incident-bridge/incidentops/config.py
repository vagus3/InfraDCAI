from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INCIDENTOPS_", env_file=".env", extra="ignore")

    db_path: Path = Path("incidentops/data/incidentops.db")
    artifact_dir: Path = Path("incidentops/data/artifacts")
    triage_webhook_url: str | None = None
    fix_webhook_url: str | None = None
    notify_webhook_url: str | None = None

    # Bearer token required on fix-dispatch/verify/notify when set. Unset (the
    # local-demo default) leaves those endpoints open -- see api.py's
    # require_action_token and DESIGN.md/README.md for what that does and
    # does not mean about exposing this deployment.
    api_token: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_starttls: bool = True

    latency_alert_seconds: float = 5.0
    error_rate_alert_ratio: float = 0.05
    # A second, higher threshold on the same metric: above this the incident
    # opens as SEV2 instead of SEV3. Named and documented here instead of a
    # bare 0.2 inline, per CODE_RULES.md's "하드코딩을 분류해서 다룬다".
    error_rate_sev2_ratio: float = 0.2
    relative_latency_regression_ratio: float = 1.5
    correlation_window_minutes: int = 30


settings = Settings()
