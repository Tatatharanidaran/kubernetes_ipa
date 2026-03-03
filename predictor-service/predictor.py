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
PROM_QUERY_RETRIES = int(os.environ.get("PROM_QUERY_RETRIES", "3"))
PROM_QUERY_BACKOFF_SECONDS = float(os.environ.get("PROM_QUERY_BACKOFF_SECONDS", "0.5"))
FALLBACK_FAILURE_THRESHOLD = int(os.environ.get("FALLBACK_FAILURE_THRESHOLD", "3"))
PREDICTION_MAX_MULTIPLIER = float(os.environ.get("PREDICTION_MAX_MULTIPLIER", "1.6"))
PREDICTION_ABSOLUTE_HEADROOM = float(os.environ.get("PREDICTION_ABSOLUTE_HEADROOM", "20"))
PREDICTION_SMOOTHING_ALPHA = float(os.environ.get("PREDICTION_SMOOTHING_ALPHA", "0.35"))
DEFAULT_METRIC_LABEL = os.environ.get(
    "DEFAULT_METRIC_LABEL",
    'sum(rate(http_requests_total{route="/"}[1m]))',
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
CONSECUTIVE_FAILURES = {}
LAST_GOOD_PREDICTIONS = {}
LAST_PUBLISHED_PREDICTIONS = {}


def _clamp_non_negative(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _sanitize_prediction_bounds(prediction, low, high):
    prediction = _clamp_non_negative(prediction)
    low = _clamp_non_negative(low)
    high = _clamp_non_negative(high)

    if low > prediction:
        low = prediction
    if high < prediction:
        high = prediction

    return prediction, low, high


def _stabilize_prediction(metric, prediction, low, high, latest_actual):
    raw_prediction = _clamp_non_negative(prediction)
    stabilized = raw_prediction
    low = _clamp_non_negative(low)
    high = _clamp_non_negative(high)

    # Prevent extreme overshoot versus current observed load.
    if latest_actual is not None and np.isfinite(latest_actual):
        latest = _clamp_non_negative(latest_actual)
        cap = max(latest * PREDICTION_MAX_MULTIPLIER, latest + PREDICTION_ABSOLUTE_HEADROOM)
        stabilized = min(stabilized, cap)

    # Smooth point-to-point jumps with EMA to reduce sawtooth spikes.
    prev = LAST_PUBLISHED_PREDICTIONS.get(metric)
    if prev is not None and np.isfinite(prev):
        alpha = min(max(PREDICTION_SMOOTHING_ALPHA, 0.0), 1.0)
        stabilized = alpha * stabilized + (1.0 - alpha) * float(prev)

    # Keep interval magnitude aligned with stabilized center.
    if raw_prediction > 0:
        ratio = stabilized / raw_prediction
        low *= ratio
        high *= ratio
    else:
        low = min(low, stabilized)
        high = max(high, stabilized)

    stabilized, low, high = _sanitize_prediction_bounds(stabilized, low, high)
    LAST_PUBLISHED_PREDICTIONS[metric] = stabilized
    return stabilized, low, high


def _record_metrics(metric, prediction, low, high, fallback):
    prediction, low, high = _sanitize_prediction_bounds(prediction, low, high)
    PREDICTION.labels(metric=metric).set(prediction)
    PREDICTION_LOW.labels(metric=metric).set(low)
    PREDICTION_HIGH.labels(metric=metric).set(high)
    PREDICTION_FALLBACK.labels(metric=metric).set(1 if fallback else 0)
    if not fallback:
        PREDICTION_LAST_PREDICTION.labels(metric=metric).set(time.time())


def _mark_success(metric, prediction, low, high, model):
    prediction, low, high = _sanitize_prediction_bounds(prediction, low, high)
    CONSECUTIVE_FAILURES[metric] = 0
    LAST_GOOD_PREDICTIONS[metric] = {
        "prediction": float(prediction),
        "low": float(low),
        "high": float(high),
        "model": model,
        "updated_at": time.time(),
    }


def _init_metrics():
    # Ensure timeseries exist on startup so Prometheus queries don't return empty vectors
    # before the first /predict request is served   .
    _record_metrics(DEFAULT_METRIC_LABEL, 0.0, 0.0, 0.0, fallback=True)
    PREDICTION_ACCURACY_SUCCESS.labels(metric=DEFAULT_METRIC_LABEL).set(0)
    PREDICTION_ACCURACY_ERROR.labels(metric=DEFAULT_METRIC_LABEL).set(0.0)
    PREDICTION_LAST_SUCCESS.labels(metric=DEFAULT_METRIC_LABEL).set(0)
    PREDICTION_LAST_FAILURE.labels(metric=DEFAULT_METRIC_LABEL).set(0)


def _query_range_with_retries(metric, start_time, end_time, step):
    last_error = None
    for attempt in range(1, PROM_QUERY_RETRIES + 1):
        try:
            return prom.custom_query_range(
                query=metric,
                start_time=start_time,
                end_time=end_time,
                step=step,
            )
        except Exception as exc:
            last_error = exc
            app.logger.warning(
                "Prometheus query attempt %s/%s failed for metric='%s': %s",
                attempt,
                PROM_QUERY_RETRIES,
                metric,
                exc,
            )
            if attempt < PROM_QUERY_RETRIES:
                time.sleep(PROM_QUERY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    raise last_error if last_error is not None else RuntimeError("unknown_prometheus_query_failure")


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
    except Exception as e:
        app.logger.warning("Failed actual-value query for metric='%s' at ts=%s: %s", metric, ts, e)
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
    app.logger.warning(
        "Fallback prediction used for metric='%s' horizon=%ss reason=%s",
        metric,
        horizon,
        reason,
    )
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


def _graceful_failure(metric, horizon, reason):
    streak = CONSECUTIVE_FAILURES.get(metric, 0) + 1
    CONSECUTIVE_FAILURES[metric] = streak

    if streak < FALLBACK_FAILURE_THRESHOLD:
        cached = LAST_GOOD_PREDICTIONS.get(metric)
        if cached:
            app.logger.warning(
                "Prometheus data unavailable for metric='%s' (failure streak %s/%s). "
                "Serving cached prediction.",
                metric,
                streak,
                FALLBACK_FAILURE_THRESHOLD,
            )
            _record_metrics(
                metric,
                cached["prediction"],
                cached["low"],
                cached["high"],
                fallback=False,
            )
            return jsonify({
                "metric": metric,
                "prediction": cached["prediction"],
                "low": cached["low"],
                "high": cached["high"],
                "horizon_seconds": horizon,
                "model": f"cached:{cached.get('model', 'unknown')}",
                "fallback": False,
                "reason": f"{reason}:transient_failure_{streak}",
            }), 200

        app.logger.warning(
            "Prometheus data unavailable for metric='%s' (failure streak %s/%s). "
            "No cached prediction available yet.",
            metric,
            streak,
            FALLBACK_FAILURE_THRESHOLD,
        )
        _record_metrics(metric, 0.0, 0.0, 0.0, fallback=False)
        return jsonify({
            "metric": metric,
            "prediction": 0.0,
            "low": 0.0,
            "high": 0.0,
            "horizon_seconds": horizon,
            "model": "grace",
            "fallback": False,
            "reason": f"{reason}:transient_failure_{streak}",
        }), 200

    return _safe_fallback(
        metric,
        horizon,
        f"{reason}:failure_streak_{streak}",
    )


def _baseline_prediction(metric, horizon, value, reason):
    yhat = _clamp_non_negative(value)
    low = _clamp_non_negative(yhat * 0.9)
    high = _clamp_non_negative(yhat * 1.1)
    yhat, low, high = _stabilize_prediction(metric, yhat, low, high, yhat)
    app.logger.info(
        "Baseline prediction used for metric='%s' horizon=%ss reason=%s value=%.4f",
        metric,
        horizon,
        reason,
        yhat,
    )
    _record_metrics(metric, yhat, low, high, fallback=False)
    _mark_success(metric, yhat, low, high, "baseline")
    _enqueue_prediction(metric, yhat, horizon)
    return jsonify({
        "metric": metric,
        "prediction": yhat,
        "low": low,
        "high": high,
        "horizon_seconds": horizon,
        "model": "baseline",
        "fallback": False,
        "reason": reason
    }), 200


@app.route("/health")
def health():
    return "ok", 200


@app.route("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


_init_metrics()
app.logger.info("Predictor Prometheus source URL: %s", PROM_URL)
print("Prometheus metrics endpoint ready at /metrics", flush=True)


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

        result = _query_range_with_retries(
            metric=metric,
            start_time=start_time,
            end_time=end_time,
            step="30s",
        )

        # ---------- HARD GUARDS ----------
        if not result:
            return _graceful_failure(metric, horizon, "empty_result")

        values = result[0].get("values", [])
        if len(values) < 5:
            if values:
                latest = pd.to_numeric(values[-1][1], errors="coerce")
                if pd.notna(latest):
                    return _baseline_prediction(metric, horizon, float(latest), "insufficient_points")
            return _graceful_failure(metric, horizon, "insufficient_points")

        df = pd.DataFrame(values, columns=["ds", "y"])
        df["ds"] = pd.to_datetime(df["ds"], unit="s")
        df["y"] = pd.to_numeric(df["y"], errors="coerce")

        df.dropna(inplace=True)

        if df.empty:
            return _graceful_failure(metric, horizon, "nan_series")

        if np.isclose(df["y"].std(), 0.0):
            return _baseline_prediction(metric, horizon, float(df["y"].iloc[-1]), "no_variance")

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

        yhat = _clamp_non_negative(pred["yhat"])
        if not np.isfinite(yhat):
            return _graceful_failure(metric, horizon, "invalid_prediction")

        low = _clamp_non_negative(pred["yhat_lower"])
        high = _clamp_non_negative(pred["yhat_upper"])
        latest_actual = float(df["y"].iloc[-1]) if not df.empty else None
        yhat, low, high = _stabilize_prediction(metric, yhat, low, high, latest_actual)
        _record_metrics(metric, yhat, low, high, fallback=False)
        _mark_success(metric, yhat, low, high, "prophet")
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
        return _graceful_failure(metric, horizon, f"exception:{str(e)}")
