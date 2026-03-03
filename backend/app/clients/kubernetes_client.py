import logging
from pathlib import Path
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

logger = logging.getLogger(__name__)


class KubernetesClient:
    def __init__(self):
        self._initialized = False
        self._core_v1: Optional[client.CoreV1Api] = None
        self._apps_v1: Optional[client.AppsV1Api] = None

    def _load_config(self) -> None:
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config")
        except config.ConfigException:
            kubeconfig = str(Path.home() / ".kube" / "config")
            config.load_kube_config(config_file=kubeconfig)
            logger.info("Loaded local Kubernetes config from %s", kubeconfig)

        self._core_v1 = client.CoreV1Api()
        self._apps_v1 = client.AppsV1Api()
        self._initialized = True

    async def _ensure_initialized(self) -> None:
        if not self._initialized:
            await run_in_threadpool(self._load_config)

    async def list_pods(self, namespace: str) -> list[client.V1Pod]:
        await self._ensure_initialized()
        pod_list = await run_in_threadpool(self._core_v1.list_namespaced_pod, namespace)
        return pod_list.items

    async def list_deployments(self, namespace: str) -> list[client.V1Deployment]:
        await self._ensure_initialized()
        deployment_list = await run_in_threadpool(
            self._apps_v1.list_namespaced_deployment, namespace
        )
        return deployment_list.items

    async def get_pod_logs(
        self,
        pod_name: str,
        namespace: str,
        tail_lines: int = 200,
    ) -> str:
        await self._ensure_initialized()
        return await run_in_threadpool(
            self._core_v1.read_namespaced_pod_log,
            name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
        )

    async def list_events(
        self,
        namespace: str,
        field_selector: str | None = None,
    ) -> list[object]:
        await self._ensure_initialized()
        event_list = await run_in_threadpool(
            self._core_v1.list_namespaced_event,
            namespace,
            field_selector=field_selector,
        )
        return event_list.items

    async def get_deployment(self, namespace: str, name: str) -> client.V1Deployment | None:
        await self._ensure_initialized()
        try:
            return await run_in_threadpool(
                self._apps_v1.read_namespaced_deployment,
                name,
                namespace,
            )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    async def create_deployment(
        self,
        namespace: str,
        body: client.V1Deployment,
    ) -> client.V1Deployment:
        await self._ensure_initialized()
        return await run_in_threadpool(
            self._apps_v1.create_namespaced_deployment,
            namespace,
            body,
        )

    async def scale_deployment(self, namespace: str, name: str, replicas: int) -> None:
        await self._ensure_initialized()
        scale_body = {"spec": {"replicas": replicas}}
        await run_in_threadpool(
            self._apps_v1.patch_namespaced_deployment_scale,
            name,
            namespace,
            scale_body,
        )
