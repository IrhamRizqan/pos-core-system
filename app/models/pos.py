from email.policy import default
import enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import(String, Integer, Numeric, ForeignKey, DateTime, Enum, JSON, UniqueConstraint, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class UserRole(str, enum.Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    CASHIER = "CASHIER"

class MutationType(str, enum.Enum):
    SALE = "SALE"
    RESTOCK = "RESTOCK"
    ADJUSTMENT = "ADJUSTMENT"
    VOID = "VOID"

class Outlet(Base):
    __tablename__ = "outlets"

    id:Mapped[int] = mapped_column(primary_key=True)
    name:Mapped[str] = mapped_column(String(100), nullable=False)
    address:Mapped[str] = mapped_column(String(255), nullable=True)

class User(Base):
    __tablename__ = "users"

    id:Mapped[int] = mapped_column(primary_key=True)
    username:Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    hashed_password:Mapped[str] = mapped_column(String(255), nullable=False)
    role:Mapped[str] = mapped_column(Enum(UserRole), nullable=False)
    outlet_id:Mapped[int] = mapped_column(ForeignKey("outlets.id"), nullable=False)

class Product(Base):
    __tablename__ = "products"

    id:Mapped[int] = mapped_column(primary_key=True)
    sku:Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name:Mapped[str] = mapped_column(String(150), nullable=False)
    price:Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

class OutletStock(Base):
    __tablename__ = "outlet_stocks"
    __table_args__ = (UniqueConstraint("outlet_id", "product_id", name="uq_outlet_product"),)

    id:Mapped[int] = mapped_column(primary_key=True)
    outlet_id:Mapped[int] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    product_id:Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity:Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at:Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

class StockLedger(Base):
    __tablename__ = "stock_ledgers"

    id:Mapped[int] = mapped_column(primary_key=True)
    outlet_id:Mapped[int] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    product_id:Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    mutation_type:Mapped[MutationType] = mapped_column(Enum(MutationType), nullable=False)
    change_qty:Mapped[int] = mapped_column(Integer, nullable=False) #Return negatif kalau terjual
    balance_after:Mapped[int] = mapped_column(Integer, nullable=False)
    reference_code:Mapped[str] = mapped_column(String(64), index=True)
    created_at:Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class OrderStatus(str, enum.Enum):
    COMPLETED = "COMPLETED"    
    VOIDED = "VOIDED"

class Order(Base):
    __tablename__ = "orders"

    id:Mapped[int] = mapped_column(primary_key=True)
    invoice_number:Mapped[str] = mapped_column(String(64), unique=True, index=True)
    outlet_id:Mapped[int] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    cashier_id:Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount:Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method:Mapped[str] = mapped_column(String(30), nullable=False)
    status:Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.COMPLETED, nullable=False
    )
    created_at:Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class OrderItem(Base):
    __tablename__ = "order_items"

    id:Mapped[int] = mapped_column(primary_key=True)
    order_id:Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id:Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity:Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price:Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    subtotal:Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    
class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key:Mapped[str] = mapped_column(String(100), primary_key=True)
    outlet_id:Mapped[int] = mapped_column(ForeignKey("outlets.id"), nullable=False)
    response_payload:Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at:Mapped[datetime] = mapped_column(DateTime, server_default=func.now())