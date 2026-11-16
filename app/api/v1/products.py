from app.schemas.checkout import ProductCatalogItem
from redis.cache import CacheInterface
import json
from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import get_current_user
from app.models.pos import OutletStock, Product, User

router = APIRouter(prefix="/products", tags=["Catalog"])

@router.get("/outlet/{outlet_id}")
async def get_outlet_catalog(
    outlet_id:int,
    db:AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    _: User = Depends(get_current_user),
):
    cache_key = f"catalog:outlet:{outlet_id}"

    cached_data = await redis.get(cache_key)
    if cached_data:
        return {"Source": "redis_cache", "data": json.loads(cached_data)}

    stmt = (
        select(Product.id, Product.sku, Product.name, Product.price, OutletStock.quantity)
        .join(OutletStock, Product.id == OutletStock.product_id)
        .where(OutletStock.outlet_id == outlet_id)
    )
    rows = (await db.execute(stmt)).all()

    catalog = [{
        "id": r.id,
        "sku": r.sku,
        "name": r.name,
        "price": str(r.price),
        "stock": r.quantity,
    } for r in rows ]

    await redis.setex(cache_key, 300, json.dumps(catalog))
    return {"source": "database", "data":catalog}