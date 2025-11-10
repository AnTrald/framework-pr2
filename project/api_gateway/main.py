from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import httpx
import logging
import os
from jose import JWTError, jwt
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import List, Optional
import uuid

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-in-production-123")
ALGORITHM = os.getenv("ALGORITHM", "HS256")

logger = logging.getLogger("api_gateway")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

app = FastAPI(title="API Gateway", version="1.0.0")

security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SERVICE_ROUTES = {
    "users": os.getenv("USERS_SERVICE_URL"),
    "orders": os.getenv("ORDERS_SERVICE_URL")
}

class UserCreate(BaseModel):
    email: str
    name: str
    password: str

class LoginData(BaseModel):
    email: str
    password: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

class OrderItem(BaseModel):
    product_id: uuid.UUID
    product_name: str
    quantity: int
    price: float

class OrderCreate(BaseModel):
    items: List[OrderItem]
    total_amount: float

class OrderUpdate(BaseModel):
    status: Optional[str] = None

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
            status_code=401,
            detail="Invalid authentication credentials"
        )
    return payload

async def proxy_request(request: Request, target_url: str, data: dict = None):
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    try:
        async with httpx.AsyncClient() as client:
            if data:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    json=data,
                    timeout=30.0
                )
            else:
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=await request.body(),
                    timeout=30.0
                )
            return response

    except httpx.ConnectError:
        logger.error(f"Cannot connect to service: {target_url}")
        raise HTTPException(503, "Service temporarily unavailable")
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        raise HTTPException(500, "Internal gateway error")

async def handle_proxy_request(service: str, path: str, data: dict = None, request: Request = None):
    target_url = f"{SERVICE_ROUTES[service]}/{path}"
    logger.info(f"Proxying to: {target_url}")

    response = await proxy_request(request, target_url, data)
    logger.info(f"Response from {service}: {response.status_code}")
    return response.json()

@app.post("/v1/users/register")
async def gateway_users_register(user_data: UserCreate, request: Request):
    return await handle_proxy_request("users", "v1/users/register", user_data.dict(), request)

@app.post("/v1/users/login")
async def gateway_users_login(login_data: LoginData, request: Request):
    return await handle_proxy_request("users", "v1/users/login", login_data.dict(), request)

@app.get("/v1/users/profile")
async def gateway_users_profile(request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("users", "v1/users/profile", None, request)

@app.put("/v1/users/profile")
async def gateway_users_update_profile(user_update: UserUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("users", "v1/users/profile", user_update.dict(), request)

@app.get("/v1/users")
async def gateway_users_list(request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("users", "v1/users", None, request)

# Orders endpoints - все с авторизацией
@app.post("/v1/orders")
async def gateway_orders_create(order_data: OrderCreate, request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("orders", "v1/orders", order_data.dict(), request)

@app.get("/v1/orders/{order_id}")
async def gateway_orders_get(order_id: uuid.UUID, request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("orders", f"v1/orders/{order_id}", None, request)

@app.get("/v1/orders")
async def gateway_orders_list(request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("orders", "v1/orders", None, request)

@app.put("/v1/orders/{order_id}")
async def gateway_orders_update(order_id: uuid.UUID, order_update: OrderUpdate, request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("orders", f"v1/orders/{order_id}", order_update.dict(), request)

@app.delete("/v1/orders/{order_id}")
async def gateway_orders_cancel(order_id: uuid.UUID, request: Request, current_user: dict = Depends(get_current_user)):
    return await handle_proxy_request("orders", f"v1/orders/{order_id}", None, request)

# Health check
@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "api_gateway",
        "available_services": list(SERVICE_ROUTES.keys())
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run('main:app', reload=True, host="localhost", port=8000)