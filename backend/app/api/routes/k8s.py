import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_k8s_service
from app.services.k8s_service import K8sService

router = APIRouter(prefix="/api/k8s", tags=["kubernetes"])
logger = logging.getLogger(__name__)


@router.get("/status")
async def get_k8s_status(
    namespace: str = Query(default="default"),
    service: K8sService = Depends(get_k8s_service),
):
    try:
        return await service.get_cluster_status(namespace=namespace)
    except Exception as exc:
        logger.exception("Failed to fetch Kubernetes status for namespace='%s': %s", namespace, exc)
        raise HTTPException(status_code=502, detail=f"Failed to fetch Kubernetes status: {exc}") from exc


@router.get("/scaling-events")
async def get_scaling_events(
    namespace: str = Query(default="default"),
    limit: int = Query(default=5, ge=1, le=50),
    service: K8sService = Depends(get_k8s_service),
):
    try:
        return await service.get_scaling_events(namespace=namespace, limit=limit)
    except Exception as exc:
        logger.exception(
            "Failed to fetch scaling events for namespace='%s': %s",
            namespace,
            exc,
        )
        raise HTTPException(status_code=502, detail=f"Failed to fetch scaling events: {exc}") from exc
