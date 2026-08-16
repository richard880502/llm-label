from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout

from .auth import get_current_user
from .database import init_db
from .routers import export, projects, rows
from .routers import auth as auth_router
from .routers import tasks as tasks_router
from .routers import users as users_router
from .routers import presence as presence_router

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


app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
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

static_path = Path(__file__).parent.parent / "static"
if static_path.exists():
    assets_path = static_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        return FileResponse(str(static_path / "index.html"))
