from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime
import logging
import os
import psycopg2
import json
from jose import JWTError, jwt
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv

if os.path.exists('.env'):
    load_dotenv()

VALID_STATUS_TRANSITIONS = {
    "created": ["in_progress", "cancelled"],
    "in_progress": ["completed", "cancelled"],
    "completed": [],
    "cancelled": []
}


class OrderItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    price: float

    @field_validator('quantity')
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError('Quantity must be positive')
        return v

    @field_validator('price')
    @classmethod
    def validate_price(cls, v: float) -> float:
        if v < 0:
            raise ValueError('Price cannot be negative')
        return v


class OrderCreate(BaseModel):
    items: List[OrderItem]
    total_amount: float

    @field_validator('total_amount')
    @classmethod
    def validate_total_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError('Total amount must be positive')
        return v


class OrderUpdate(BaseModel):
    status: Optional[str] = None


class OrderResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    items: List[Dict[str, Any]]
    total_amount: float
    status: str
    created_at: datetime
    updated_at: datetime


class BaseResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[dict] = None


class OrderStatus:
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production-123")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
USERS_SERVICE_URL = os.getenv("USERS_SERVICE_URL", "http://localhost:8001")
ORDER_STATUSES = ["created", "in_progress", "completed", "cancelled"]


def get_db():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        import urllib.parse
        result = urllib.parse.urlparse(database_url)
        conn = psycopg2.connect(
            dbname=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port
        )
    else:
        conn = psycopg2.connect(
            dbname="pr2",
            user="postgres",
            password="avt223450",
            host="localhost",
            port="5432"
        )
    return conn


logger = logging.getLogger("orders_service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

app = FastAPI(title="Orders Service", version="1.0.0")

security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return payload


def validate_user_exists(user_id: uuid.UUID) -> bool:
    try:
        return True
    except Exception as e:
        logger.error(f"Error validating user: {e}")
        return False


def is_valid_status_transition(current_status: str, new_status: str) -> bool:
    allowed_transitions = VALID_STATUS_TRANSITIONS.get(current_status, [])
    return new_status in allowed_transitions


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "orders"}


@app.post("/v1/orders", response_model=BaseResponse)
async def create_order(
        order_data: OrderCreate,
        current_user: dict = Depends(get_current_user)
):
    logger.info(f"Creating order for user: {current_user.get('user_id')}")

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        user_id = uuid.UUID(current_user.get('user_id'))

        if not validate_user_exists(user_id):
            return BaseResponse(
                success=False,
                error={"code": "USER_NOT_FOUND", "message": "User not found"}
            )

        order_id = str(uuid.uuid4())

        items_for_json = []
        for item in order_data.items:
            items_for_json.append({
                "product_id": str(item.product_id),
                "product_name": item.product_name,
                "quantity": item.quantity,
                "price": item.price
            })

        items_json = json.dumps(items_for_json)

        cur.execute(
            """INSERT INTO orders (id, user_id, items, total_amount, status) 
               VALUES (%s, %s, %s, %s, %s)""",
            (order_id, str(user_id), items_json, order_data.total_amount, OrderStatus.CREATED)
        )
        conn.commit()

        logger.info(f"Order created successfully: {order_id}")
        logger.info(f"ORDER_CREATED: order_id={order_id}, user_id={user_id}")

        return BaseResponse(
            success=True,
            data={"order_id": order_id}
        )

    except Exception as e:
        logger.error(f"Error creating order: {e}")
        if conn:
            conn.rollback()
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": f"Order creation failed: {str(e)}"}
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.get("/v1/orders/{order_id}", response_model=BaseResponse)
async def get_order(
        order_id: uuid.UUID,
        current_user: dict = Depends(get_current_user)
):
    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM orders WHERE id = %s", (str(order_id),))
        order = cur.fetchone()

        if not order:
            return BaseResponse(
                success=False,
                error={"code": "ORDER_NOT_FOUND", "message": "Order not found"}
            )

        order_user_id = uuid.UUID(order[1])
        current_user_id = uuid.UUID(current_user.get('user_id'))
        user_role = current_user.get('role')

        if order_user_id != current_user_id and user_role != 'admin':
            return BaseResponse(
                success=False,
                error={"code": "ACCESS_DENIED", "message": "Access to this order denied"}
            )

        items_data = order[2]

        order_response = OrderResponse(
            id=order[0],
            user_id=order_user_id,
            items=items_data,
            total_amount=float(order[3]),
            status=order[4],
            created_at=order[5],
            updated_at=order[6]
        )

        return BaseResponse(
            success=True,
            data={"order": order_response.dict()}
        )

    except Exception as e:
        logger.error(f"Error getting order: {e}")
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to get order"}
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.get("/v1/orders", response_model=BaseResponse)
async def get_user_orders(
        current_user: dict = Depends(get_current_user),
        page: int = Query(1, ge=1),
        size: int = Query(10, ge=1, le=100),
        status: Optional[str] = Query(None)
):
    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        user_id = uuid.UUID(current_user.get('user_id'))
        user_role = current_user.get('role')
        offset = (page - 1) * size

        if user_role == 'admin':
            base_query = "SELECT * FROM orders"
            count_query = "SELECT COUNT(*) FROM orders"
            query_params = []
            where_used = False
        else:
            base_query = "SELECT * FROM orders WHERE user_id = %s"
            count_query = "SELECT COUNT(*) FROM orders WHERE user_id = %s"
            query_params = [str(user_id)]
            where_used = True

        if status:
            if where_used:
                base_query += " AND status = %s"
                count_query += " AND status = %s"
            else:
                base_query += " WHERE status = %s"
                count_query += " WHERE status = %s"
                where_used = True
            query_params.append(status)

        base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        query_params.extend([size, offset])

        cur.execute(base_query, query_params)
        orders = cur.fetchall()

        count_params = query_params[:-2]
        cur.execute(count_query, count_params)
        total = cur.fetchone()[0]

        orders_data = []
        for order in orders:
            orders_data.append({
                "id": order[0],
                "user_id": order[1],
                "items": order[2],
                "total_amount": float(order[3]),
                "status": order[4],
                "created_at": order[5],
                "updated_at": order[6]
            })

        return BaseResponse(
            success=True,
            data={
                "orders": orders_data,
                "total": total,
                "page": page,
                "size": size
            }
        )

    except Exception as e:
        logger.error(f"Error getting orders: {e}")
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to get orders"}
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.put("/v1/orders/{order_id}", response_model=BaseResponse)
async def update_order(
        order_id: uuid.UUID,
        order_update: OrderUpdate,
        current_user: dict = Depends(get_current_user)
):
    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM orders WHERE id = %s", (str(order_id),))
        order = cur.fetchone()

        if not order:
            return BaseResponse(
                success=False,
                error={"code": "ORDER_NOT_FOUND", "message": "Order not found"}
            )

        order_user_id = uuid.UUID(order[1])
        current_user_id = uuid.UUID(current_user.get('user_id'))
        user_role = current_user.get('role')

        if order_user_id != current_user_id and user_role != 'admin':
            return BaseResponse(
                success=False,
                error={"code": "ACCESS_DENIED", "message": "Access to update this order denied"}
            )

        if order_update.status:
            if order_update.status not in ORDER_STATUSES:
                return BaseResponse(
                    success=False,
                    error={"code": "INVALID_STATUS", "message": f"Invalid status. Allowed: {ORDER_STATUSES}"}
                )

            current_status = order[4]
            if not is_valid_status_transition(current_status, order_update.status):
                return BaseResponse(
                    success=False,
                    error={
                        "code": "INVALID_STATUS_TRANSITION",
                        "message": f"Cannot change status from '{current_status}' to '{order_update.status}'. "
                                   f"Allowed transitions: {VALID_STATUS_TRANSITIONS.get(current_status, [])}"
                    }
                )

            cur.execute(
                "UPDATE orders SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (order_update.status, str(order_id))
            )
            conn.commit()

            logger.info(f"ORDER_STATUS_UPDATED: order_id={order_id}, from={current_status}, to={order_update.status}")

        logger.info(f"Order updated successfully: {order_id}")
        return BaseResponse(
            success=True,
            data={"message": "Order updated successfully"}
        )

    except Exception as e:
        logger.error(f"Error updating order: {e}")
        if conn:
            conn.rollback()
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to update order"}
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.delete("/v1/orders/{order_id}", response_model=BaseResponse)
async def cancel_order(
        order_id: uuid.UUID,
        current_user: dict = Depends(get_current_user)
):
    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM orders WHERE id = %s", (str(order_id),))
        order = cur.fetchone()

        if not order:
            return BaseResponse(
                success=False,
                error={"code": "ORDER_NOT_FOUND", "message": "Order not found"}
            )

        order_user_id = uuid.UUID(order[1])
        current_user_id = uuid.UUID(current_user.get('user_id'))

        if order_user_id != current_user_id:
            return BaseResponse(
                success=False,
                error={"code": "ACCESS_DENIED", "message": "Only order owner can cancel the order"}
            )

        current_status = order[4]

        if not is_valid_status_transition(current_status, OrderStatus.CANCELLED):
            return BaseResponse(
                success=False,
                error={
                    "code": "CANNOT_CANCEL",
                    "message": f"Cannot cancel order with status '{current_status}'. "
                               f"Order can only be cancelled from 'created' or 'in_progress' status."
                }
            )

        cur.execute(
            "UPDATE orders SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (OrderStatus.CANCELLED, str(order_id))
        )
        conn.commit()

        logger.info(f"Order cancelled successfully: {order_id}")
        logger.info(f"ORDER_CANCELLED: order_id={order_id}, from={current_status}, user_id={current_user_id}")

        return BaseResponse(
            success=True,
            data={"message": "Order cancelled successfully"}
        )

    except Exception as e:
        logger.error(f"Error cancelling order: {e}")
        if conn:
            conn.rollback()
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to cancel order"}
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="localhost",
        port=8002,
    )