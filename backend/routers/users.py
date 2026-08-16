from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import CurrentUser, hash_password, require_admin
from ..database import get_db

router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "reviewer"
    email: str = ""


class SetEmailRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    new_password: str


class UpdateRoleRequest(BaseModel):
    role: str


@router.get("")
def list_users(admin: CurrentUser = Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at, is_active, email, totp_enabled FROM users ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("")
def create_user(body: CreateUserRequest, admin: CurrentUser = Depends(require_admin)):
    if len(body.password) < 4:
        raise HTTPException(400, "密碼至少需要 4 個字元")
    if body.role not in ("admin", "reviewer"):
        raise HTTPException(400, "角色必須是 admin 或 reviewer")
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username=?", (body.username,)).fetchone()
        if existing:
            raise HTTPException(400, "帳號已存在")
        email = body.email.strip() or None
        conn.execute(
            "INSERT INTO users (username, password_hash, role, email) VALUES (?, ?, ?, ?)",
            (body.username, hash_password(body.password), body.role, email),
        )
        conn.commit()
        row = conn.execute("SELECT id, username, role, created_at, is_active, email FROM users WHERE username=?", (body.username,)).fetchone()
    return dict(row)


@router.delete("/{user_id}")
def delete_user(user_id: int, admin: CurrentUser = Depends(require_admin)):
    with get_db() as conn:
        target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "使用者不存在")
        if target["username"] == admin.username:
            raise HTTPException(400, "無法刪除自己的帳號")
        admin_count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
        ).fetchone()[0]
        if target["role"] == "admin" and admin_count <= 1:
            raise HTTPException(400, "至少要保留一個管理員帳號")
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    return {"ok": True}


@router.patch("/{user_id}/role")
def update_role(
    user_id: int,
    body: UpdateRoleRequest,
    admin: CurrentUser = Depends(require_admin),
):
    if body.role not in ("admin", "reviewer"):
        raise HTTPException(400, "角色必須是 admin 或 reviewer")
    with get_db() as conn:
        target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "使用者不存在")
        if target["username"] == admin.username:
            raise HTTPException(400, "無法修改自己的角色")
        if target["role"] == "admin" and body.role == "reviewer":
            admin_count = conn.execute(
                "SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=1"
            ).fetchone()[0]
            if admin_count <= 1:
                raise HTTPException(400, "至少要保留一個管理員帳號")
        conn.execute("UPDATE users SET role=? WHERE id=?", (body.role, user_id))
        conn.commit()
        updated = conn.execute(
            "SELECT id, username, role, created_at, is_active FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return dict(updated)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    admin: CurrentUser = Depends(require_admin),
):
    if len(body.new_password) < 4:
        raise HTTPException(400, "密碼至少需要 4 個字元")
    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "使用者不存在")
        conn.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (hash_password(body.new_password), user_id),
        )
        conn.commit()
    return {"ok": True}


@router.patch("/{user_id}/email")
def set_email(
    user_id: int,
    body: SetEmailRequest,
    admin: CurrentUser = Depends(require_admin),
):
    email = body.email.strip() or None
    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "使用者不存在")
        conn.execute("UPDATE users SET email=? WHERE id=?", (email, user_id))
        conn.commit()
        updated = conn.execute(
            "SELECT id, username, role, created_at, is_active, email, totp_enabled FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return dict(updated)


@router.post("/{user_id}/totp")
def admin_enable_totp(user_id: int, admin: CurrentUser = Depends(require_admin)):
    import pyotp
    with get_db() as conn:
        target = conn.execute("SELECT id, username FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "使用者不存在")
        secret = pyotp.random_base32()
        uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=target["username"],
            issuer_name="標注複查平台",
        )
        conn.execute(
            "UPDATE users SET totp_secret=?, totp_enabled=1 WHERE id=?",
            (secret, user_id),
        )
        conn.commit()
    return {"secret": secret, "uri": uri}


@router.delete("/{user_id}/totp")
def admin_disable_totp(user_id: int, admin: CurrentUser = Depends(require_admin)):
    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "使用者不存在")
        conn.execute(
            "UPDATE users SET totp_secret=NULL, totp_enabled=0 WHERE id=?", (user_id,)
        )
        conn.commit()
    return {"ok": True}
