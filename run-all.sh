#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    echo "Install it and re-run this script."
    exit 1
  fi
}

require_cmd docker
require_cmd kubectl
require_cmd minikube

if [ ! -d "$ROOT_DIR/js-app/node_modules" ]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Installing js-app dependencies (node_modules missing)..."
    (cd "$ROOT_DIR/js-app" && npm install)
  else
    echo "js-app/node_modules is missing and npm is not installed."
    echo "Install npm and run: cd \"$ROOT_DIR/js-app\" && npm install"
    exit 1
  fi
fi

echo "Starting minikube (if needed) and configuring Docker env..."
minikube status >/dev/null 2>&1 || minikube start --memory=8192 --cpus=4
eval "$(minikube docker-env)"

echo "Building local images..."
cd "$ROOT_DIR/js-app"
docker build -t js-app:latest .

cd "$ROOT_DIR/predictor-service"
docker build -t predictor:local .

cd "$ROOT_DIR/controller"
docker build -t ipa-controller:local .

cd "$ROOT_DIR/llm-decision-service"
docker build -t llm-decision-service:latest .

echo "Applying Kubernetes manifests..."
kubectl apply -f "$ROOT_DIR/js-app/k8s/deployment.yaml"
kubectl apply -f "$ROOT_DIR/js-app/k8s/service.yaml"
kubectl apply -f "$ROOT_DIR/js-app/k8s/servicemonitor.yaml"

kubectl apply -f "$ROOT_DIR/predictor-service/k8s/deployment.yaml"
kubectl apply -f "$ROOT_DIR/predictor-service/k8s/service.yaml"
kubectl apply -f "$ROOT_DIR/predictor-service/k8s/servicemonitor.yaml"

kubectl apply -f "$ROOT_DIR/llm-decision-service/k8s/ollama.yaml"
kubectl apply -f "$ROOT_DIR/llm-decision-service/k8s/llm-decision-service.yaml"

kubectl apply -f "$ROOT_DIR/controller/k8s/serviceaccount.yaml"
kubectl apply -f "$ROOT_DIR/controller/k8s/deployment.yaml"

kubectl apply -f "$ROOT_DIR/demo-ipa.yaml"

echo "Waiting for Ollama to be ready..."
kubectl wait -n default --for=condition=Available deployment/ollama --timeout=120s

echo "Pulling Ollama model..."
kubectl exec -n default deploy/ollama -- ollama pull llama3.2:1b

echo "Restarting deployments..."
kubectl rollout restart -n default deploy/js-app
kubectl rollout restart -n default deploy/predictor
kubectl rollout restart -n default deploy/llm-decision-service
kubectl rollout restart -n default deploy/ipa-controller

echo "Waiting for pods to be ready..."
kubectl wait -n default --for=condition=Available deployment/js-app --timeout=120s
kubectl wait -n default --for=condition=Available deployment/predictor --timeout=120s
kubectl wait -n default --for=condition=Available deployment/llm-decision-service --timeout=120s
kubectl wait -n default --for=condition=Available deployment/ipa-controller --timeout=120s

echo "All done."
if ! kubectl get ns monitoring >/dev/null 2>&1; then
  echo "Note: 'monitoring' namespace not found."
  echo "If you want Grafana/Prometheus, deploy kube-prometheus first."
  echo "Suggested commands:"
  echo "  cd \"$ROOT_DIR/kube-prometheus\""
  echo "  ./build.sh"
  echo "  kubectl apply --server-side -f manifests/setup"
  echo "  kubectl apply -f manifests/"
  echo "  cd \"$ROOT_DIR\""
fi
echo "Next: port-forward as needed:"
echo "  Terminal 2: kubectl port-forward -n default svc/llm-decision-service 5000:5000"
echo "  Terminal 3: kubectl -n monitoring port-forward svc/grafana 3000:80"
echo "  Terminal 4: kubectl -n monitoring port-forward svc/prometheus-k8s 9090:9090"
echo "  Terminal 5: kubectl -n default port-forward svc/predictor 8000:8000"
echo "  Terminal 6: kubectl exec -it loadgen -- sh"
echo "  Terminal 6: Then inside loadgen: while true; do wget -qO- http://js-app.default.svc.cluster.local:8080 >/dev/null; done" 
echo "  Terminal 7: kubectl logs -n default -l app=ipa-controller -f"
