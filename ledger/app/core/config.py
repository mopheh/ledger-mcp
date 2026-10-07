from pathlib import Path

from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24 * 7

    class Config:
        env_file = BASE_DIR / ".env.local"
        extra = "ignore"


settings = Settings()