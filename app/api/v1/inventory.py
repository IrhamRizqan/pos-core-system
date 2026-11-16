from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import require_roles
from app.models.pos import User, UserRole
from app.schemas.checkout import RestockRequest, StockOpnameRequest
from app.services.inventory_service import restock_inventory, perform_stock_opname

router = APIRouter(prefix="/inventory", tags=["Inventory"])

@router.post("/restock")
async def create_restock(
    payload:RestockRequest,
    db:AsyncSession = Depends(get_db),
    redis:Redis = Depends(get_redis),
    current_user: User = Depends(require_roles(UserRole.MANAGER, UserRole.OWNER)),
):
    if current_user.role != UserRole.OWNER and current_user.outlet_id != payload.outlet_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses restock untuk cabang ini",
        )

    return await restock_inventory(
        db=db,
        redis=redis,
        outlet_id=payload.outlet_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        reference_note=payload.reference_note,
    )

@router.post("/stock-opname")
async def create_stock_opname(
    payload:StockOpnameRequest,
    db:AsyncSession = Depends(get_db),
    redis:Redis = Depends(get_redis),
    current_user:User = Depends(require_roles(UserRole.MANAGER, UserRole.OWNER))
):
    if current_user.role != UserRole.OWNER and current_user.outlet_id != payload.outlet_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses stock opname untuk cabang ini",
        )
    
    return await perform_stock_opname(
        db=db,
        redis=redis,
        outlet_id=payload.outlet_id,
        product_id=payload.product_id,
        actual_stock=payload.actual_stock,
        reason=payload.reason,
    )