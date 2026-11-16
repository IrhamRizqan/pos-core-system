from app.schemas.checkout import ProductCatalogItem
from fastapi import HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pos import MutationType, Outlet, OutletStock, Product, StockLedger

async def restock_inventory(
    db:AsyncSession,
    redis:Redis,
    outlet_id:int,
    product_id:int,
    quantity:int,
    reference_note:str,
)-> dict:
        try:
            outlet = await db.get(Outlet, outlet_id)
            if not outlet:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Outlet tidak ditemukan!",
                )
            
            product = await db.get(Product, product_id)
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Produk tidak ditemukan"
                )
            
            stock_stmt=(
                select(OutletStock)
                .where(
                    OutletStock.outlet_id == outlet_id,
                    OutletStock.product_id == product_id,
                )
                .with_for_update()
            )
            stock_row = (await db.execute(stock_stmt)).scalar_one_or_none()

            if not stock_row:
                stock_row = OutletStock(outlet_id=outlet_id, product_id=product_id, quantity=0)
                db.add(stock_row)
                await db.flush()
            
            stock_row.quantity += quantity

            ledger = StockLedger(
                outlet_id = outlet_id,
                product_id = product_id,
                mutation_type=MutationType.RESTOCK,
                change_qty = quantity,
                balance_after = stock_row.quantity,
                reference_code=reference_note,
            )
            db.add(ledger)

            await db.commit()
        
        except Exception:
            await db.rollback()
            raise
        
        await redis.delete(f"catalog:outlet:{outlet_id}")

        return{
            "status": "RESTOCKED",
            "outlet_id": outlet_id,
            "product_id": product_id,
            "product_name": product.name,
            "added_quantity": quantity,
            "current_stock": stock_row.quantity,
            "reference_code": reference_note,
        }

async def perform_stock_opname(
    db:AsyncSession,
    redis:Redis,
    outlet_id:int,
    product_id:int,
    actual_stock:int,
    reason:str,
)->dict:
    try:
        product = await db.get(Product, product_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Produk tidak ditemukan",
            )
        
        stock_stmt=(
            select(OutletStock)
            .where(
                OutletStock.outlet_id == outlet_id,
                OutletStock.product_id == product_id,
            )
            .with_for_update()
        )
        stock_stmt=(
            select(OutletStock)
            .where(
                OutletStock.outlet_id == outlet_id,
                OutletStock.product_id == product_id,
            )
            .with_for_update()
        )
        stock_row = (await db.execute(stock_stmt)).scalar_one_or_none()

        if not stock_row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Data stok produk di cabang ini belum terdaftar",
            )
        
        system_stock = stock_row.quantity
        discrepancy = actual_stock - system_stock

        if discrepancy == 0:
            await db.commit()
            return{
                "status":"MATCHED",
                "outlet_id":outlet_id,
                "product_id":product_id,
                "product_name":product.name,
                "system_stock":system_stock,
                "actual_stock":actual_stock,
                "discrepancy":0,
            }
        
        stock_row.quantity = actual_stock
        clean_reason = reason.strip().upper().replace(" ", "-")
        ref_code = f"OPNAME-{clean_reason}"[:64]

        ledger = StockLedger(
            outlet_id=outlet_id,
            product_id=product_id,
            mutation_type=MutationType.ADJUSTMENT,
            change_qty=discrepancy,
            balance_after=actual_stock,
            reference_code=ref_code,
        )
        db.add(ledger)
        await db.commit()

    except Exception:
        await db.rollback()
        raise

    await redis.delete(f"catalog:outlet:{outlet_id}")

    return{
        "status": "ADJUSTED",
        "outlet_id": outlet_id,
        "product_id": product_id,
        "product_name": product.name,
        "system_stock": system_stock,
        "actual_stock": actual_stock,
        "discrepancy": discrepancy,
        "reference_code": ref_code,
    }