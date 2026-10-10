# Ledger

Ledger is a small money-movement API. Users sign up, open accounts, fund them, and move money between them. Every movement is recorded as a pair of ledger entries, so the books can be checked at any time: debits and credits must add up to zero.

It is a learning project, built with FastAPI, SQLModel and Postgres (hosted on Neon).

## How money moves

Each account has a currency, a type (`user` or `system`) and an integer balance. Amounts are stored as integers, never floats.

The system account is how money enters and leaves the ledger. There is one per currency, it belongs to no user, and the API never lets anyone create, read, transfer from, or deposit into one directly.

- **Deposit:** debits the system account and credits the user's account.
- **Withdrawal:** debits the user's account and credits the system account.
- **Transfer:** debits one user account and credits another in the same currency. Transfers need an idempotency key, so a retried request returns the original transaction instead of moving money twice.

Because deposits come out of the system account, its balance goes negative as users are funded. That is expected: it mirrors the total money held by users.

Each of these writes a `transactions` row and two `ledger_entries` rows in one database commit. Accounts are locked with `SELECT ... FOR UPDATE` while they change, in a fixed order to avoid deadlocks.

## Authentication

There are two ways to authenticate:

- **JWT:** `POST /users/sign-in` returns a bearer token. It is used for managing your profile, accounts, deposits and withdrawals.
- **API key:** `POST /auth/generate-api-key` (with a JWT) returns a key like `sk_<environment>_...`. The plaintext is shown once and only a SHA-256 hash is stored. API keys are used for `POST /accounts/transfer` and `GET /accounts/check-balance`. Keys can be listed and revoked under `/auth/api-keys`.

## Endpoints

| Route | Auth | Purpose |
|---|---|---|
| `POST /users/sign-up` | none | create a user |
| `POST /users/sign-in` | none | get a JWT |
| `GET /users/me` | JWT | current user |
| `GET /users/list-users` | JWT | list users |
| `POST /accounts/create-account` | JWT | open an account (`user` type only) |
| `GET /accounts/list-accounts` | JWT | your accounts |
| `POST /accounts/{id}/deposit` | JWT | fund one of your accounts |
| `POST /accounts/{id}/withdraw` | JWT | withdraw from one of your accounts |
| `POST /accounts/transfer` | API key | move money to another account by account number |
| `GET /accounts/check-balance` | API key | balance of one of your accounts |
| `POST /auth/generate-api-key`, `GET /auth/api-keys`, `DELETE /auth/api-keys/{id}` | JWT | manage API keys |
| `POST /auth/verify-api-key` | API key | check that a key is valid |

Interactive docs are at `/docs` when the server is running.

The deposit route has no payment step behind it. Any signed-in user can mint funds into their own account. That is fine for manual testing, but it needs to be removed or restricted before real use.

## MCP server

`app/mcp_server.py` exposes the API to AI clients such as Claude over stdio. It is a thin client of the running API and authenticates with an API key, so ownership checks and idempotency are enforced by the API itself.

| Tool | What it does |
|---|---|
| `check_balance` | balance of one of your accounts; `account_id` can be omitted if you have exactly one |
| `transfer` | move money from one of your accounts to another account by account number |

`transfer` generates an idempotency key when none is given and returns it. To retry a failed or uncertain call, pass the same key again so the money moves only once.

To use it, start the API, create an API key with `POST /auth/generate-api-key`, then register the server with your client. For Claude Code:

```
claude mcp add ledger \
  -e LEDGER_API_KEY=sk_... \
  -e LEDGER_API_URL=http://127.0.0.1:8000 \
  -e PYTHONPATH=/path/to/ledger \
  -- /path/to/ledger/app/.venv/bin/python -m app.mcp_server
```

`LEDGER_API_URL` defaults to `http://127.0.0.1:8000`. The server needs the API running, and the key belongs to one user, so the tools only see that user's accounts. It can move real balances, so use a key for an account you are willing to test with.

## Layout

```
app/
  main.py                 FastAPI app and router wiring
  seed.py                 creates the system account(s)
  mcp_server.py           MCP server (stdio) for AI clients
  core/                   settings and database session
  modules/
    users/                sign-up, sign-in, JWT
    auth/                 API keys
    accounts/             accounts, transactions, deposit/withdraw/transfer
    ledger_entries/       debit and credit rows
migrations/               Alembic migrations
alembic.ini
```

## Running it

Run everything from the `ledger/` directory.

1. Create `app/.env.local` with `DATABASE_URL` (a `postgresql+psycopg://` URL) and `JWT_SECRET`.
2. Install dependencies with `pip install -r app/requirements.txt`.
3. Apply migrations and seed the system account:
   ```
   python -m alembic upgrade head
   python -m app.seed
   ```
4. Start the server:
   ```
   python -m uvicorn app.main:app --reload
   ```

The seed creates one system account, `SYSTEM-NGN`. To support another currency, add it to `SYSTEM_CURRENCIES` in `app/seed.py` and run the seed again. Deposits and withdrawals fail with "No system account found" for any currency without one.

## Migrations

The app does not create tables on startup. Schema changes go through Alembic.

After adding or changing a model:

1. Import its module in `migrations/env.py` so autogenerate can see it.
2. Generate a migration: `python -m alembic revision --autogenerate -m "describe the change"`.
3. Read the generated file in `migrations/versions/`. Autogenerate cannot tell a rename from a drop plus an add, and it adds NOT NULL columns without a default.
4. Apply it: `python -m alembic upgrade head`.

`python -m alembic check` reports whether the models and the database have drifted apart.
