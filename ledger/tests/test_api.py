import httpx
import pytest_asyncio

from app.main import app


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def sign_up_and_auth(client, name):
    body = {"name": name, "email": f"{name}@example.com", "password": "pw-12345"}
    assert (await client.post("/users/sign-up", json=body)).status_code == 201
    token = (await client.post("/users/sign-in", json=body)).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_deposit_requires_idempotency_key(client):
    headers = await sign_up_and_auth(client, "carol")
    acct = (
        await client.post(
            "/accounts/create-account",
            json={"accountNumber": "C-1", "currency": "NGN"},
            headers=headers,
        )
    ).json()
    r = await client.post(f"/accounts/{acct['id']}/deposit", json={"amount": 100}, headers=headers)
    assert r.status_code == 422


async def test_deposit_and_withdraw_retries_are_deduplicated(client):
    headers = await sign_up_and_auth(client, "dave")
    acct = (
        await client.post(
            "/accounts/create-account",
            json={"accountNumber": "D-1", "currency": "NGN"},
            headers=headers,
        )
    ).json()
    url = f"/accounts/{acct['id']}"
    dep = {"amount": 500, "idempotency_key": "dep-1"}
    assert (await client.post(f"{url}/deposit", json=dep, headers=headers)).json()["balance"] == 500
    assert (await client.post(f"{url}/deposit", json=dep, headers=headers)).json()["balance"] == 500

    wd = {"amount": 200, "idempotency_key": "wd-1"}
    assert (await client.post(f"{url}/withdraw", json=wd, headers=headers)).json()["balance"] == 300
    assert (await client.post(f"{url}/withdraw", json=wd, headers=headers)).json()["balance"] == 300

    clash = await client.post(
        f"{url}/deposit", json={"amount": 1, "idempotency_key": "dep-1"}, headers=headers
    )
    assert clash.status_code == 400
