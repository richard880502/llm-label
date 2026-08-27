from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout

from .annotation.migrations import ensure_annotation_schema_columns
from .auth import get_current_user
from .database import init_db
from .routers import export, projects, rows
from .routers import auth as auth_router
from .routers import oauth as oauth_router
from .routers import presence as presence_router
from .routers import schemas as schemas_router
from .routers import tasks as tasks_router
from .routers import users as users_router

app = FastAPI(title="Annotation Review Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(PoolTimeout)
async def pool_timeout_handler(request: Request, exc: PoolTimeout) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is busy, please retry shortly."},
    )


@app.on_event("startup")
def on_startup():
    init_db()
    ensure_annotation_schema_columns()


app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(oauth_router.router, prefix="/api/oauth", tags=["oauth"])
app.include_router(
    users_router.router,
    prefix="/api/users",
    tags=["users"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    projects.router,
    prefix="/api/projects",
    tags=["projects"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    schemas_router.router,
    prefix="/api/projects",
    tags=["schemas"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    rows.router,
    prefix="/api/projects",
    tags=["rows"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    export.router,
    prefix="/api/projects",
    tags=["export"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    tasks_router.router,
    prefix="/api/projects",
    tags=["tasks"],
    dependencies=[Depends(get_current_user)],
)
app.include_router(
    presence_router.router,
    prefix="/api/projects",
    tags=["presence"],
    dependencies=[Depends(get_current_user)],
)


def _public_origin(request: Request) -> str:
    """Use the externally visible origin when TLS terminates at a proxy."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    return f"{proto}://{host}"


@app.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
@app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
def oauth_protected_resource_metadata(request: Request):
    origin = _public_origin(request)
    return {
        "resource": f"{origin}/mcp",
        "authorization_servers": [origin],
        "scopes_supported": [
            "projects:read", "rows:read", "tasks:read", "tasks:run", "rows:write",
            "reviews:approve", "reviews:batch_approve", "offline_access",
        ],
        "bearer_methods_supported": ["header"],
    }


@app.get("/.well-known/oauth-authorization-server", include_in_schema=False)
def oauth_authorization_server_metadata(request: Request):
    origin = _public_origin(request)
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/authorize",
        "token_endpoint": f"{origin}/api/oauth/token",
        "registration_endpoint": f"{origin}/api/oauth/register",
        "revocation_endpoint": f"{origin}/api/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [
            "projects:read", "rows:read", "tasks:read", "tasks:run", "rows:write",
            "reviews:approve", "reviews:batch_approve", "offline_access",
        ],
    }

static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    assets_path = static_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(str(static_path / "index.html"))
