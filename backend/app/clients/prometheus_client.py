import logging
import os
import asyncio
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class PrometheusClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0, retries: int = 2):
        self.base_url = (base_url or os.getenv("PROMETHEUS_URL", "http://localhost:9090")).rstrip("/")
        self.timeout = timeout
        self.retries = retries

    async def query_prometheus(self, promql: str) -> dict[str, Any]:
        endpoint = f"{self.base_url}/api/v1/query"
        for attempt in range(self.retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(endpoint, params={"query": promql})
                    response.raise_for_status()
                    payload = response.json()
                break
            except (httpx.HTTPError, ValueError) as exc:
                if attempt >= self.retries:
                    logger.exception("Prometheus query failed for promql='%s': %s", promql, exc)
                    return {}
                await asyncio.sleep(0.35 * (attempt + 1))
        else:
            return {}

        if payload.get("status") != "success":
            logger.error("Prometheus returned non-success for promql='%s': %s", promql, payload)
            return {}

        return payload.get("data", {})

    async def get_metric_value(self, metric_name: str) -> Optional[float]:
        data = await self.query_prometheus(metric_name)
        result = data.get("result", [])
        if not result:
            return None

        value = result[0].get("value")
        if not value or len(value) < 2:
            return None

        try:
            return float(value[1])
        except (TypeError, ValueError):
            return None
