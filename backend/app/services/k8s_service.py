import asyncio
import re
from datetime import datetime, timezone

from app.clients.kubernetes_client import KubernetesClient
from app.schemas.logs import PodLogsResponse


class K8sService:
    def __init__(self, kubernetes_client: KubernetesClient):
        self.kubernetes_client = kubernetes_client

    async def get_cluster_status(self, namespace: str = "default") -> dict:
        pods_raw, deployments_raw = await asyncio.gather(
            self.kubernetes_client.list_pods(namespace=namespace),
            self.kubernetes_client.list_deployments(namespace=namespace),
        )

        pods = []
        for pod in pods_raw:
            container_statuses = pod.status.container_statuses or []
            ready = bool(container_statuses) and all(status.ready for status in container_statuses)
            pods.append(
                {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "ready": ready,
                }
            )

        deployments = []
        for deployment in deployments_raw:
            deployments.append(
                {
                    "name": deployment.metadata.name,
                    "replicas": deployment.spec.replicas or 0,
                    "available": deployment.status.available_replicas or 0,
                }
            )

        return {
            "namespace": namespace,
            "pods": pods,
            "deployments": deployments,
        }

    async def get_pod_logs(
        self,
        pod_name: str,
        namespace: str,
        tail_lines: int,
    ) -> PodLogsResponse:
        logs = await self.kubernetes_client.get_pod_logs(
            pod_name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
        )

        return PodLogsResponse(
            pod_name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
            logs=logs,
        )

    async def get_scaling_events(self, namespace: str = "default", limit: int = 5) -> list[dict]:
        events = await self.kubernetes_client.list_events(
            namespace=namespace,
            field_selector="involvedObject.kind=Deployment",
        )

        by_deployment_last_new: dict[str, int] = {}
        timeline: list[dict] = []

        def event_ts(event) -> datetime:
            ts = (
                getattr(event, "event_time", None)
                or getattr(event, "last_timestamp", None)
                or getattr(event, "first_timestamp", None)
                or datetime.now(timezone.utc)
            )
            if ts.tzinfo is None:
                return ts.replace(tzinfo=timezone.utc)
            return ts

        events_sorted = sorted(events, key=event_ts)

        for event in events_sorted:
            reason = (event.reason or "").lower()
            message = event.message or ""
            deployment = event.involved_object.name if event.involved_object else None
            if not deployment:
                continue

            if "scaled" not in reason and "scaled" not in message.lower():
                continue

            match = re.search(r"to\s+(\d+)", message)
            if not match:
                continue

            new_replicas = int(match.group(1))
            old_replicas = by_deployment_last_new.get(deployment, max(new_replicas - 1, 0))
            by_deployment_last_new[deployment] = new_replicas

            action = "scale_up" if new_replicas > old_replicas else "scale_down"
            if new_replicas == old_replicas:
                action = "stable"

            timeline.append(
                {
                    "deployment": deployment,
                    "old_replicas": old_replicas,
                    "new_replicas": new_replicas,
                    "timestamp": event_ts(event).isoformat(),
                    "reason": action,
                }
            )

        return timeline[-limit:][::-1]
