"""Typed configuration using pydantic-settings"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Environment
    environment: str = "local"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # Output
    output_dir: str = "/app/output"
    job_images_dir: str = "/app/job_images"
    image_expiry_minutes: int = 30
    api_base_url: str = "http://api:8000"

    # fal.ai
    fal_key: str = ""

    # Security
    api_allowed_ips: str = ""  # Comma-separated

    # Rate limiting for the anonymous, expensive /jobs endpoint.
    # All knobs are configurable via env / .env.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 5      # max job submissions per IP per rolling minute
    rate_limit_per_hour: int = 30       # max job submissions per IP per rolling hour
    rate_limit_per_day: int = 100       # hard daily cap per IP

    @property
    def allowed_ips_list(self) -> list[str]:
        """Parse comma-separated IPs into list"""
        return [ip.strip() for ip in self.api_allowed_ips.split(",") if ip.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
