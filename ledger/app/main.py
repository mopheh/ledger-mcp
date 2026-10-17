from fastapi import FastAPI

from app.modules.accounts.router import router as accounts_router
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router

app = FastAPI(title="Ledger API")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(accounts_router)

