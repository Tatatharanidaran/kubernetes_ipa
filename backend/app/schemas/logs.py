from pydantic import BaseModel


class PodLogsResponse(BaseModel):
    pod_name: str
    namespace: str
    tail_lines: int
    logs: str
