# Ledger MCP

A small money-movement system with an MCP server on top, so an AI client can check balances and make transfers on a user's behalf. It is a learning project.

It has two services:

- `ledger/` is the API. It owns users, accounts, balances and the double-entry ledger. Built with FastAPI, SQLModel and Postgres (hosted on Neon).
- `mcp-server/` is the MCP server. It exposes two tools to AI clients and calls the API for everything. It holds no data and makes no decisions about who owns what.

```
AI client  --(MCP over HTTP, Authorization: Bearer sk_...)-->  mcp-server  --(same header)-->  ledger API  -->  Postgres
```

The client's `Authorization` header is forwarded unchanged to the API, which resolves it to a user. The MCP server never sees a password and never picks the user. Account ownership, idempotency and balance checks all happen in the API.

## How money moves

Each account has a currency, a type (`user` or `system`) and an integer balance. Amounts are stored as integers, never floats. The MCP tools call them cents.

The system account is how money enters and leaves the ledger. There is one per currency, it belongs to no user, and the API never lets anyone create, read, transfer from, or deposit into one directly.

- Deposit: debits the system account and credits the user's account.
- Withdrawal: debits the user's account and credits the system account.
- Transfer: debits one user account and credits another in the same currency.

Deposits, withdrawals and transfers all take an `idempotency_key`. Keys are scoped to the signed-in user, so two users can use the same string. Retrying with the same key and the same parameters returns the original result instead of moving money twice. Reusing a key with different parameters is rejected with a 400.

Because deposits come out of the system account, its balance goes negative as users are funded. That is expected: it mirrors the total money held by users.

Each of these writes a `transactions` row and two `ledger_entries` rows in one database commit. Accounts are locked with `SELECT ... FOR UPDATE` while they change, in a fixed order to avoid deadlocks. Across the whole table, credits minus debits must be zero.

The database enforces the key rules itself, not just the application:

- `accounts.balance` cannot go negative, except on system accounts.
- `transactions.amount` and `ledger_entries.amount` must be positive.
- `ledger_entries` and `transactions` are append-only. A trigger rejects `UPDATE`, `DELETE` and `TRUNCATE` on them, so a mistake has to be fixed by posting a new transaction. This stops application bugs and ad-hoc SQL by mistake. A role that owns the tables can still drop the trigger, so run the app as a role that does not own them if you need protection from the app's own credentials.

## Authentication

- JWT: `POST /users/sign-in` (or `POST /users/token`, which Swagger's Authorize button uses) returns a bearer token. It is used for managing your profile, accounts, deposits and withdrawals.
- API key: `POST /auth/generate-api-key` (with a JWT) returns a key like `sk_<environment>_...`, where the environment is `test` or `live`. The plaintext is shown once and only a SHA-256 hash is stored. API keys are what the transfer and balance routes accept, and so what the MCP server uses. Keys can be listed and revoked under `/auth/api-keys`.

## API endpoints

| Route | Auth | Purpose |
|---|---|---|
| `POST /users/sign-up` | none | create a user |
| `POST /users/sign-in` | none | get a JWT (JSON body) |
| `POST /users/token` | none | get a JWT (form body, for Swagger) |
| `GET /users/me` | JWT | current user |
| `GET /users/list-users` | JWT | list users |
| `POST /accounts/create-account` | JWT | open an account (`user` type only) |
| `GET /accounts/list-accounts` | JWT | your accounts |
| `POST /accounts/{id}/deposit` | JWT | fund one of your accounts (`amount`, `idempotency_key`) |
| `POST /accounts/{id}/withdraw` | JWT | withdraw from one of your accounts (`amount`, `idempotency_key`) |
| `POST /accounts/transfer` | API key | move money to another account by account number |
| `GET /accounts/check-balance` | API key | balance of one of your accounts |
| `POST /auth/generate-api-key`, `GET /auth/api-keys`, `DELETE /auth/api-keys/{id}` | JWT | manage API keys |
| `POST /auth/verify-api-key` | API key | check that a key is valid |

Interactive docs are at `/docs` when the API is running.

The deposit route has no payment step behind it. Any signed-in user can mint funds into their own account. That is fine for manual testing, but it needs to be removed or restricted before real use.

## MCP tools

| Tool | What it does |
|---|---|
| `check_balance(account_id?)` | balance of one of your accounts; `account_id` can be omitted if you have exactly one |
| `transfer_funds(from_account_id, receiver_account_number, amount_cents)` | move money from one of your accounts to another account by account number |

The MCP server applies its own transfer ceiling before it calls the API. `MCP_TRANSFER_LIMIT_CENTS` sets it and defaults to 10000. A transfer above it is refused without reaching the API. The server generates a fresh idempotency key for each tool call.

Errors come back as `{"error": "..."}` with the API's reason, such as `Insufficient funds` or `Account not found`.

## Layout

```
ledger/
  alembic.ini
  migrations/             Alembic migrations
  app/
    main.py               FastAPI app and router wiring
    seed.py               creates the system account(s)
    core/                 settings and database session
    modules/
      users/              sign-up, sign-in, JWT
      auth/               API keys
      accounts/           accounts, transactions, deposit/withdraw/transfer
      ledger_entries/     debit and credit rows
mcp-server/
  server.py               FastMCP server (streamable HTTP, port 8080)
  test.py                 small client that calls check_balance
```

## Running the API

Run these from `ledger/`.

1. Create `ledger/app/.env.local` with `DATABASE_URL` (a `postgresql+psycopg://` URL) and `JWT_SECRET`.
2. Install dependencies: `pip install -r app/requirements.txt`.
3. Apply migrations and seed the system account:
   ```
   python -m alembic upgrade head
   python -m app.seed
   ```
4. Start the API on port 8000:
   ```
   python -m uvicorn app.main:app --reload
   ```

The seed creates one system account, `SYSTEM-NGN`. To support another currency, add it to `SYSTEM_CURRENCIES` in `app/seed.py` and run the seed again. Deposits and withdrawals fail with "No system account found" for any currency without one.

## Running the MCP server

Run these from `mcp-server/`, with the API already running.

```
pip install -r requirements.txt
python server.py
```

The server listens on `http://0.0.0.0:8080/mcp` and calls the API at `http://localhost:8000` (the `LEDGER_API_BASE` constant in `server.py`).

To connect Claude Code:

1. Sign in through the API's `/docs` and call `POST /auth/generate-api-key` to get an `sk_test_...` key.
2. Register the server:
   ```
   claude mcp add --transport http ledger http://localhost:8080/mcp \
     --header "Authorization: Bearer sk_test_..."
   ```
3. Run `/mcp` in Claude Code to confirm it is connected, then ask for your balance or a transfer.

The key belongs to one user, so the tools only reach that user's accounts. They move real balances, so use test accounts.

`test.py` is a minimal client for the same thing. Put an API key in `YOUR_API_TOKEN`; the balance route does not accept a JWT.

## Tests

Run these from `ledger/`. The tests rebuild the schema with the real migrations and then `TRUNCATE` every table, so they need their own empty Postgres database. The name must contain `test`, and they never read `DATABASE_URL` from `.env.local`.

```
createdb ledger_test
TEST_DATABASE_URL=postgresql+psycopg://localhost/ledger_test python -m pytest
```

Without `TEST_DATABASE_URL` every test is skipped. They cover idempotency (replays, mismatched reuse, per-user scoping, concurrent duplicates), ledger invariants (balances net to zero, debits equal credits, balances match posted entries), the deposit/withdraw API, and a check that the models match the migrated schema.

CI (`.github/workflows/ci.yml`) runs the same suite against a Postgres service container.

## Migrations

The API does not create tables on startup. Schema changes go through Alembic.

After adding or changing a model:

1. Import its module in `ledger/migrations/env.py` so autogenerate can see it.
2. Generate a migration: `python -m alembic revision --autogenerate -m "describe the change"`.
3. Read the generated file in `ledger/migrations/versions/`. Autogenerate cannot tell a rename from a drop plus an add, and it adds NOT NULL columns without a default.
4. Apply it: `python -m alembic upgrade head`.

`python -m alembic check` reports whether the models and the database have drifted apart.

## Known gaps

- A retried MCP transfer is a new transfer. The MCP server makes a new idempotency key on every call, so only retries inside the API are deduplicated.
- `mcp-server/test.py` contains a hard-coded JWT, and that file is in git history. It should read the key from an environment variable instead.
- The MCP server binds to `0.0.0.0` and has no TLS. Anyone who can reach port 8080 can try keys against it.
