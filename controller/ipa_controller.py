import math
import requests
import kopf
from kubernetes import client, config
from datetime import datetime, timedelta

PREDICTOR_URL = "http://predictor.default.svc:8000/predict"
LLM_URL = "http://llm-decision-service.default.svc:5000/decide"

POLL_INTERVAL = 30
PREDICTOR_TIMEOUT = (3, 20)
LLM_TIMEOUT = (3, 15)

config.load_incluster_config()
apps_api = client.AppsV1Api()

LAST_SCALE_DOWN = {}

@kopf.timer(
    group="autoscaling.example.com",
    version="v1",
    plural="intelligentpodautoscalers",
    interval=POLL_INTERVAL,
)
def reconcile(spec, namespace, logger, **_):
    if not hasattr(reconcile, "_last_state"):
        reconcile._last_state = {}

    target = spec["targetRef"]["name"]

    dep = apps_api.read_namespaced_deployment(target, namespace)
    current = dep.spec.replicas

    min_r = spec.get("minReplicas", 1)
    max_r = spec.get("maxReplicas", 20)
    target_per_pod = spec["targetPerPod"]
    cooldown = spec.get("cooldownSeconds", 120)

    now = datetime.utcnow()

    # ------------------ Prediction ------------------
    try:
        r = requests.get(
            PREDICTOR_URL,
            params={
                "metric": spec["metric"],
                "lookback": spec["lookbackSeconds"],
                "horizon": spec["horizonSeconds"],
            },
            timeout=PREDICTOR_TIMEOUT,
        )
        r.raise_for_status()
        prediction = max(0.0, float(r.json()["prediction"]))
    except Exception as e:
        logger.error(f"[{target}] Predictor failed: {e}")
        return

    # --- SMART AUTOSCALER FIX START ---
    # ------------------ Threshold + hysteresis decision ------------------
    scale_step = max(1, int(spec.get("scaleStep", 1)))
    hysteresis_buffer = max(0.0, float(spec.get("hysteresisBuffer", 5)))

    high_threshold = float(current * target_per_pod)
    low_threshold = float(max(0, current - scale_step) * target_per_pod)
    upper_scale_threshold = high_threshold + hysteresis_buffer
    lower_scale_threshold = max(0.0, low_threshold - hysteresis_buffer)

    action = "stable"
    desired = current

    if prediction > upper_scale_threshold:
        action = "scale_up"
        desired = min(current + scale_step, max_r)
    elif prediction < lower_scale_threshold:
        action = "scale_down"
        desired = max(current - scale_step, min_r)

    # If already at limits, avoid misleading scale action.
    if desired == current:
        action = "stable"
    # --- SMART AUTOSCALER FIX END ---

    # ------------------ Cooldown (scale-down only) ------------------
    last_down = LAST_SCALE_DOWN.get(target)
    if action == "scale_down" and last_down:
        if now - last_down < timedelta(seconds=cooldown):
            desired = current
            action = "stable"

    # --- SMART AUTOSCALER FIX START ---
    if action == "scale_up":
        reason = (
            f"Scaling up: prediction {prediction:.2f} > upper threshold "
            f"{upper_scale_threshold:.2f}."
        )
    elif action == "scale_down":
        reason = (
            f"Scaling down: prediction {prediction:.2f} < lower threshold "
            f"{lower_scale_threshold:.2f}."
        )
    else:
        reason = (
            f"Stable: prediction {prediction:.2f} within hysteresis band "
            f"[{lower_scale_threshold:.2f}, {upper_scale_threshold:.2f}] "
            f"or bounded by replica limits."
        )

    logger.info(
        f"[DEBUG] prediction={prediction:.2f} current={current} desired={desired} decision={action}"
    )
    # --- SMART AUTOSCALER FIX END ---

    # ------------------ Ask LLM for explanation ONLY ------------------
    try:
        llm_resp = requests.post(
            LLM_URL,
            json={
                "action": action,
                "prediction": prediction,
                "current": current,
                "desired": desired,
            },
            timeout=LLM_TIMEOUT,
        )
        llm_resp.raise_for_status()
        llm_reason = llm_resp.json().get("reason")
        if llm_reason:
            reason = f"{reason} | LLM note: {llm_reason}"
    except Exception as e:
        logger.warning(f"[{target}] LLM unavailable: {e}")
        # LLM is optional, NEVER critical

    # ------------------ Log (reduce stable-no-change noise) ------------------
    last_state = reconcile._last_state.get(target, {"action": None, "replicas": None})
    should_log = True

    if action == "stable" and desired == current:
        if last_state["action"] == action and last_state["replicas"] == desired:
            should_log = False

    # Always log critical scaling decisions with full reasoning.
    if action in ("scale_up", "scale_down"):
        should_log = True

    if should_log:
        logger.info(
            f"[{target}] action={action} "
            f"prediction={prediction:.2f} "
            f"current={current} desired={desired} "
            f"reason={reason}"
        )

    # ------------------ Apply scaling ------------------
    if desired != current:
        dep.spec.replicas = desired
        patched = False

        for attempt in range(3):
            try:
                apps_api.patch_namespaced_deployment(target, namespace, dep)
                patched = True
                break
            except client.rest.ApiException as e:
                if e.status == 409:
                    logger.warning(
                        f"[{target}] Deployment modified concurrently, retrying with latest version..."
                    )
                    dep = apps_api.read_namespaced_deployment(target, namespace)
                    dep.spec.replicas = desired
                    continue
                raise

        if not patched:
            logger.error(f"[{target}] Failed to patch deployment after retries.")
            return

        if desired < current:
            LAST_SCALE_DOWN[target] = now

        logger.info(f"[{target}] Scaled {current} → {desired}")

    reconcile._last_state[target] = {"action": action, "replicas": desired}
