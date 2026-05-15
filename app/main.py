from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(title="seeker-ai", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}
