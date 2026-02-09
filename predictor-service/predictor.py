from flask import Flask, request, jsonify, Response
import pandas as pd
from prophet import Prophet
from prometheus_api_client import PrometheusConnect
from datetime import datetime, timedelta
import os
import numpy as np
import time
import requests
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

PROM_URL = os.environ.get(
    "PROM_URL",
    "http://monitoring-kube-prometheus-prometheus.monitoring.svc:9090"
)
PREDICTION_SUCCESS_THRESHOLD_PCT = float(
    os.environ.get("PREDICTION_SUCCESS_THRESHOLD_PCT", "0.2")
)

app = Flask(__name__)
prom = PrometheusConnect(url=PROM_URL, disable_ssl=True)

# --- Prometheus metrics for predictions ---
PREDICTION = Gauge(
    "ipa_prediction",
    "Predicted requests per second",
    ["metric"]
)
PREDICTION_LOW = Gauge(
    "ipa_prediction_low",
    "Prediction lower bound",
    ["metric"]
)
PREDICTION_HIGH = Gauge(
    "ipa_prediction_high",
    "Prediction upper bound",
    ["metric"]
)
PREDICTION_FALLBACK = Gauge(
    "ipa_prediction_fallback",
    "1 if predictor returned fallback",
    ["metric"]
)
PREDICTION_LAST_SUCCESS = Gauge(
    "ipa_prediction_last_accuracy_success_timestamp",
    "Unix timestamp of last accurate prediction",
    ["metric"]
)
PREDICTION_LAST_FAILURE = Gauge(
    "ipa_prediction_last_accuracy_failure_timestamp",
    "Unix timestamp of last inaccurate prediction",
    ["metric"]
)
PREDICTION_LAST_PREDICTION = Gauge(
    "ipa_prediction_last_prediction_timestamp",
    "Unix timestamp of last computed prediction",
    ["metric"]
)
PREDICTION_ACCURACY_ERROR = Gauge(
    "ipa_prediction_accuracy_error",
    "Absolute percent error between predicted and actual",
    ["metric"]
)
PREDICTION_ACCURACY_SUCCESS = Gauge(
    "ipa_prediction_accuracy_success",
    "1 if prediction was within threshold, else 0",
    ["metric"]
)

PENDING_PREDICTIONS = []


def _record_metrics(metric, prediction, low, high, fallback):
    PREDICTION.labels(metric=metric).set(prediction)
    PREDICTION_LOW.labels(metric=metric).set(low)
    PREDICTION_HIGH.labels(metric=metric).set(high)
    PREDICTION_FALLBACK.labels(metric=metric).set(1 if fallback else 0)
    if not fallback:
        PREDICTION_LAST_PREDICTION.labels(metric=metric).set(time.time())


def _enqueue_prediction(metric, prediction, horizon):
    PENDING_PREDICTIONS.append({
        "metric": metric,
        "prediction": prediction,
        "target_time": time.time() + horizon
    })
    # Prevent unbounded growth
    if len(PENDING_PREDICTIONS) > 200:
        del PENDING_PREDICTIONS[:100]


def _query_actual(metric, ts):
    try:
        resp = requests.get(
            f"{PROM_URL}/api/v1/query",
            params={"query": metric, "time": ts},
            timeout=5
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "success":
            return None
        result = payload.get("data", {}).get("result", [])
        if not result:
            return None
        value = result[0].get("value", [None, None])[1]
        if value is None:
            return None
        actual = float(value)
        if not np.isfinite(actual):
            return None
        return actual
    except Exception:
        return None


def _evaluate_pending():
    if not PENDING_PREDICTIONS:
        return

    now = time.time()
    ready = [p for p in PENDING_PREDICTIONS if p["target_time"] <= now]
    if not ready:
        return

    # Keep future predictions
    PENDING_PREDICTIONS[:] = [p for p in PENDING_PREDICTIONS if p["target_time"] > now]

    for p in ready:
        metric = p["metric"]
        predicted = p["prediction"]
        actual = _query_actual(metric, p["target_time"])
        if actual is None:
            PREDICTION_ACCURACY_SUCCESS.labels(metric=metric).set(0)
            PREDICTION_LAST_FAILURE.labels(metric=metric).set(time.time())
            continue

        denom = max(abs(actual), 1.0)
        error_pct = abs(predicted - actual) / denom
        PREDICTION_ACCURACY_ERROR.labels(metric=metric).set(error_pct)

        if error_pct <= PREDICTION_SUCCESS_THRESHOLD_PCT:
            PREDICTION_ACCURACY_SUCCESS.labels(metric=metric).set(1)
            PREDICTION_LAST_SUCCESS.labels(metric=metric).set(time.time())
        else:
            PREDICTION_ACCURACY_SUCCESS.labels(metric=metric).set(0)
            PREDICTION_LAST_FAILURE.labels(metric=metric).set(time.time())


def _safe_fallback(metric, horizon, reason):
    _record_metrics(metric, 0.0, 0.0, 0.0, fallback=True)
    return jsonify({
        "metric": metric,
        "prediction": 0.0,
        "low": 0.0,
        "high": 0.0,
        "horizon_seconds": horizon,
        "model": "fallback",
        "fallback": True,
        "reason": reason
    }), 200


@app.route("/health")
def health():
    return "ok", 200


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route("/predict", methods=["GET"])
def predict():
    metric = request.args.get("metric", "rate(http_requests_total[1m])")
    lookback = int(request.args.get("lookback", 1800))
    horizon = int(request.args.get("horizon", 300))

    # Evaluate any predictions whose horizon has passed.
    _evaluate_pending()

    try:
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=lookback)

        result = prom.custom_query_range(
            query=metric,
            start_time=start_time,
            end_time=end_time,
            step="30s"
        )

        # ---------- HARD GUARDS ----------
        if not result:
            return _safe_fallback(metric, horizon, "empty_result")

        values = result[0].get("values", [])
        if len(values) < 5:
            return _safe_fallback(metric, horizon, "insufficient_points")

        df = pd.DataFrame(values, columns=["ds", "y"])
        df["ds"] = pd.to_datetime(df["ds"], unit="s")
        df["y"] = pd.to_numeric(df["y"], errors="coerce")

        df.dropna(inplace=True)

        if df.empty:
            return _safe_fallback(metric, horizon, "nan_series")

        if np.isclose(df["y"].std(), 0.0):
            return _safe_fallback(metric, horizon, "no_variance")

        # ---------- PROPHET ----------
        model = Prophet(
            interval_width=0.9,
            daily_seasonality=False,
            weekly_seasonality=False
        )

        model.fit(df)

        periods = max(1, int(horizon / 30))
        future = model.make_future_dataframe(periods=periods, freq="30s")
        forecast = model.predict(future)

        pred = forecast.iloc[-1]

        yhat = float(pred["yhat"])
        if not np.isfinite(yhat):
            return _safe_fallback(metric, horizon, "invalid_prediction")

        low = float(pred["yhat_lower"])
        high = float(pred["yhat_upper"])
        _record_metrics(metric, yhat, low, high, fallback=False)
        _enqueue_prediction(metric, yhat, horizon)

        return jsonify({
            "metric": metric,
            "prediction": yhat,
            "low": low,
            "high": high,
            "horizon_seconds": horizon,
            "model": "prophet",
            "fallback": False
        }), 200

    except Exception as e:
        return _safe_fallback(metric, horizon, f"exception:{str(e)}")
