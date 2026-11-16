import asyncio
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import update

from app.core.database import AsyncSessionLocal, engine
from app.core.redis import redis_client
from app.main import app
from app.models.pos import OutletStock

@pytest.mark.asyncio
async def test_prevent_overselling_in_pressure():
    #skenario : stok tersisa 3 unit, 10 kasir melakukan checkout 1 unit di detik bahkan milidetik yang sama
    #ekspektasi : 3 transaksi sukses (200/201), 7 ditolak (409) dan stok akhir 0 (bukan minus)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(OutletStock)
                .where(OutletStock.outlet_id == 1, OutletStock.product_id == 1)
                .values(quantity=3) 
            )
            await db.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login_res = await client.post(
                "/api/v1/auth/login",
                json={"username": "kasir1", "password": "password123"},
            )
            assert login_res.status_code == 200
            token = login_res.json()["access_token"]

            async def post_checkout_request():
                headers = {
                    "Idempotency-Key": f"test-race-{uuid.uuid4()}",
                    "Authorization": f"Bearer {token}",
                }
                payload = {
                    "outlet_id": 1,
                    "payment_method": "QRIS",
                    "items": [{"product_id": 1, "quantity": 1}],
                }
                return await client.post("/api/v1/checkout", json=payload, headers=headers)

            tasks = [post_checkout_request() for _ in range(10)]
            responses = await asyncio.gather(*tasks)

            status_codes = [r.status_code for r in responses]
            success_count = status_codes.count(200)
            conflict_count = status_codes.count(409)

            assert success_count == 3, f"aktual: {success_count} seharusnya 3 sukses"
            assert conflict_count == 7, f"aktual: {conflict_count} seharusnya 7 ditolak"
    finally:
        await redis_client.aclose()
        await engine.dispose()