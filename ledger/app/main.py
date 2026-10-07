from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.database import init_db
from app.modules.accounts.router import router as accounts_router
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Ledger API", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(accounts_router)
