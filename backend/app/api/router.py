from fastapi import APIRouter

from app.api.routes import health, k8s, logs, predictions

api_router = APIRouter()
api_router.include_router(predictions.router)
api_router.include_router(k8s.router)
api_router.include_router(logs.router)
api_router.include_router(health.router)
