from redis import UsernamePasswordCredentialProvider
import uuid
from decimal import Decimal
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from app.models.pos import (UserRole, Product, OutletStock, StockLedger, Order, OrderItem, OrderStatus, IdempotencyKey, MutationType)

async def process_checkout(
    db: AsyncSession,
    redis: Redis,
    outlet_id: int,
    cashier_id: int,
    idempotency_key: str,
    payment_method: str,
    items: list[dict],
) -> dict:
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Keranjang Belanja Tidak Boleh Kosong"
            )
        
        existing_idem = await db.get(IdempotencyKey, idempotency_key)
        if existing_idem:
            return existing_idem.response_payload
        
        sorted_items = sorted(items, key=lambda x: x["product_id"])
        product_ids = [item["product_id"] for item in sorted_items]

        try:
            existing_idem_tx = await db.get(IdempotencyKey,idempotency_key)
            if existing_idem_tx:
                return existing_idem_tx.response_payload
            
            prod_stmt = select(Product).where(Product.id.in_(product_ids))
            products = {p.id: p for p in (await db.execute(prod_stmt)).scalars().all()}

            if len(products) != len(product_ids):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Produk Tidak Ditemukan Di Keranjang"
                )
            
            stock_stmt = (
                select(OutletStock).where(
                    OutletStock.outlet_id == outlet_id,
                    OutletStock.product_id.in_(product_ids),
                ).order_by(OutletStock.product_id).with_for_update()
            )

            stocks = {s.product_id: s for s in (await db.execute(stock_stmt)).scalars().all()}

            total_amount = Decimal("0.00")
            invoice_number = f"INV-{outlet_id}-{uuid.uuid4().hex[:8].upper()}"

            order = Order(
                invoice_number=invoice_number,
                outlet_id=outlet_id,
                cashier_id=cashier_id,
                total_amount=Decimal("0.00"),
                payment_method=payment_method,
            )
            db.add(order)
            await db.flush() #get order.id tanpa commit tx

            receipt_items = []

            for item in sorted_items:
                pid = item["product_id"]
                qty = item["quantity"]
                stock_row = stocks.get(pid)
                product = products[pid]

                if not stock_row or stock_row.quantity < qty:
                    available = stock_row.quantity if stock_row else 0
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Stok '{product.name}' tidak mencukupi! (sisa: {available}, diminta: {qty})"
                    )
                
                stock_row.quantity -= qty

                ledger = StockLedger(
                    outlet_id=outlet_id,
                    product_id=pid,
                    mutation_type=MutationType.SALE,
                    change_qty=-qty,
                    balance_after=stock_row.quantity,
                    reference_code=invoice_number,
                )
                db.add(ledger)

                subtotal = product.price * qty
                total_amount += subtotal

                order_item = OrderItem(
                    order_id=order.id,
                    product_id=pid,
                    quantity=qty,
                    unit_price=product.price,
                    subtotal=subtotal,
                )
                db.add(order_item)

                receipt_items.append({
                    "product_id": pid,
                    "name": product.name,
                    "quantity": qty,
                    "unit_price": str(product.price),
                    "subtotal": str(subtotal),
                })

            order.total_amount = total_amount

            response_payload={
                "status": "SUCCESS",
                "invoice_number": invoice_number,
                "outlet_id": outlet_id,
                "total_amount": str(total_amount),
                "payment_method": payment_method,
                "items": receipt_items,
            }
            
            db.add(
                IdempotencyKey(
                    key=idempotency_key,
                    outlet_id=outlet_id,
                    response_payload=response_payload,
                )
            )

            await db.commit()
        except Exception:
            await db.rollback()
            raise
        
        await redis.delete(f"catalog:outlet:{outlet_id}")
        return response_payload

async def void_order(
    db:AsyncSession,
    redis:Redis,
    invoice_number:str,
    user_role: UserRole,
    user_outlet_id:int,
) -> dict:
        try:
            order_stmt=(
                select(Order)
                .where(Order.invoice_number == invoice_number)
                .with_for_update()
            )
            order = (await db.execute(order_stmt)).scalar_one_or_none()

            if not order:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Invoice '{invoice_number}' tidak ditemukan",
                )
            
            if user_role != UserRole.OWNER and user_outlet_id != order.outlet_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Anda tidak memiliki akses untuk membatalkan transaksi cabang lain"
                )
            
            if order.status == OrderStatus.VOIDED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Transaksi '{invoice_number}' sudah dibatalkan",
                )
            
            items_stmt=(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.product_id)
            )
            order_items = (await db.execute(items_stmt)).scalars().all()
            product_ids = [item.product_id for item in order_items]

            stock_stmt=(
                select(OutletStock)
                .where(
                    OutletStock.outlet_id == order.outlet_id,
                    OutletStock.product_id.in_(product_ids),
                )
                .order_by(OutletStock.product_id)
                .with_for_update()
            )
            stocks = {s.product_id: s for s in (await db.execute(stock_stmt)).scalars().all()}

            restored_items = []
            for item in order_items:
                stock_row = stocks[item.product_id]
                stock_row.quantity += item.quantity

                ledger = StockLedger(
                    outlet_id=order.outlet_id,
                    product_id=item.product_id,
                    mutation_type=MutationType.VOID,
                    change_qty=item.quantity,
                    balance_after=stock_row.quantity,
                    reference_code=f"VOID-{order.invoice_number}",
                )
                db.add(ledger)

                restored_items.append({
                    "product_id":item.product_id,
                    "restored_quantity":item.quantity,
                    "balance_after":stock_row.quantity,
                })
            
            order.status = OrderStatus.VOIDED
            await db.commit()

        except Exception:
            await db.rollback()
            raise
        
        await redis.delete(f"catalog:outlet:{order.outlet_id}")

        return{
            "status": "VOIDED",
            "invoice_number": order.invoice_number,
            "outlet_id": order.outlet_id,
            "refunded_amount": str(order.total_amount),
            "restored_items": restored_items,
        }