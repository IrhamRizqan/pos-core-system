from email.policy import default
from decimal import Decimal
from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    username:str
    password:str

class TokenResponse(BaseModel):
    access_token:str
    token_type:str = "bearer"

class ProductCatalogItem(BaseModel):
    id:int
    sku:str
    name:str
    price:Decimal
    stock:int

class CheckoutItemRequest(BaseModel):
    product_id:int
    quantity:int = Field(..., gt=0, description="Minimal pembelian 1 Item")

class CheckoutRequest(BaseModel):
    outlet_id:int
    payment_method:str = Field(..., examples=["QRIS", "CASH", "DEBIT"])
    items:list[CheckoutItemRequest]

class RestockRequest(BaseModel):
    outlet_id:int = Field(..., examples=[1])
    product_id:int = Field(..., examples=[1])
    quantity:int = Field(..., gt=0, description="Jumlah stok masuk harus lebih dari 0")
    reference_note:str = Field(default="MANUAL-RESTOCK", max_length=64)

class StockOpnameRequest(BaseModel):
    outlet_id:int = Field(..., examples=[1])
    product_id:int = Field(..., examples=[1])
    actual_stock:int = Field(..., ge=0, description="Jumlah stok fisik hasil hitung aktual")
    reason:str = Field(
        default="STOK-OPNAME",
        min_length=3,
        max_length=50,
        examples=["BARANG-RUSAK", "SELISIH-HITUNG-BULANAN"],
    )
