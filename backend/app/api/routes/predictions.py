from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_prediction_service
from app.services.prediction_service import PredictionService

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("")
async def get_predictions(service: PredictionService = Depends(get_prediction_service)):
    try:
        return await service.get_prediction_metrics()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch predictions: {exc}") from exc
