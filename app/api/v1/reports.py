from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BeforeValidator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import require_roles
from app.models.pos import Order, OrderStatus, Outlet, User, UserRole

router = APIRouter(prefix="/reports", tags=["Reports"])

def parse_indonesian_date(value:str | date | None)-> date| None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    
    raise ValueError("Format tanggal tidak valid. gunakan DD-MM-YYYY Contoh: (01-11-2021)")

FlexibleDate = Annotated[date | None, BeforeValidator(parse_indonesian_date)]

@router.get("/daily-summary")
async def get_daily_shift_summary(
    outlet_id:int = Query(..., description="ID cabang yang akan direkap"),
    report_date:FlexibleDate = Query(
        default=None,
        description="Format DD-MM-YYYY (contoh: 01-11-2021), kosongkan untuk hari ini",
        examples=["01-11-2021"],
    ),
    db:AsyncSession = Depends(get_db),
    current_user:User = Depends(require_roles(UserRole.MANAGER, UserRole.OWNER)),
):
    if current_user.role != UserRole.OWNER and current_user.outlet_id != outlet_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Anda tidak memiliki akses laporan untuk cabang ini",
        )
    
    outlet = await db.get(Outlet, outlet_id)
    if not outlet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outlet tidak ditemukan",
        )
    
    target_date = report_date or (await db.execute(select(func.current_date()))).scalar_one()

    completed_stmt=(
        select(
            Order.payment_method,
            func.count(Order.id).label("tx_count"),
            func.coalesce(func.sum(Order.total_amount), Decimal("0.00")).label("subtotal"),
        )
        .where(
            Order.outlet_id == outlet_id,
            Order.status == OrderStatus.COMPLETED,
            func.date(Order.created_at) == target_date,
        )
        .group_by(Order.payment_method)
    )
    completed_rows = (await db.execute(completed_stmt)).all()

    payment_breakdown = {}
    total_completed_tx = 0
    net_revenue = Decimal("0.00")

    for method, tx_count, subtotal in completed_rows:
        payment_breakdown[method] = {
            "transaction_count": tx_count,
            "total_amount": str(subtotal),
        }
        total_completed_tx += tx_count
        net_revenue += subtotal
    
    voided_stmt = select(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total_amount), Decimal("0.00")),
    ).where(
        Order.outlet_id == outlet_id,
        Order.status == OrderStatus.VOIDED,
        func.date(Order.created_at) == target_date,
    )
    voided_count, voided_amount = (await db.execute(voided_stmt)).one()

    return{
        "outlet_id": outlet.id,
        "outlet_name": outlet.name,
        "report_date": str(target_date),
        "summary": {
            "completed_transactions": total_completed_tx,
            "net_revenue": str(net_revenue),
            "voided_transactions": voided_count,
            "voided_amount": str(voided_amount),
        },
        "payment_breakdown": payment_breakdown,
    }