from contextlib import asynccontextmanager
from decimal import Decimal
from fastapi import FastAPI
from sqlalchemy import select

from app.api.v1 import auth, checkout, products, inventory
from app.core.database import AsyncSessionLocal, engine
from app.core.redis import redis_client
from app.core.security import hash_password
from app.models.pos import Base, Outlet, OutletStock, Product, User, UserRole

async def seed_initial_data():
    #otomatis mengisi data awal
    async with AsyncSessionLocal() as db:
        outlet = (await db.execute(select(Outlet))).scalar_one_or_none()
        if not outlet:
            outlet = Outlet(name="Cabang Utama Dago", address="Jl. Ir. H. Juanda, Bandung")
            db.add(outlet)
            await db.flush()

            cashier = User(
                username="kasir1",
                hashed_password=hash_password("password123"),
                role=UserRole.CASHIER,
                outlet_id=outlet.id,
            )
            product = Product(sku="KOPI-001", name="Es Kopi Susu", price=Decimal("26000.00"))
            db.add_all([cashier, product])
            await db.flush()

            stock = OutletStock(outlet_id=outlet.id, product_id=product.id, quantity=3)
            db.add(stock)

        existing_manager = (
            await db.execute(select(User).where(User.username == "manager1"))
        ).scalar_one_or_none()
        if not existing_manager:
            manager = User(
                username="manager1",
                hashed_password=hash_password("password123"),
                role=UserRole.MANAGER,
                outlet_id=outlet.id,
            )
            db.add(manager)
        await db.commit()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as con:
        await con.run_sync(Base.metadata.create_all)
    await seed_initial_data()
    yield
    await redis_client.aclose()
    await engine.dispose()

app = FastAPI(
    title="POS Core Engine API",
    description="High Concurrency multi outlet POS Backend with Pessimistic Looking and Idempotency",
    version="1.0",
    lifespan=lifespan
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(products.router, prefix="/api/v1")
app.include_router(checkout.router, prefix="/api/v1")
app.include_router(inventory.router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}