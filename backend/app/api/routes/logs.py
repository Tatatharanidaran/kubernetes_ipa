from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_k8s_service
from app.core.config import Settings, get_settings
from app.schemas.logs import PodLogsResponse
from app.services.k8s_service import K8sService

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/{pod_name}", response_model=PodLogsResponse)
async def get_pod_logs(
    pod_name: str,
    namespace: str | None = Query(default=None),
    tail_lines: int = Query(default=200, ge=1, le=5000),
    settings: Settings = Depends(get_settings),
    service: K8sService = Depends(get_k8s_service),
):
    target_namespace = namespace or settings.default_namespace
    try:
        return await service.get_pod_logs(
            pod_name=pod_name,
            namespace=target_namespace,
            tail_lines=tail_lines,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch pod logs: {exc}") from exc
