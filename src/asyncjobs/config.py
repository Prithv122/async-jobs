"""Settings read from the environment / .env. See .env.example for the real variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    webhook_secret: str = "change-me"

    # Webhook delivery: bounded retries with exponential backoff, then give up.
    webhook_max_retries: int = 5
    webhook_backoff_base_seconds: float = 1.0

    # Idempotency-Key reservations expire so a client can safely reuse a key later.
    idempotency_key_ttl_seconds: int = 86400

    # How long the worker sleeps to simulate real processing work. Kept low in tests via
    # an env override so the suite doesn't sit idle for seconds per job.
    simulated_work_seconds: float = 2.0

    max_upload_bytes: int = 10 * 1024 * 1024


settings = Settings()
