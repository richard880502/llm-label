import os
import hashlib
import secrets

import pyotp
from fastapi import APIRouter, Depends, HTTPException
from jose import JWTError, jwt
from pydantic import BaseModel

from ..auth import (
    ALGORITHM,
    SECRET_KEY,
    CurrentUser,
    create_temp_token,
    create_token,
    get_current_user,
    hash_password,
    verify_password,
)
from ..database import get_db

router = APIRouter()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class GoogleTokenRequest(BaseModel):
    credential: str


class TotpVerifyRequest(BaseModel):
    code: str
    temp_token: str


class TotpConfirmRequest(BaseModel):
    code: str


class CreateApiTokenRequest(BaseModel):
    name: str = "Codex / Claude MCP"


@router.get("/config")
def auth_config():
    return {"google_client_id": GOOGLE_CLIENT_ID}


@router.post("/login")
def login(body: LoginRequest):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (body.username,)
        ).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    if row["totp_enabled"]:
        temp_token = create_temp_token(row["username"], row["role"])
        return {"requires_totp": True, "temp_token": temp_token}
    token = create_token(row["username"], row["role"])
    return {"token": token, "username": row["username"], "role": row["role"]}


@router.post("/google")
def google_login(body: GoogleTokenRequest):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "伺服器尚未設定 Google Client ID")
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        idinfo = id_token.verify_oauth2_token(
            body.credential,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
    except Exception as e:
        raise HTTPException(401, f"Google token 驗證失敗：{e}")

    email = idinfo.get("email")
    if not email:
        raise HTTPException(401, "無法取得 Google 帳號 Email")

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE email=? AND is_active=1", (email,)
        ).fetchone()
        if not user:
            raise HTTPException(401, "此 Google 帳號尚未被授權，請聯繫管理員綁定 Email")

        google_sub = idinfo.get("sub")
        if google_sub and not user["google_sub"]:
            conn.execute("UPDATE users SET google_sub=? WHERE id=?", (google_sub, user["id"]))
            conn.commit()

    if user["totp_enabled"]:
        temp_token = create_temp_token(user["username"], user["role"])
        return {"requires_totp": True, "temp_token": temp_token}

    token = create_token(user["username"], user["role"])
    return {"token": token, "username": user["username"], "role": user["role"]}


@router.post("/totp/verify-login")
def totp_verify_login(body: TotpVerifyRequest):
    try:
        payload = jwt.decode(body.temp_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("step") != "google_pending":
            raise HTTPException(401, "無效的驗證 token")
        username: str = payload.get("sub", "")
        role: str = payload.get("role", "reviewer")
    except JWTError:
        raise HTTPException(401, "驗證逾時，請重新登入")

    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE username=? AND is_active=1", (username,)
        ).fetchone()
    if not user or not user["totp_secret"]:
        raise HTTPException(401, "此帳號未設定雙驗證")

    totp = pyotp.TOTP(user["totp_secret"])
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(401, "驗證碼錯誤或已過期")

    token = create_token(username, role)
    return {"token": token, "username": username, "role": role}


@router.get("/totp/status")
def totp_status(current_user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        user = conn.execute(
            "SELECT totp_enabled FROM users WHERE username=?", (current_user.username,)
        ).fetchone()
    return {"enabled": bool(user["totp_enabled"]) if user else False}


@router.post("/totp/setup")
def totp_setup(current_user: CurrentUser = Depends(get_current_user)):
    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.username,
        issuer_name="標注複查平台",
    )
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET totp_secret=?, totp_enabled=0 WHERE username=?",
            (secret, current_user.username),
        )
        conn.commit()
    return {"secret": secret, "uri": uri}


@router.post("/totp/confirm")
def totp_confirm(body: TotpConfirmRequest, current_user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        user = conn.execute(
            "SELECT totp_secret FROM users WHERE username=?", (current_user.username,)
        ).fetchone()
        if not user or not user["totp_secret"]:
            raise HTTPException(400, "請先產生雙驗證設定")

        totp = pyotp.TOTP(user["totp_secret"])
        if not totp.verify(body.code, valid_window=1):
            raise HTTPException(400, "驗證碼錯誤，請重試")

        conn.execute(
            "UPDATE users SET totp_enabled=1 WHERE username=?", (current_user.username,)
        )
        conn.commit()
    return {"ok": True}


@router.delete("/totp")
def totp_disable(current_user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET totp_secret=NULL, totp_enabled=0 WHERE username=?",
            (current_user.username,),
        )
        conn.commit()
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    return {"username": user.username, "role": user.role}


@router.get("/tokens")
def list_api_tokens(user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, name, token_prefix, created_at, last_used_at
               FROM api_tokens WHERE username=? AND revoked_at IS NULL
               ORDER BY created_at DESC""",
            (user.username,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.post("/tokens")
def create_api_token(
    body: CreateApiTokenRequest,
    user: CurrentUser = Depends(get_current_user),
):
    raw_token = "apt_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    prefix = raw_token[:12]
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO api_tokens (username, name, token_hash, token_prefix)
               VALUES (?, ?, ?, ?)""",
            (user.username, body.name.strip() or "Codex / Claude MCP", token_hash, prefix),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name, token_prefix, created_at FROM api_tokens WHERE id=?",
            (cur.lastrowid,),
        ).fetchone()
    return {**dict(row), "token": raw_token}


@router.delete("/tokens/{token_id}")
def revoke_api_token(token_id: int, user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        cur = conn.execute(
            """UPDATE api_tokens SET revoked_at=datetime('now', 'localtime')
               WHERE id=? AND username=? AND revoked_at IS NULL""",
            (token_id, user.username),
        )
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(404, "找不到存取權杖")
    return {"ok": True}


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser = Depends(get_current_user),
):
    if len(body.new_password) < 4:
        raise HTTPException(400, "密碼至少需要 4 個字元")
    with get_db() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username=?", (user.username,)
        ).fetchone()
        if not row or not verify_password(body.current_password, row["password_hash"]):
            raise HTTPException(400, "目前密碼不正確")
        conn.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (hash_password(body.new_password), user.username),
        )
        conn.commit()
    return {"ok": True}
