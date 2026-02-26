# IPA Platform — Predictive Autoscaling & DevOps Control Portal for Kubernetes

IPA Platform is a Kubernetes-native platform for predictive autoscaling driven by metrics, model-based signals, and controller decisions. It combines runtime workloads with an Intelligent Pod Autoscaler (IPA) control loop and a DevOps Control Portal for live visibility. The system is designed for practical experimentation and production-style operations workflows on Minikube.

## 🏗️ Architecture Overview

- `js-app`: Node.js workload exposed on port `8080`.
- `predictor-service`: Python predictor API exposed on port `8000`, exporting Prometheus metrics for forecasted scaling signals.
- `llm-decision-service`: Python decision service exposed on port `5000`, backed by Ollama.
- `ipa-controller` (from `controller`): Kopf-based Kubernetes controller that watches IPA CRDs and applies scaling actions.
- `IPA Control Portal` (`frontend` + `backend`): React + FastAPI interface for prediction visibility, Kubernetes status, logs, and Grafana embedding.
- `Prometheus + Grafana` (`kube-prometheus`): Optional monitoring stack for metrics ingestion, querying, and dashboards.

## 🖥️ IPA Control Portal

The portal provides a centralized operational UI:

- **Dashboard**: Live prediction metrics and trend chart.
- **Kubernetes Status**: Pod and deployment readiness/status overview.
- **Logs Viewer**: Pod log inspection from a selected namespace/pod.
- **Grafana Embed**: Embedded dashboard view using configured Grafana URL.

## Prerequisites

- `docker`
- `kubectl`
- `minikube`
- A working Kubernetes context (the script uses Minikube by default).

## 🚀 Quick Start

### Run the Platform

Run the full setup:
```bash
./run.sh
```

The script will:
- Start Minikube if needed.
- Build local Docker images.
- Apply Kubernetes manifests.
- Deploy Ollama and pull the model.
- Restart workloads and wait for readiness.

### Deploy Monitoring (Optional)

If you want Prometheus and Grafana, deploy kube-prometheus first:
```bash
cd kube-prometheus
./build.sh
kubectl apply --server-side -f manifests/setup
kubectl apply -f manifests/
cd ..
```

### Access the Control Portal

After the script completes, you can port-forward as needed:
```bash
kubectl port-forward -n default svc/llm-decision-service 5000:5000
kubectl -n monitoring port-forward svc/grafana 3000:80
kubectl -n monitoring port-forward svc/prometheus-k8s 9090:9090
kubectl -n default port-forward svc/predictor 8000:8000
```

## ⚙️ How IPA Works

- `predictor-service` publishes Prometheus metrics such as:
  - `ipa_prediction`
  - `ipa_prediction_low`
  - `ipa_prediction_high`
  - `ipa_prediction_fallback`
  - `ipa_prediction_last_success_timestamp`
- These predictive signals represent recommended replica behavior and fallback state.
- The IPA controller watches IPA custom resources and reconciles desired scaling decisions to Kubernetes workloads.
- The Control Portal surfaces these signals in real time, including StatusBar health indicators:
  - **Cluster Health** from pod readiness.
  - **Prediction Status** from fallback state.

## Notes

- The Ollama model pulled by default is `llama3.2:1b`.
- If the `monitoring` namespace does not exist, the port-forward commands for Grafana/Prometheus will fail until kube-prometheus is deployed.
