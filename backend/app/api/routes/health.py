from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_cache, get_qdrant_client
from app.core.cache import Cache
from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Kiểm tra API còn sống")
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=get_settings().app_version)


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    summary="Kiểm tra kết nối PostgreSQL, Qdrant, Redis",
    responses={503: {"model": HealthResponse, "description": "PostgreSQL không kết nối được"}},
)
def ready(
    response: Response, db: Session = Depends(get_db), cache: Cache = Depends(get_cache)
) -> HealthResponse:
    s = get_settings()
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["postgres"] = f"error: {e.__class__.__name__}"
    try:
        client = get_qdrant_client()
        has = client.collection_exists(s.qdrant_collection)
        checks["qdrant"] = "ok" if has else f"ok (chưa có collection '{s.qdrant_collection}')"
    except Exception as e:  # noqa: BLE001
        checks["qdrant"] = f"error: {e.__class__.__name__}"
    checks["redis"] = cache.ping()

    degraded = any(v.startswith("error") for v in checks.values())
    if checks["postgres"] != "ok":
        response.status_code = 503
    return HealthResponse(status="degraded" if degraded else "ok", version=s.app_version, checks=checks)
