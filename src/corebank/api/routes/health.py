from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response, status

from corebank import __version__
from corebank.infrastructure.database import check_database
from corebank.schemas.health import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger("corebank.health")


@router.get("/live", response_model=HealthResponse, summary="Liveness probe")
def live() -> HealthResponse:
    """Returns 200 as long as the process is running. No dependencies are checked."""
    return HealthResponse(status="ok", service="corebank-ledger", version=__version__)


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness probe",
    responses={503: {"model": HealthResponse, "description": "A dependency is unavailable"}},
)
def ready(request: Request, response: Response) -> HealthResponse:
    """Returns 200 only when the database answers a trivial query.

    No configuration or connection details are exposed, only ``ok``/``failed``.
    """
    checks: dict[str, str] = {}
    try:
        checks["database"] = "ok" if check_database(request.app.state.engine) else "failed"
    except Exception:
        logger.warning("readiness check failed")
        checks["database"] = "failed"
    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        service="corebank-ledger",
        version=__version__,
        checks=checks,
    )
