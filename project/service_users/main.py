from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import List, Optional
import uuid
from datetime import datetime, timedelta
import logging
import re
import psycopg2
import bcrypt
from jose import JWTError, jwt

# Схемы Pydantic
from pydantic import BaseModel, field_validator

SECRET_KEY = "your-super-secret-key-change-in-production-123"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

logger = logging.getLogger("users_service")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


class UserBase(BaseModel):
    email: str
    name: str

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v


class UserRole:
    ADMIN = "admin"
    CLIENT = "client"

class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    role: str
    created_at: datetime
    updated_at: datetime


class BaseResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[dict] = None


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v):
            raise ValueError('Invalid email format')
        return v


# Функции для работы с БД
def get_db():
    conn = psycopg2.connect(
        dbname="pr2",
        user="postgres",
        password="avt223450",
        host="localhost",
        port="5432"
    )
    return conn


# Функции для аутентификации
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# Инициализация FastAPI
app = FastAPI(title="Users Service", version="1.0.0")

security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return payload


# Эндпоинты
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "users"}


@app.post("/v1/register", response_model=BaseResponse)
async def register(user_data: UserCreate):
    logger.info(f"Registration attempt for email: {user_data.email}")

    conn = None
    cur = None

    try:
        conn = get_db()
        cur = conn.cursor()

        # Проверяем существующего пользователя
        cur.execute("SELECT * FROM users WHERE email = %s", (user_data.email,))
        existing_user = cur.fetchone()

        if existing_user:
            logger.warning(f"Registration failed - email already exists: {user_data.email}")
            return BaseResponse(
                success=False,
                error={"code": "USER_EXISTS", "message": "User with this email already exists"}
            )

        # Создаем пользователя с ролью 'client' по умолчанию
        user_id = str(uuid.uuid4())
        hashed_password = get_password_hash(user_data.password)

        cur.execute(
            "INSERT INTO users (id, email, password_hash, name, roles) VALUES (%s, %s, %s, %s, %s)",
            (user_id, user_data.email, hashed_password, user_data.name, "client")  # ← просто строка "client"
        )
        conn.commit()

        logger.info(f"User registered successfully: {user_id}")
        return BaseResponse(
            success=True,
            data={"user_id": user_id}
        )

    except Exception as e:
        logger.error(f"❌ DATABASE ERROR: {str(e)}")
        if conn:
            conn.rollback()
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": f"Registration failed: {str(e)}"}
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@app.post("/v1/login", response_model=BaseResponse)
async def login(login_data: LoginRequest):
    logger.info(f"Login attempt for email: {login_data.email}")

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM users WHERE email = %s", (login_data.email,))
        user = cur.fetchone()

        if not user or not verify_password(login_data.password, user[2]):  # password_hash в позиции 2
            logger.warning(f"Login failed for email: {login_data.email}")
            return BaseResponse(
                success=False,
                error={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password"}
            )

        access_token = create_access_token(
            data={"sub": user[1], "user_id": user[0], "role": user[4]},  # ← user[4] теперь строка
            expires_delta=timedelta(minutes=30)
        )

        logger.info(f"Login successful for user: {user[0]}")
        return BaseResponse(
            success=True,
            data={
                "access_token": access_token,
                "token_type": "bearer",
                "user_id": str(user[0])
            }
        )

    except Exception as e:
        logger.error(f"Database error: {e}")
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Login failed"}
        )
    finally:
        cur.close()
        conn.close()


@app.get("/v1/profile", response_model=BaseResponse)
async def get_profile(current_user: dict = Depends(get_current_user)):
    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM users WHERE email = %s", (current_user["sub"],))
        user = cur.fetchone()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        user_response = UserResponse(
            id=user[0],
            email=user[1],
            name=user[3],
            role=user[4],
            created_at=user[5],
            updated_at=user[6]
        )

        return BaseResponse(
            success=True,
            data={"user": user_response.model_dump()}
        )

    except Exception as e:
        logger.error(f"Database error: {e}")
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to get profile"}
        )
    finally:
        cur.close()
        conn.close()


@app.put("/v1/profile", response_model=BaseResponse)
async def update_profile(
        user_update: UserUpdate,
        current_user: dict = Depends(get_current_user)
):
    conn = get_db()
    cur = conn.cursor()

    try:
        # Получаем текущего пользователя
        cur.execute("SELECT * FROM users WHERE email = %s", (current_user["sub"],))
        user = cur.fetchone()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Проверяем email на уникальность если он меняется
        if user_update.email and user_update.email != user[1]:
            cur.execute("SELECT * FROM users WHERE email = %s", (user_update.email,))
            existing_user = cur.fetchone()
            if existing_user:
                return BaseResponse(
                    success=False,
                    error={"code": "EMAIL_EXISTS", "message": "Email already in use"}
                )

        # Обновляем данные
        update_fields = []
        update_values = []

        if user_update.name:
            update_fields.append("name = %s")
            update_values.append(user_update.name)

        if user_update.email:
            update_fields.append("email = %s")
            update_values.append(user_update.email)

        if update_fields:
            update_values.append(user[0])  # user_id для WHERE
            cur.execute(
                f"UPDATE users SET {', '.join(update_fields)}, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                update_values
            )
            conn.commit()

        logger.info(f"Profile updated for user: {user[0]}")
        return BaseResponse(
            success=True,
            data={"message": "Profile updated successfully"}
        )

    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to update profile"}
        )
    finally:
        cur.close()
        conn.close()


@app.get("/v1/users", response_model=BaseResponse)
async def get_users(
        current_user: dict = Depends(get_current_user),
        page: int = Query(1, ge=1),
        size: int = Query(10, ge=1, le=100)
):
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

    conn = get_db()
    cur = conn.cursor()

    try:
        offset = (page - 1) * size

        # Получаем пользователей с пагинацией
        cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s", (size, offset))
        users = cur.fetchall()

        # Получаем общее количество
        cur.execute("SELECT COUNT(*) FROM users")
        total = cur.fetchone()[0]

        users_data = []
        for user in users:
            users_data.append({
                "id": user[0],
                "email": user[1],
                "name": user[3],
                "roles": user[4],
                "created_at": user[5],
                "updated_at": user[6]
            })

        return BaseResponse(
            success=True,
            data={
                "users": users_data,
                "total": total,
                "page": page,
                "size": size
            }
        )

    except Exception as e:
        logger.error(f"Database error: {e}")
        return BaseResponse(
            success=False,
            error={"code": "DATABASE_ERROR", "message": "Failed to get users list"}
        )
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="localhost",
        port=8001,
    )