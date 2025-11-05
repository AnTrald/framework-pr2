from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://user:password@localhost:5432/users_db"

    # JWT
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Service
    environment: str = "development"
    service_name: str = "users_service"
    debug: bool = False

    class Config:
        env_file = ".env"


settings = Settings()