import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.clients.prometheus_client import PrometheusClient

logger = logging.getLogger(__name__)

SAFE_DEFAULTS = {
    "prediction": 0.0,
    "actual_load": 0.0,
    "low": 0.0,
    "high": 0.0,
    "fallback": 1,
    "last_success": 0.0,
}


class PredictionService:
    def __init__(self, prometheus_client: PrometheusClient):
        self.prometheus_client = prometheus_client
        self._last_good_metrics: dict[str, float | int] = SAFE_DEFAULTS.copy()

    async def get_prediction_metrics(self) -> dict[str, float | int]:
        queries = {
            # Aggregate across metric-label series so we don't pick an arbitrary stale series.
            "prediction": "max(ipa_prediction)",
            "actual_load": "(sum(rate(http_requests_total{route=\"/\"}[1m])) or max(js_app_requests_per_second))",
            "low": "max(ipa_prediction_low)",
            "high": "max(ipa_prediction_high)",
            "fallback": "max(ipa_prediction_fallback)",
            # Support both metric names (legacy/new) exposed by predictor versions.
            "last_success": "max((ipa_prediction_last_success_timestamp or ipa_prediction_last_accuracy_success_timestamp))",
        }

        results = await asyncio.gather(
            *(self.prometheus_client.query_prometheus(promql) for promql in queries.values())
        )

        metrics: dict[str, float | int] = SAFE_DEFAULTS.copy()
        unavailable_count = 0
        missing_keys: list[str] = []

        for key, data in zip(queries.keys(), results):
            value = self._extract_value(data)
            if value is None:
                unavailable_count += 1
                missing_keys.append(key)
                if key in self._last_good_metrics:
                    metrics[key] = self._last_good_metrics[key]
                continue
            metrics[key] = int(value) if key == "fallback" else float(value)

        for key in ("prediction", "actual_load", "low", "high", "last_success"):
            if key in metrics:
                metrics[key] = round(float(metrics[key]), 2)

        for key in ("prediction", "low", "high"):
            metrics[key] = max(0.0, float(metrics[key]))

        if unavailable_count > 0:
            logger.warning(
                "Some Prometheus metrics were unavailable (%s/%s). Missing: %s. Using safe defaults for missing values.",
                unavailable_count,
                len(queries),
                ", ".join(missing_keys),
            )

            core_metric_missing = any(
                key in {"prediction", "low", "high", "fallback"} for key in missing_keys
            )
            if core_metric_missing:
                logger.warning("Prometheus core metrics missing – predictor running in fallback mode.")
        else:
            self._last_good_metrics = metrics.copy()

        if unavailable_count > 0:
            for key in queries.keys():
                if key not in missing_keys:
                    self._last_good_metrics[key] = metrics[key]
        return metrics

    async def get_predictions(self) -> dict[str, Any]:
        metrics = await self.get_prediction_metrics()
        last_success_iso = None
        if metrics["last_success"] > 0:
            last_success_iso = datetime.fromtimestamp(
                float(metrics["last_success"]), tz=timezone.utc
            ).isoformat()

        return {
            "ipa_prediction": metrics["prediction"],
            "actual_load": metrics["actual_load"],
            "ipa_prediction_low": metrics["low"],
            "ipa_prediction_high": metrics["high"],
            "ipa_prediction_fallback": bool(int(metrics["fallback"])),
            "ipa_prediction_fallback_raw": metrics["fallback"],
            "last_success_timestamp": metrics["last_success"],
            "last_success_iso": last_success_iso,
        }

    @staticmethod
    def _extract_value(data: dict[str, Any]) -> float | None:
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
