import asyncio
import re
from datetime import datetime, timezone

from kubernetes import client

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

    async def get_auto_load_status(self, namespace: str = "default") -> dict:
        deployment = await self.kubernetes_client.get_deployment(namespace=namespace, name="loadgen-auto")
        if deployment is None:
            return {
                "enabled": False,
                "exists": False,
                "replicas": 0,
                "namespace": namespace,
            }

        replicas = deployment.spec.replicas or 0
        return {
            "enabled": replicas > 0,
            "exists": True,
            "replicas": replicas,
            "namespace": namespace,
        }

    async def set_auto_load(self, enabled: bool, namespace: str = "default") -> dict:
        deployment = await self.kubernetes_client.get_deployment(namespace=namespace, name="loadgen-auto")

        if deployment is None:
            deployment_body = self._build_loadgen_auto_deployment(namespace)
            await self.kubernetes_client.create_deployment(namespace=namespace, body=deployment_body)

        desired_replicas = 1 if enabled else 0
        await self.kubernetes_client.scale_deployment(
            namespace=namespace,
            name="loadgen-auto",
            replicas=desired_replicas,
        )

        return await self.get_auto_load_status(namespace=namespace)

    @staticmethod
    def _build_loadgen_auto_deployment(namespace: str) -> client.V1Deployment:
        labels = {"app": "loadgen-auto"}
        container = client.V1Container(
            name="loadgen-auto",
            image="busybox:1.36",
            image_pull_policy="IfNotPresent",
            command=[
                "sh",
                "-c",
                (
                    "target_url='http://js-app."
                    + namespace
                    + ".svc.cluster.local:8080'; "
                    "while true; do "
                    "for i in $(seq 1 200); do wget -qO- \"$target_url\" >/dev/null & done; "
                    "wait; sleep 1; "
                    "done"
                ),
            ],
            readiness_probe=client.V1Probe(
                _exec=client.V1ExecAction(
                    command=[
                        "sh",
                        "-c",
                        f"wget -qO- http://js-app.{namespace}.svc.cluster.local:8080 >/dev/null 2>&1",
                    ]
                ),
                initial_delay_seconds=5,
                period_seconds=5,
                timeout_seconds=2,
                failure_threshold=6,
            ),
        )

        pod_spec = client.V1PodSpec(
            restart_policy="Always",
            containers=[container],
        )

        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=labels),
            spec=pod_spec,
        )

        deployment_spec = client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels=labels),
            template=pod_template,
        )

        return client.V1Deployment(
            api_version="apps/v1",
            kind="Deployment",
            metadata=client.V1ObjectMeta(name="loadgen-auto", namespace=namespace, labels=labels),
            spec=deployment_spec,
        )
