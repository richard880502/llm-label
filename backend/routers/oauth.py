"""OAuth 2.1 authorization server for the public MCP endpoint.

The browser-facing authorization page lives in the React application so it can
reuse the platform's password, Google, and TOTP login flows.  This router owns
client registration, authorization-code exchange, refresh-token rotation, and
connection revocation.
"""

import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..auth import CurrentUser, get_current_user
from ..database import get_db

router = APIRouter()

MCP_SCOPES = {
    "projects:read",
    "rows:read",
    "tasks:read",
    "tasks:run",
    "rows:write",
    "reviews:approve",
    "reviews:batch_approve",
    "offline_access",
}
DEFAULT_SCOPES = {"projects:read", "rows:read", "tasks:read", "tasks:run"}
ACCESS_TOKEN_MINUTES = 60
REFRESH_TOKEN_DAYS = 30


def _now_plus(minutes: int) -> str:
    return (datetime.now(ZoneInfo("Asia/Taipei")) + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _parse_scope(scope: str | None) -> set[str]:
    values = set((scope or "").split())
    unknown = values - MCP_SCOPES
    if unknown:
        raise HTTPException(400, detail=f"Unsupported OAuth scope: {', '.join(sorted(unknown))}")
    return values


def _valid_redirect_uri(uri: str) -> bool:
    parsed = urlparse(uri)
    return bool(parsed.scheme == "https" and parsed.netloc) or (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


def _pkce_s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def _token_response(connection_id: int, scopes: str) -> dict:
    access_token = "mcp_" + secrets.token_urlsafe(32)
    issue_refresh_token = "offline_access" in scopes.split()
    refresh_token = "mcp_refresh_" + secrets.token_urlsafe(40) if issue_refresh_token else None
    with get_db() as conn:
        conn.execute(
            """INSERT INTO mcp_oauth_tokens
               (connection_id, access_token_hash, refresh_token_hash, expires_at)
               VALUES (?, ?, ?, ?)""",
            (connection_id, _hash(access_token), _hash(refresh_token) if refresh_token else None, _now_plus(ACCESS_TOKEN_MINUTES)),
        )
        conn.commit()
    result = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_MINUTES * 60,
        "scope": scopes,
    }
    if refresh_token:
        result["refresh_token"] = refresh_token
    return result


class DynamicClientRequest(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=20)
    client_name: str = "MCP client"
    grant_types: list[str] = []
    response_types: list[str] = []
    token_endpoint_auth_method: str = "none"


class ConsentRequest(BaseModel):
    client_id: str
    redirect_uri: str
    code_challenge: str = Field(min_length=43, max_length=128)
    code_challenge_method: str = "S256"
    scope: str = ""
    resource: str = ""
    approved_scopes: list[str] = []
    project_ids: list[int] = []


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_client(body: DynamicClientRequest):
    if any(not _valid_redirect_uri(uri) for uri in body.redirect_uris):
        raise HTTPException(400, detail="redirect_uris must use HTTPS (or localhost HTTP)")
    if body.token_endpoint_auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
        raise HTTPException(400, detail="Unsupported token endpoint authentication method")
    client_id = "mcp_client_" + secrets.token_urlsafe(24)
    client_name = body.client_name.strip()[:120] or "MCP client"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO mcp_oauth_clients (client_id, client_name, redirect_uris) VALUES (?, ?, ?)",
            (client_id, client_name, json.dumps(body.redirect_uris)),
        )
        conn.commit()
    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": body.redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }


@router.post("/authorize/complete")
def complete_authorization(body: ConsentRequest, request: Request, user: CurrentUser = Depends(get_current_user)):
    if user.is_oauth_connection:
        raise HTTPException(403, detail="Use a platform login to authorize a new MCP connection")
    if body.code_challenge_method != "S256":
        raise HTTPException(400, detail="OAuth clients must use PKCE S256")
    if body.resource:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
        host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
        if body.resource != f"{proto}://{host}/mcp":
            raise HTTPException(400, detail="OAuth resource must match this MCP endpoint")
    requested = _parse_scope(body.scope)
    requested = requested or DEFAULT_SCOPES
    approved = set(body.approved_scopes) if body.approved_scopes else requested & DEFAULT_SCOPES
    if not approved <= requested or not approved <= MCP_SCOPES:
        raise HTTPException(400, detail="Approved scopes must be a subset of requested scopes")
    # Refresh tokens are only issued when the client explicitly requests offline access.
    if "offline_access" not in requested:
        approved.discard("offline_access")
    if not approved - {"offline_access"}:
        raise HTTPException(400, detail="Choose at least one MCP permission")

    with get_db() as conn:
        client = conn.execute(
            "SELECT client_id FROM mcp_oauth_clients WHERE client_id=?", (body.client_id,)
        ).fetchone()
        if not client:
            raise HTTPException(400, detail="Unknown OAuth client")
        redirect_uris = json.loads(
            conn.execute("SELECT redirect_uris FROM mcp_oauth_clients WHERE client_id=?", (body.client_id,)).fetchone()["redirect_uris"]
        )
        if body.redirect_uri not in redirect_uris:
            raise HTTPException(400, detail="redirect_uri does not match client registration")
        code = "mcp_code_" + secrets.token_urlsafe(32)
        conn.execute(
            """INSERT INTO mcp_oauth_authorization_codes
               (code_hash, client_id, username, redirect_uri, scopes, project_ids, code_challenge, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _hash(code), body.client_id, user.username, body.redirect_uri,
                " ".join(sorted(approved)), json.dumps(sorted(set(body.project_ids))),
                body.code_challenge, _now_plus(5),
            ),
        )
        conn.commit()
    return {"code": code}


@router.get("/authorize-info")
def authorization_info(client_id: str = Query(...), redirect_uri: str = Query(...), scope: str = Query("")):
    requested = _parse_scope(scope) or DEFAULT_SCOPES
    with get_db() as conn:
        client = conn.execute(
            "SELECT client_name, redirect_uris FROM mcp_oauth_clients WHERE client_id=?", (client_id,)
        ).fetchone()
    if not client or redirect_uri not in json.loads(client["redirect_uris"]):
        raise HTTPException(400, detail="Unknown OAuth client or redirect URI")
    return {"client_name": client["client_name"], "requested_scopes": sorted(requested)}


@router.post("/token")
def issue_token(
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    client_id: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
):
    if grant_type == "authorization_code":
        if not all((code, redirect_uri, client_id, code_verifier)):
            raise HTTPException(400, detail="code, redirect_uri, client_id, and code_verifier are required")
        with get_db() as conn:
            auth_code = conn.execute(
                """SELECT * FROM mcp_oauth_authorization_codes WHERE code_hash=?
                   AND client_id=? AND redirect_uri=? AND consumed_at IS NULL
                   AND expires_at > datetime('now', 'localtime')""",
                (_hash(code), client_id, redirect_uri),
            ).fetchone()
            if not auth_code or not secrets.compare_digest(auth_code["code_challenge"], _pkce_s256(code_verifier)):
                raise HTTPException(400, detail="Invalid, expired, or already used authorization code")
            client = conn.execute(
                "SELECT client_name FROM mcp_oauth_clients WHERE client_id=?", (client_id,)
            ).fetchone()
            conn.execute(
                "UPDATE mcp_oauth_authorization_codes SET consumed_at=datetime('now', 'localtime') WHERE id=?",
                (auth_code["id"],),
            )
            connection = conn.execute(
                """INSERT INTO mcp_oauth_connections (username, client_id, client_name, scopes, project_ids)
                   VALUES (?, ?, ?, ?, ?)""",
                (auth_code["username"], client_id, client["client_name"], auth_code["scopes"], auth_code["project_ids"]),
            )
            conn.commit()
            connection_id = connection.lastrowid
        return _token_response(connection_id, auth_code["scopes"])

    if grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(400, detail="refresh_token is required")
        with get_db() as conn:
            token = conn.execute(
                """SELECT t.*, c.scopes FROM mcp_oauth_tokens t
                   JOIN mcp_oauth_connections c ON c.id=t.connection_id
                   WHERE t.refresh_token_hash=? AND t.revoked_at IS NULL AND c.revoked_at IS NULL""",
                (_hash(refresh_token),),
            ).fetchone()
            if not token or "offline_access" not in token["scopes"].split():
                raise HTTPException(400, detail="Invalid or revoked refresh token")
            conn.execute("UPDATE mcp_oauth_tokens SET revoked_at=datetime('now', 'localtime') WHERE id=?", (token["id"],))
            conn.commit()
        return _token_response(token["connection_id"], token["scopes"])

    raise HTTPException(400, detail="Unsupported grant_type")


@router.post("/revoke", status_code=status.HTTP_200_OK)
def revoke_token(token: str = Form(...), token_type_hint: str | None = Form(None)):
    token_hash = _hash(token)
    with get_db() as conn:
        if token_type_hint == "refresh_token" or token.startswith("mcp_refresh_"):
            conn.execute("UPDATE mcp_oauth_tokens SET revoked_at=datetime('now', 'localtime') WHERE refresh_token_hash=?", (token_hash,))
        else:
            conn.execute("UPDATE mcp_oauth_tokens SET revoked_at=datetime('now', 'localtime') WHERE access_token_hash=?", (token_hash,))
        conn.commit()
    return {"ok": True}


@router.get("/connections")
def list_connections(user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, client_name, scopes, project_ids, created_at, last_used_at
               FROM mcp_oauth_connections WHERE username=? AND revoked_at IS NULL ORDER BY created_at DESC""",
            (user.username,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.delete("/connections/{connection_id}")
def revoke_connection(connection_id: int, user: CurrentUser = Depends(get_current_user)):
    with get_db() as conn:
        result = conn.execute(
            "UPDATE mcp_oauth_connections SET revoked_at=datetime('now', 'localtime') WHERE id=? AND username=? AND revoked_at IS NULL",
            (connection_id, user.username),
        )
        conn.commit()
    if result.rowcount == 0:
        raise HTTPException(404, detail="MCP connection not found")
    return {"ok": True}


@router.get("/mcp-auth", status_code=status.HTTP_204_NO_CONTENT)
def validate_mcp_transport(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="MCP OAuth authentication required")
    from ..auth import authenticate_mcp_token

    if not authenticate_mcp_token(authorization[7:]):
        raise HTTPException(status_code=401, detail="Invalid, expired, or revoked MCP token")
    return None
