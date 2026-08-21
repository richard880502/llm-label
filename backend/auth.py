import os
import hashlib
import json
import re
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request
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
    """Authenticated platform identity.

    Browser JWTs and legacy PATs retain the platform's existing permissions.
    OAuth-issued MCP tokens are deliberately narrower: their scopes and optional
    project allow-list are evaluated for every protected API request.
    """

    def __init__(
        self,
        username: str,
        role: str,
        *,
        scopes: set[str] | None = None,
        project_ids: set[int] | None = None,
        oauth_connection_id: int | None = None,
    ):
        self.username = username
        self.role = role
        self.scopes = scopes
        self.project_ids = project_ids
        self.oauth_connection_id = oauth_connection_id

    @property
    def is_oauth_connection(self) -> bool:
        return self.oauth_connection_id is not None


def _oauth_user(raw_token: str) -> CurrentUser | None:
    """Resolve an opaque MCP OAuth access token without accepting a login JWT."""
    if not raw_token.startswith("mcp_"):
        return None
    from .database import get_db

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    with get_db() as conn:
        row = conn.execute(
            """SELECT c.id AS connection_id, c.username, u.role, c.scopes, c.project_ids
               FROM mcp_oauth_tokens t
               JOIN mcp_oauth_connections c ON c.id=t.connection_id
               JOIN users u ON u.username=c.username
               WHERE t.access_token_hash=? AND t.revoked_at IS NULL
                 AND t.expires_at > datetime('now', 'localtime')
                 AND c.revoked_at IS NULL AND u.is_active=1""",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE mcp_oauth_tokens SET last_used_at=datetime('now', 'localtime') WHERE access_token_hash=?",
            (token_hash,),
        )
        conn.execute(
            "UPDATE mcp_oauth_connections SET last_used_at=datetime('now', 'localtime') WHERE id=?",
            (row["connection_id"],),
        )
        conn.commit()
    try:
        project_ids = {int(item) for item in json.loads(row["project_ids"] or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        project_ids = set()
    return CurrentUser(
        username=row["username"],
        role=row["role"],
        scopes=set((row["scopes"] or "").split()),
        project_ids=project_ids,
        oauth_connection_id=row["connection_id"],
    )


def _pat_user(raw_token: str) -> CurrentUser | None:
    if not raw_token.startswith("apt_"):
        return None
    from .database import get_db

    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    with get_db() as conn:
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
    return CurrentUser(username=row["username"], role=row["role"]) if row else None


def authenticate_mcp_token(raw_token: str) -> CurrentUser | None:
    """Only token types intended for MCP transport: OAuth or legacy PAT."""
    return _oauth_user(raw_token) or _pat_user(raw_token)


def require_scope(user: CurrentUser, scope: str) -> None:
    if user.scopes is not None and scope not in user.scopes:
        raise HTTPException(status_code=403, detail=f"MCP connection lacks required scope: {scope}")


def _enforce_oauth_request_scope(user: CurrentUser, request: Request) -> None:
    """Map the existing REST surface to OAuth scopes without changing JWT/PAT behavior."""
    if not user.is_oauth_connection:
        return
    path = request.url.path
    method = request.method
    project_match = re.search(r"/api/projects/(\d+)(?:/|$)", path)
    if project_match and user.project_ids and int(project_match.group(1)) not in user.project_ids:
        raise HTTPException(status_code=403, detail="MCP connection is not allowed to access this project")

    scope: str | None = None
    if path == "/api/projects":
        scope = "projects:read" if method == "GET" else None
    elif "/rows" in path:
        if method == "GET":
            scope = "rows:read"
        elif path.endswith("/rows/batch"):
            scope = "reviews:batch_approve"
        # Single-row PATCH has to inspect its requested status: approval is a
        # separate high-risk permission and is checked in rows.update_row.
    elif "/tasks" in path:
        scope = "tasks:read" if method == "GET" and "/batch" not in path else "tasks:run"
    elif method == "GET" and project_match:
        scope = "projects:read"
    if scope:
        require_scope(user, scope)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> CurrentUser:
    raw_token = credentials.credentials
    mcp_user = authenticate_mcp_token(raw_token)
    if mcp_user:
        _enforce_oauth_request_scope(mcp_user, request)
        return mcp_user
    if raw_token.startswith(("apt_", "mcp_")):
        raise HTTPException(status_code=401, detail="Invalid, expired, or revoked access token")
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
