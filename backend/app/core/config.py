from functools import lru_cache
import json
import os
from typing import Any, List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def detect_prometheus_url() -> str:
    explicit = os.getenv("PROMETHEUS_URL")
    if explicit:
        return explicit
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return "http://prometheus-k8s.monitoring.svc:9090"
    return "http://localhost:19090"


class Settings(BaseSettings):
    prometheus_url: str = detect_prometheus_url()
    grafana_url: str = "http://grafana.monitoring.svc:3000"
    default_namespace: str = "default"
    cors_origins: List[str] | str = [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []

            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except json.JSONDecodeError:
                    # Fall back to plain/comma-separated parsing.
                    pass

            return [origin.strip() for origin in raw.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
