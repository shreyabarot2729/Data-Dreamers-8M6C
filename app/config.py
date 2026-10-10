from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = Field(default="sqlite+aiosqlite:///:memory:")
    database_echo: bool = False
    secret_key: str = "dev-secret-key-change-me"
    otp_ttl_seconds: int = 300
    otp_provider: str = "demo"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_verify_service_sid: str | None = None
    face_provider: str = "demo"
    aws_region: str = "us-east-1"
    aws_rekognition_collection: str = "eventsecure-participants"
    face_match_threshold: float = Field(default=90, ge=50, le=100)
    local_face_model_dir: str = "models"
    local_face_match_threshold: float = Field(default=0.363, ge=-1, le=1)
    app_url: str = "http://127.0.0.1:8000"
    verify_face: bool = True
    verify_liveness: bool = True
    verify_pad: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
