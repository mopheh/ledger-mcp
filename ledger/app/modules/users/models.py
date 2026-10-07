from sqlmodel import SQLModel, Field
class User(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    is_active: bool = Field(default=True)
    
