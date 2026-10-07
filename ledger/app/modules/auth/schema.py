import enum
from datetime import datetime

from pydantic import BaseModel


class Environment(str, enum.Enum):
    test = "test"
    live = "live"


class APIKeyCreateSchema(BaseModel):
    environment: Environment
    name: str | None = None


class APIKeyResponseSchema(BaseModel):
    key: str


class APIKeyReadSchema(BaseModel):
    id: int
    prefix: str
    name: str | None = None
    is_active: bool
    expires_at: datetime | None = None
    created_at: datetime
    last_used_at: datetime | None = None

    class Config:
        from_attributes = True
