import os
import hashlib
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

_bearer = HTTPBearer()


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": username, "role": role, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_temp_token(username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=5)
    return jwt.encode(
        {"sub": username, "role": role, "step": "google_pending", "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


class CurrentUser:
    def __init__(self, username: str, role: str):
        self.username = username
        self.role = role


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    raw_token = credentials.credentials
    if raw_token.startswith("apt_"):
        from .database import get_db

        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        conn = get_db()
        row = conn.execute(
            """SELECT t.username, u.role FROM api_tokens t
               JOIN users u ON u.username=t.username
               WHERE t.token_hash=? AND t.revoked_at IS NULL AND u.is_active=1""",
            (token_hash,),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE api_tokens SET last_used_at=datetime('now', 'localtime') WHERE token_hash=?",
                (token_hash,),
            )
            conn.commit()
        conn.close()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid or revoked access token")
        return CurrentUser(username=row["username"], role=row["role"])
    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("step") == "google_pending":
            raise HTTPException(status_code=401, detail="Token requires Google verification")
        username: str = payload.get("sub", "")
        role: str = payload.get("role", "reviewer")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return CurrentUser(username=username, role=role)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
