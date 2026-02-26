import logging

import httpx
from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/api/health", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/grafana")
async def grafana_health() -> dict:
    settings = get_settings()
    grafana_url = settings.grafana_url.rstrip("/")
    candidates = [f"{grafana_url}/api/health"]

    # Local fallback for dev mode when backend is run outside the cluster.
    if ".svc" in grafana_url:
        candidates.append("http://localhost:3000/api/health")

    for endpoint in candidates:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(endpoint)
                if response.status_code == 200:
                    payload = response.json()
                    if payload.get("database") == "ok":
                        return {"status": "ok", "grafana_url": endpoint.rsplit("/api/health", 1)[0]}
        except Exception as exc:
            logger.warning("Grafana health check failed for %s: %s", endpoint, exc)

    return {"status": "down"}
