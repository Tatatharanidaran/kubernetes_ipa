from functools import lru_cache

from app.clients.kubernetes_client import KubernetesClient
from app.clients.prometheus_client import PrometheusClient
from app.core.config import get_settings
from app.services.k8s_service import K8sService
from app.services.prediction_service import PredictionService


@lru_cache
def get_prometheus_client() -> PrometheusClient:
    settings = get_settings()
    return PrometheusClient(settings.prometheus_url)


@lru_cache
def get_kubernetes_client() -> KubernetesClient:
    return KubernetesClient()


@lru_cache
def get_prediction_service() -> PredictionService:
    return PredictionService(get_prometheus_client())


@lru_cache
def get_k8s_service() -> K8sService:
    return K8sService(get_kubernetes_client())
