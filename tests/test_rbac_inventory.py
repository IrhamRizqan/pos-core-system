import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal, engine
from app.core.redis import redis_client
from app.main import app, seed_initial_data
from app.models.pos import MutationType, OutletStock, StockLedger


@pytest_asyncio.fixture(autouse=True)
async def setup_and_teardown_db():
    await seed_initial_data()
    yield
    await redis_client.aclose()
    await engine.dispose()


async def _get_token(client: AsyncClient, username: str, password: str) -> str:
    res = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert res.status_code == 200
    return res.json()["access_token"]


@pytest.mark.asyncio
async def test_cashier_forbidden_from_restock_and_void():
    #skenario RBAC akun cashier mencoba akses endpoint restock dan void transaksi
    #expect kedua request di tolak dengan 403
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cashier_token = await _get_token(client, "kasir1", "password123")
        headers = {"Authorization": f"Bearer {cashier_token}"}

        restock_res = await client.post(
            "/api/v1/inventory/restock",
            json={"outlet_id": 1, "product_id": 1, "quantity": 10},
            headers=headers,
        )
        assert restock_res.status_code == 403

        void_res = await client.post(
            "/api/v1/checkout/INV-1-DUMMY001/void",
            headers=headers,
        )
        assert void_res.status_code == 403

@pytest.mark.asyncio
async def test_manager_cross_outlet_isolation():
    #skenario multi-outlet, manager cabang 1 mencoba restock cabang lain
    #expect request di tolak dengan 403
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        manager_token = await _get_token(client, "manager1", "password123")
        headers = {"Authorization": f"Bearer {manager_token}"}

        res = await client.post(
            "/api/v1/inventory/restock",
            json={"outlet_id": 999, "product_id": 1, "quantity": 5},
            headers=headers,
        )
        assert res.status_code == 403

@pytest.mark.asyncio
async def test_manager_restock_and_void_flow_with_ledger():
    #skenario end to end, reset stok ke 5, manager restock +10, kasir checkout 2 unit, manager void pada invoice tersebut dan manager coba void ulang dengan expect 409
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutletStock)
            .where(OutletStock.outlet_id == 1, OutletStock.product_id == 1)
            .values(quantity=5)
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        manager_token = await _get_token(client, "manager1", "password123")
        cashier_token = await _get_token(client, "kasir1", "password123")

        manager_headers = {"Authorization": f"Bearer {manager_token}"}

        # 1.manager restock +10
        restock_res = await client.post(
            "/api/v1/inventory/restock",
            json={
                "outlet_id": 1,
                "product_id": 1,
                "quantity": 10,
                "reference_note": "PO-SUPPLIER-01",
            },
            headers=manager_headers,
        )
        assert restock_res.status_code == 200
        assert restock_res.json()["current_stock"] == 15

        # 2.kasir checkout 2 unit
        checkout_res = await client.post(
            "/api/v1/checkout",
            json={
                "outlet_id": 1,
                "payment_method": "CASH",
                "items": [{"product_id": 1, "quantity": 2}],
            },
            headers={
                "Authorization": f"Bearer {cashier_token}",
                "Idempotency-Key": f"test-void-{uuid.uuid4()}",
            },
        )
        assert checkout_res.status_code == 200
        invoice_number = checkout_res.json()["invoice_number"]

        # 3.manager void transaksi ini
        void_res = await client.post(
            f"/api/v1/checkout/{invoice_number}/void",
            headers=manager_headers,
        )
        assert void_res.status_code == 200
        void_data = void_res.json()
        assert void_data["status"] == "VOIDED"
        assert void_data["restored_items"][0]["balance_after"] == 15

        # 4.cegah double void
        duplicate_void_res = await client.post(
            f"/api/v1/checkout/{invoice_number}/void",
            headers=manager_headers,
        )
        assert duplicate_void_res.status_code == 409

    # 5.verifikasi audit trail di StockLedger mencatat VOID
    async with AsyncSessionLocal() as db:
        ledger_stmt = select(StockLedger).where(
            StockLedger.reference_code == f"VOID-{invoice_number}"
        )
        void_ledger = (await db.execute(ledger_stmt)).scalar_one_or_none()
        assert void_ledger is not None
        assert void_ledger.mutation_type == MutationType.VOID
        assert void_ledger.change_qty == 2
        assert void_ledger.balance_after == 15