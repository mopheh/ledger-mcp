from sqlmodel import SQLModel, Field
class User(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    is_active: bool = Field(default=True)
    is_admin: bool = Field(default=False, nullable=False, sa_column_kwargs={"server_default": "false"})
    
