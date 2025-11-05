from pydantic import BaseModel, EmailStr
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
from enum import Enum

class UserRole(str, Enum):
    ENGINEER = "engineer"
    MANAGER = "manager"
    ADMIN = "admin"
    CLIENT = "client"

class OrderStatus(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class BaseResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

class ErrorResponse(BaseModel):
    code: str
    message: str

class UserBase(BaseModel):
    email: EmailStr
    name: str

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None

class UserResponse(UserBase):
    id: UUID
    roles: List[UserRole]
    created_at: datetime
    updated_at: datetime

class OrderItem(BaseModel):
    product: str
    quantity: int
    price: float

class OrderBase(BaseModel):
    items: List[OrderItem]

class OrderCreate(OrderBase):
    pass

class OrderResponse(BaseModel):
    id: UUID
    user_id: UUID
    items: List[OrderItem]
    total_amount: float
    status: OrderStatus
    created_at: datetime
    updated_at: datetime

class PaginationParams(BaseModel):
    page: int = 1
    size: int = 10

class UsersListResponse(BaseModel):
    users: List[UserResponse]
    total: int
    page: int
    size: int

class OrdersListResponse(BaseModel):
    orders: List[OrderResponse]
    total: int
    page: int
    size: int

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"