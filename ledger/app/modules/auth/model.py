from sqlmodel import DateTime, DateTime, Field, SQLModel
from datetime import datetime, timezone

class APIKey(SQLModel, table=True):
    __tablename__ = "api_keys"

    id: int  =  Field(default=None, primary_key=True)
    key_hash: str = Field(index=True, unique=True)
    prefix: str = Field(index=True)
    user_id: int = Field(foreign_key="user.id")
    name: str | None = Field(default=None)
    is_active: bool = Field(default=True)
    expires_at: datetime | None  = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_type=DateTime(timezone=True))
    last_used_at: datetime |None  = Field(default=None, sa_type=DateTime(timezone=True))