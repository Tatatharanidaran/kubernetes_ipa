# IPA Project

This repository contains a small Kubernetes-based system with multiple services, an IPA controller, and optional monitoring via kube-prometheus.

## Components

- `js-app`: Node.js app exposed on port 8080.
- `predictor-service`: Python service exposed on port 8000.
- `llm-decision-service`: Python service exposed on port 5000 and backed by Ollama.
- `controller`: IPA controller built with Kopf.
- `crds`: Custom resource definitions for the IntelligentPodAutoscaler.
- `kube-prometheus`: Optional monitoring stack (Prometheus and Grafana).

## Prerequisites

- `docker`
- `kubectl`
- `minikube`
- A working Kubernetes context (the script uses Minikube by default).

## Quick Start

Run the full setup:
```bash
./run-all.sh
```

The script will:
- Start Minikube if needed.
- Build local Docker images.
- Apply Kubernetes manifests.
- Deploy Ollama and pull the model.
- Restart workloads and wait for readiness.

## Monitoring (Optional)

If you want Prometheus and Grafana, deploy kube-prometheus first:
```bash
cd kube-prometheus
./build.sh
kubectl apply --server-side -f manifests/setup
kubectl apply -f manifests/
cd ..
```

## Port Forwards

After the script completes, you can port-forward as needed:
```bash
kubectl port-forward -n default svc/llm-decision-service 5000:5000
kubectl -n monitoring port-forward svc/grafana 3000:80
kubectl -n monitoring port-forward svc/prometheus-k8s 9090:9090
kubectl -n default port-forward svc/predictor 8000:8000
```

## Notes

- The Ollama model pulled by default is `llama3.2:1b`.
- If the `monitoring` namespace does not exist, the port-forward commands for Grafana/Prometheus will fail until kube-prometheus is deployed.
