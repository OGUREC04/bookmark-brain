from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.bookmarks import router as bookmarks_router
from app.api.folders import router as folders_router
from app.api.reminders import router as reminders_router
from app.api.search import router as search_router
from app.api.users import router as users_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    from app.database import engine
    await engine.dispose()


app = FastAPI(
    title="BookmarkBrain API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — explicit origins, not ["*"] with credentials (browsers block that combo)
_cors_origins = (
    ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000"]
    if settings.ENVIRONMENT == "development"
    else []
)
if settings.MINI_APP_URL:
    _cors_origins.append(settings.MINI_APP_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(users_router)
app.include_router(bookmarks_router)
app.include_router(folders_router)
app.include_router(reminders_router)
app.include_router(search_router)


@app.get("/health")
async def health():
    """Health check with Postgres and Redis connectivity."""
    import redis.asyncio as aioredis
    from sqlalchemy import text as sa_text

    checks: dict[str, str] = {}

    # Postgres
    try:
        from app.database import async_session
        async with async_session() as session:
            await session.execute(sa_text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {e}"

    # Redis
    try:
        r = aioredis.from_url(settings.REDIS_URL)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=status_code,
    )
