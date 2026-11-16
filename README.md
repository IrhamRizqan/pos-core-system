# pos-core-system

Backend API for a multi-outlet Point of Sale (POS) system built with **FastAPI**, **async SQLAlchemy 2.0**, **MySQL 8.0**, and **Redis**

Instead of a basic CRUD store, this project focuses on the edge cases that usually break naive POS implementations in production: race conditions when multiple cashiers sell the last remaining item simultaneously, duplicate orders from network retries, and unauthorized cross-branch access

## Tech Stack

- **Framework:** Python 3.11, FastAPI, Pydantic v2
- **Database:** MySQL 8.0, SQLAlchemy 2.0 (`asyncio` + `asyncmy`)
- **Cache:** Redis 7 (`redis.asyncio`)
- **Auth:** JWT (`PyJWT`) & `bcrypt`
- **Testing & Infra:** Pytest, `pytest-asyncio`, `httpx`, Docker Compose

## Architecture & Design Decisions

### 1. Preventing Overselling & Deadlocks
Checking stock in application memory before subtracting it fails under concurrent load. During checkout, stock rows in `outlet_stocks` are locked at the database level using `SELECT ... FOR UPDATE` (`with_for_update()`) inside a single ACID transaction

To avoid deadlocks when two cashiers check out overlapping items in different orders, cart items are sorted by `product_id` ascending before acquiring row locks

### 2. Idempotent Checkout
POS terminals on unstable connections often retry timed-out payment requests. `POST /api/v1/checkout` requires an `Idempotency-Key` header. The key and its serialized response payload are committed inside the same transaction as the order—if the terminal retries with the same key, the API returns the original receipt immediately without deducting stock again

### 3. Append-Only Stock Ledger
Current stock counts live in `outlet_stocks` for fast lookups, while every inventory change (`SALE`, `RESTOCK`, `VOID`, `ADJUSTMENT`) is recorded as an immutable row in `stock_ledgers` along with `change_qty`, `balance_after`, and the reference invoice/PO number

### 4. Cache-Aside Product Catalog
`GET /api/v1/products/outlet/{outlet_id}` reads from Redis (`catalog:outlet:{id}`) first and falls back to MySQL on a cache miss. Any stock-mutating operation (checkout, restock, or order void) invalidates the outlet's cache key after committing

### 5. Multi-Outlet Isolation & RBAC
Staff accounts are scoped to an `outlet_id` and assigned one of three roles: `CASHIER`, `MANAGER`, or `OWNER`.
- Cashiers can only process checkouts for their assigned branch.
- Managers can restock inventory and void completed orders, restricted strictly to their own branch.
- Voiding an order locks the `orders` row first to prevent duplicate voids (`409 Conflict`), restores stock quantities, and writes a `VOID` entry to the ledger

## Project Structure

```text
pos-core-system/
├── app/
│   ├── api/v1/
│   │   ├── auth.py          # JWT login endpoint
│   │   ├── checkout.py      # Checkout & order void endpoints
│   │   ├── inventory.py     # Manager/Owner restock endpoint
│   │   └── products.py      # Redis-cached outlet catalog
│   ├── core/
│   │   ├── config.py        # Environment settings
│   │   ├── database.py      # Async SQLAlchemy engine & session
│   │   ├── redis.py         # Async Redis client
│   │   └── security.py      # Password hashing, JWT & RBAC dependencies
│   ├── models/
│   │   └── pos.py           # SQLAlchemy ORM models & enums
│   ├── schemas/
│   │   └── checkout.py      # Pydantic request/response schemas
│   ├── services/
│   │   ├── checkout_service.py   # Transactional checkout & void logic
│   │   └── inventory_service.py  # Transactional restock logic
│   └── main.py              # App entrypoint, lifespan & initial seed
├── tests/
│   ├── test_concurrency.py     # Parallel checkout race-condition test
│   └── test_rbac_inventory.py  # Role permissions, cross-outlet & void tests
├── docker-compose.yml       # MySQL 8.0 & Redis containers
├── pytest.ini
└── requirements.txt
```

## API Endpoints

| Method | Path | Access | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/login` | Public | Exchange credentials for a JWT bearer token |
| `GET` | `/api/v1/products/outlet/{outlet_id}` | Authenticated | Get outlet catalog and current stock (Redis cached) |
| `POST` | `/api/v1/checkout` | `CASHIER`, `MANAGER`, `OWNER` | Create an order (requires `Idempotency-Key` header) |
| `POST` | `/api/v1/checkout/{invoice_number}/void` | `MANAGER`, `OWNER` | Cancel a completed order and restore inventory |
| `POST` | `/api/v1/inventory/restock` | `MANAGER`, `OWNER` | Add stock to an outlet and log a `RESTOCK` ledger entry |
| `GET` | `/health` | Public | Health check |

## Local Setup

### 1. Start MySQL and Redis
```bash
docker compose up -d
```

### 2. Install Dependencies
```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Run the Server
```bash
uvicorn app.main:app --reload
```

On startup, tables are created automatically along with two default accounts for `outlet_id: 1`:
- **Cashier:** `kasir1` / `password123`
- **Manager:** `manager1` / `password123`

Swagger UI is available at `http://127.0.0.1:8000/docs`.

## Running Tests

The integration test suite runs against the live Docker MySQL and Redis instances to verify row-level locking under concurrent requests and RBAC enforcement:

```bash
pytest -v
```

```text
tests/test_concurrency.py::test_prevent_overselling_in_pressure PASSED                [ 25%]
tests/test_rbac_inventory.py::test_cashier_forbidden_from_restock_and_void PASSED     [ 50%]
tests/test_rbac_inventory.py::test_manager_cross_outlet_isolation PASSED              [ 75%]
tests/test_rbac_inventory.py::test_manager_restock_and_void_flow_with_ledger PASSED   [100%]

4 passed in 3.06s
```