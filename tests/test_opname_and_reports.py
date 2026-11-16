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
async def setup_and_teardown():
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
async def test_cashier_forbidden_from_opname_and_reports():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cashier_token = await _get_token(client, "kasir1", "password123")
        headers = {"Authorization": f"Bearer {cashier_token}"}

        opname_res = await client.post(
            "/api/v1/inventory/stock-opname",
            json={"outlet_id": 1, "product_id": 1, "actual_stock": 5, "reason": "TEST"},
            headers=headers,
        )
        assert opname_res.status_code == 403

        report_res = await client.get(
            "/api/v1/reports/daily-summary?outlet_id=1",
            headers=headers,
        )
        assert report_res.status_code == 403


@pytest.mark.asyncio
async def test_stock_opname_records_adjustment_ledger():
    """
    Skenario: Stok di sistem tercatat 10 unit, namun hasil hitung fisik hanya 7 unit
    (3 unit rusak). Sistem harus mencatat selisih -3 ke StockLedger sebagai ADJUSTMENT.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutletStock)
            .where(OutletStock.outlet_id == 1, OutletStock.product_id == 1)
            .values(quantity=10)
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        manager_token = await _get_token(client, "manager1", "password123")
        headers = {"Authorization": f"Bearer {manager_token}"}

        res = await client.post(
            "/api/v1/inventory/stock-opname",
            json={
                "outlet_id": 1,
                "product_id": 1,
                "actual_stock": 7,
                "reason": "KEMASAN-RUSAK",
            },
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ADJUSTED"
        assert data["system_stock"] == 10
        assert data["actual_stock"] == 7
        assert data["discrepancy"] == -3

    async with AsyncSessionLocal() as db:
        stmt = (
            select(StockLedger)
            .where(StockLedger.reference_code == "OPNAME-KEMASAN-RUSAK")
            .order_by(StockLedger.id.desc())
        )
        ledger = (await db.execute(stmt)).scalars().first()
        assert ledger is not None
        assert ledger.mutation_type == MutationType.ADJUSTMENT
        assert ledger.change_qty == -3
        assert ledger.balance_after == 7


@pytest.mark.asyncio
async def test_daily_shift_summary_report():
    """
    Skenario: Kasir melakukan transaksi QRIS dan CASH, lalu Manager me-void salah satunya.
    Laporan harian harus memisahkan omzet bersih per metode pembayaran dan total void.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(OutletStock)
            .where(OutletStock.outlet_id == 1, OutletStock.product_id == 1)
            .values(quantity=20)
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cashier_token = await _get_token(client, "kasir1", "password123")
        manager_token = await _get_token(client, "manager1", "password123")

        # 1. Transaksi QRIS (sukses)
        res_qris = await client.post(
            "/api/v1/checkout",
            json={
                "outlet_id": 1,
                "payment_method": "QRIS",
                "items": [{"product_id": 1, "quantity": 1}],
            },
            headers={
                "Authorization": f"Bearer {cashier_token}",
                "Idempotency-Key": f"rep-qris-{uuid.uuid4()}",
            },
        )
        assert res_qris.status_code == 200

        # 2. Transaksi CASH (akan di-void)
        res_cash = await client.post(
            "/api/v1/checkout",
            json={
                "outlet_id": 1,
                "payment_method": "CASH",
                "items": [{"product_id": 1, "quantity": 1}],
            },
            headers={
                "Authorization": f"Bearer {cashier_token}",
                "Idempotency-Key": f"rep-cash-{uuid.uuid4()}",
            },
        )
        assert res_cash.status_code == 200
        void_invoice = res_cash.json()["invoice_number"]

        # 3. Manager void transaksi CASH
        void_res = await client.post(
            f"/api/v1/checkout/{void_invoice}/void",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert void_res.status_code == 200

        # 4. Tarik laporan tutup kasir hari ini
        report_res = await client.get(
            "/api/v1/reports/daily-summary?outlet_id=1",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
        assert report_res.status_code == 200
        report = report_res.json()
        assert report["summary"]["completed_transactions"] >= 1
        assert report["summary"]["voided_transactions"] >= 1
        assert "QRIS" in report["payment_breakdown"]