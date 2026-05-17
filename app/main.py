import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import conversations as conversations_router
from app.config import get_settings
from app.db.bootstrap import ensure_database, run_migrations
from app.db.session import dispose_engine
from app.tools.seeker_client import dispose_seeker_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.google_api_key:
        os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)

    ensure_database()
    await asyncio.to_thread(run_migrations)

    yield
    await dispose_seeker_client()
    await dispose_engine()


app = FastAPI(title="seeker-ai", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
app.include_router(conversations_router.router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
