# IPA Platform — Predictive Autoscaling & DevOps Control Portal for Kubernetes

IPA Platform is a Kubernetes-native predictive autoscaling project built around an Intelligent Pod Autoscaler (IPA) control loop. It combines Prometheus-driven forecasting, an LLM-assisted decision service, and a React/FastAPI control portal for operations visibility.

The repository is optimized for Minikube-based local platform development, with a single bootstrap script (`run.sh`) that deploys services, starts resilient port-forwards, and streams controller logs.

## Architecture

- `js-app`: Sample workload (`Deployment` + `Service`) exposing traffic metrics.
- `predictor-service`: Forecast API + Prometheus metrics exporter (`ipa_prediction`, range, fallback, accuracy signals).
- `llm-decision-service`: Ollama-backed reasoning service used by controller for explanation text.
- `controller` (`ipa-controller`): Kopf operator that reconciles `IntelligentPodAutoscaler` CRs and scales target deployments.
- `backend` (FastAPI): Cluster observability/control API (`/api/predictions`, `/api/k8s/status`, `/api/logs`, Grafana health).
- `frontend` (React/Vite): IPA Control Portal UI (Dashboard, Kubernetes status, logs, Grafana embed).
- `kube-prometheus` (optional but recommended): Prometheus/Grafana monitoring stack.

## IPA Control Portal

Pages in the frontend:

- `/` Dashboard: prediction, actual load, ranges, fallback status, trend.
- `/k8s` Kubernetes status tables.
- `/logs` Pod log viewer.
- `/grafana` Embedded Grafana dashboard.

## Prerequisites

- `docker`
- `kubectl`
- `minikube`
- `npm` (for frontend local dev)
- Python 3.10+ (for optional local backend dev)

## Quick Start

### 1) (Recommended) Deploy Monitoring First

```bash
cd kube-prometheus
./build.sh
kubectl apply --server-side -f manifests/setup
kubectl apply -f manifests/
cd ..
```

### 2) Run the Platform Bootstrap

```bash
./run.sh
```

`run.sh` performs:

- Minikube startup/check.
- DNS verification and CoreDNS recovery retry.
- Parallel Docker image builds in Minikube Docker daemon.
- Kubernetes manifest apply for workload/services/controller/backend.
- Ollama readiness wait + model pull (`llama3.2:1b`) when available.
- Deployment restart + readiness waits.
- Grafana embed/env configuration and IPA dashboard ConfigMap provisioning.
- Resilient background port-forwards with auto-reconnect.
- Controller log streaming in foreground.

### 3) Start the Frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

Open: `http://localhost:5173`

## Runtime Endpoints (from `run.sh`)

- LLM Decision Service: `http://localhost:15000`
- Predictor Service: `http://localhost:18000`
- IPA Backend API: `http://localhost:8000`
- Grafana: `http://localhost:3000`
- Prometheus: `http://localhost:19090`

## Traffic Generation Policy

Automatic traffic generation is intentionally disabled in `run.sh`.

- This keeps baseline behavior stable and predictable.
- Predictions can stay near zero without traffic.

To generate traffic manually, you can deploy the provided load generator:

```bash
kubectl apply -n default -f k8s/loadgen-auto.yaml
```

To stop it:

```bash
kubectl delete -n default -f k8s/loadgen-auto.yaml
```

## How IPA Works

1. `predictor-service` queries Prometheus series (for `http_requests_total` rate).
2. It publishes prediction metrics (`ipa_prediction`, `ipa_prediction_low`, `ipa_prediction_high`, `ipa_prediction_fallback`).
3. `ipa-controller` polls predictor output and computes scaling decisions using thresholds/hysteresis from the IPA CR.
4. Controller patches the target deployment replica count.
5. FastAPI backend exposes current state; React portal renders it.

Current demo CR: `demo-ipa.yaml`

- `targetPerPod: 20`
- `minReplicas: 1`
- `maxReplicas: 20`
- `lookbackSeconds: 600`
- `horizonSeconds: 300`
- `cooldownSeconds: 60`

## Local Backend Dev (Optional)

If you need backend-only local development:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run-dev.sh
```

## Troubleshooting

- If Grafana says dashboard not found, re-run `./run.sh` (it reprovisions `ipa-prediction` dashboard ConfigMap).
- If predictions look flat at zero, verify traffic exists and Prometheus targets are UP.
- If build warns about legacy Docker builder, install `docker-buildx` for cleaner build output.
- `run.sh` streams controller logs; stop with `Ctrl+C` (this also stops script-managed port-forwards).
