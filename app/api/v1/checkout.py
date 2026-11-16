from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.redis import get_redis
from app.core.security import require_roles
from app.models.pos import User, UserRole
from app.schemas.checkout import CheckoutRequest
from app.services.checkout_service import process_checkout, void_order

router = APIRouter(prefix="/checkout", tags=["Checkout"])

@router.post("")
async def create_checkout(
    payload:CheckoutRequest,
    idempotency_key:str = Header(..., alias="Idempotency-Key"),
    db:AsyncSession = Depends(get_db),
    redis:Redis = Depends(get_redis),
    current_user:User = Depends(require_roles(UserRole.CASHIER, UserRole.MANAGER, UserRole.OWNER)),
):
    if current_user.role != UserRole.OWNER and current_user.outlet_id != payload.outlet_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Anda '{current_user.role.value}' tidak memiliki akses transaksi untuk cabang ini",
        )
    
    items_dict= [item.model_dump() for item in payload.items]
    return await process_checkout(
        db=db,
        redis=redis,
        outlet_id=payload.outlet_id,
        cashier_id=current_user.id,
        idempotency_key=idempotency_key,
        payment_method=payload.payment_method,
        items=items_dict,
    )

@router.post("/{invoice_number}/void")
async def void_checkout_transaction(
    invoice_number:str,
    db:AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: User = Depends(require_roles(UserRole.MANAGER, UserRole.OWNER)),
):
    return await void_order(
        db=db,
        redis=redis,
        invoice_number=invoice_number,
        user_role=current_user.role,
        user_outlet_id=current_user.outlet_id,
    )