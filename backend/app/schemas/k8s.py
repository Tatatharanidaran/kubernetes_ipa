from pydantic import BaseModel


class PodInfo(BaseModel):
    name: str
    namespace: str
    status: str
    node_name: str | None
    pod_ip: str | None
    containers: list[str]


class DeploymentInfo(BaseModel):
    name: str
    namespace: str
    desired_replicas: int
    available_replicas: int
    ready_replicas: int


class KubernetesStatusResponse(BaseModel):
    namespace_filter: str | None
    pod_count: int
    deployment_count: int
    pods: list[PodInfo]
    deployments: list[DeploymentInfo]
