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

    # ------------------ Math decision (TRUTH) ------------------
    desired = math.ceil(prediction / target_per_pod)
    desired = max(min_r, min(max_r, desired))

    action = "stable"
    if desired > current:
        action = "scale_up"
    elif desired < current:
        action = "scale_down"

    # ------------------ Cooldown (scale-down only) ------------------
    last_down = LAST_SCALE_DOWN.get(target)
    if action == "scale_down" and last_down:
        if now - last_down < timedelta(seconds=cooldown):
            desired = current
            action = "stable"

    # ------------------ Ask LLM for explanation ONLY ------------------
    reason = f"Math-based decision: {prediction:.2f} rps / {target_per_pod} per pod"

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
        reason = llm_resp.json()["reason"]
    except Exception as e:
        logger.warning(f"[{target}] LLM unavailable: {e}")
        # LLM is optional, NEVER critical

    # ------------------ Log ------------------
    logger.info(
        f"[{target}] action={action} "
        f"prediction={prediction:.2f} "
        f"current={current} desired={desired} "
        f"reason={reason}"
    )

    # ------------------ Apply scaling ------------------
    if desired != current:
        dep.spec.replicas = desired
        apps_api.patch_namespaced_deployment(target, namespace, dep)

        if desired < current:
            LAST_SCALE_DOWN[target] = now

        logger.info(f"[{target}] Scaled {current} → {desired}")
