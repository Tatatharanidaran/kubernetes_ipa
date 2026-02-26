#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="default"
PORT_FORWARD_PIDS=()

COLOR_RESET="\033[0m"
COLOR_INFO="\033[1;34m"
COLOR_WARN="\033[1;33m"
COLOR_ERROR="\033[1;31m"

log_info() {
  printf "%b[INFO]%b %s\n" "$COLOR_INFO" "$COLOR_RESET" "$1"
}

log_warn() {
  printf "%b[WARN]%b %s\n" "$COLOR_WARN" "$COLOR_RESET" "$1"
}

log_error() {
  printf "%b[ERROR]%b %s\n" "$COLOR_ERROR" "$COLOR_RESET" "$1" >&2
}

cleanup() {
  log_warn "Stopping port-forwards..."
  for pid in "${PORT_FORWARD_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT INT TERM

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log_error "Missing required command: $1"
    exit 1
  fi
}

ensure_namespace() {
  namespace="$1"
  if ! kubectl get namespace "$namespace" >/dev/null 2>&1; then
    log_info "Creating namespace '$namespace'"
    kubectl create namespace "$namespace" >/dev/null
  fi
}

pod_ready_condition() {
  namespace="$1"
  pod="$2"
  kubectl get pod "$pod" -n "$namespace" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || true
}

cleanup_stale_pods() {
  log_info "Cleaning stale pods..."

  for pod in dns-test; do
    if kubectl get pod "$pod" -n "$NAMESPACE" >/dev/null 2>&1; then
      phase="$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
      ready="$(pod_ready_condition "$NAMESPACE" "$pod")"
      if [ "$phase" = "Failed" ] || [ "$ready" = "False" ]; then
        kubectl delete pod "$pod" -n "$NAMESPACE" --force --grace-period=0 >/dev/null 2>&1 || true
      fi
    fi
  done
}

ensure_dns_test_pod() {
  if kubectl get pod dns-test -n "$NAMESPACE" >/dev/null 2>&1; then
    deletion_ts="$(kubectl get pod dns-test -n "$NAMESPACE" -o jsonpath='{.metadata.deletionTimestamp}' 2>/dev/null || true)"
    phase="$(kubectl get pod dns-test -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    ready="$(pod_ready_condition "$NAMESPACE" "dns-test")"

    if [ -n "$deletion_ts" ]; then
      log_warn "dns-test stuck, cleaning..."
      kubectl patch pod dns-test -n "$NAMESPACE" -p '{"metadata":{"finalizers":null}}' >/dev/null 2>&1 || true
      kubectl delete pod dns-test -n "$NAMESPACE" --force --grace-period=0 --wait=false >/dev/null 2>&1 || true
      sleep 2
    elif [ "$phase" = "Failed" ] || [ "$ready" = "False" ]; then
      kubectl delete pod dns-test -n "$NAMESPACE" --force --grace-period=0 --wait=false >/dev/null 2>&1 || true
      sleep 2
    elif [ "$phase" = "Running" ] && [ "$ready" = "True" ]; then
      log_info "Reusing existing dns-test pod"
      return
    else
      kubectl delete pod dns-test -n "$NAMESPACE" --force --grace-period=0 --wait=false >/dev/null 2>&1 || true
      sleep 2
    fi
  fi

  if ! kubectl get pod dns-test -n "$NAMESPACE" >/dev/null 2>&1; then
    log_info "Creating dns-test pod"
    kubectl run dns-test -n "$NAMESPACE" --image=busybox --restart=Never -- sleep 3600 >/dev/null 2>&1 || true
  fi

  kubectl wait -n "$NAMESPACE" --for=condition=Ready pod/dns-test --timeout=60s >/dev/null 2>&1 || true
}

build_image() {
  dir="$1"
  tag="$2"
  log_info "Building image $tag"
  (
    cd "$ROOT_DIR/$dir"
    docker build -t "$tag" .
  )
}

service_available() {
  namespace="$1"
  svc="$2"

  if kubectl get svc "$svc" -n "$namespace" >/dev/null 2>&1; then
    printf "READY"
  else
    printf "NOT INSTALLED"
  fi
}

start_resilient_port_forward() {
  namespace="$1"
  resource="$2"
  ports="$3"
  name="$4"

  (
    while true; do
      echo "[INFO] Starting resilient port-forward for $name..."
      kubectl -n "$namespace" port-forward "$resource" "$ports" 2>&1 | sed -u "s/^/[${name}] /"
      echo "[WARN] Port-forward for $name disconnected. Reconnecting in 3s..."
      sleep 3
    done
  ) &

  pid=$!
  PORT_FORWARD_PIDS+=("$pid")
  log_info "Started resilient port-forward for $name ($resource $ports)"
}

require_cmd docker
require_cmd kubectl
require_cmd minikube

if [ ! -d "$ROOT_DIR/js-app/node_modules" ]; then
  if command -v npm >/dev/null 2>&1; then
    log_info "Installing js-app dependencies (node_modules missing)..."
    (cd "$ROOT_DIR/js-app" && npm install)
  else
    log_error "js-app/node_modules is missing and npm is not installed."
    exit 1
  fi
fi

log_info "Starting minikube (if needed)..."
minikube status >/dev/null 2>&1 || minikube start --memory=8192 --cpus=4

current_context="$(kubectl config current-context 2>/dev/null || true)"
if [ "$current_context" != "minikube" ]; then
  log_error "Current kubectl context is '$current_context' (expected 'minikube')."
  exit 1
fi

log_info "Configuring Docker to use Minikube daemon"
eval "$(minikube docker-env)"

if ! docker info >/dev/null 2>&1; then
  log_error "Docker daemon is not reachable."
  exit 1
fi

ensure_namespace "$NAMESPACE"
cleanup_stale_pods
ensure_dns_test_pod

if kubectl exec -n "$NAMESPACE" dns-test -- nslookup registry.ollama.ai >/dev/null 2>&1; then
  log_info "DNS test succeeded for registry.ollama.ai"
else
  log_warn "DNS lookup failed, restarting CoreDNS and retrying once..."
  kubectl rollout restart deployment coredns -n kube-system >/dev/null 2>&1 || true
  sleep 20
  if ! kubectl exec -n "$NAMESPACE" dns-test -- nslookup registry.ollama.ai >/dev/null 2>&1; then
    log_warn "DNS retry failed; continuing platform startup."
  else
    log_info "DNS retry succeeded for registry.ollama.ai"
  fi
fi

log_info "Building local images"
build_image "js-app" "js-app:latest" &
pid_js=$!
build_image "predictor-service" "predictor:local" &
pid_predictor=$!
build_image "controller" "ipa-controller:local" &
pid_controller=$!
build_image "llm-decision-service" "llm-decision-service:latest" &
pid_llm=$!
build_image "backend" "ipa-backend:local" &
pid_backend=$!

wait "$pid_js"
wait "$pid_predictor"
wait "$pid_controller"
wait "$pid_llm"
wait "$pid_backend"

log_info "Applying Kubernetes manifests"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/js-app/k8s/deployment.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/js-app/k8s/service.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/js-app/k8s/servicemonitor.yaml"

kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/predictor-service/k8s/deployment.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/predictor-service/k8s/service.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/predictor-service/k8s/servicemonitor.yaml"

kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/llm-decision-service/k8s/ollama.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/llm-decision-service/k8s/llm-decision-service.yaml"

kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/controller/k8s/serviceaccount.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/controller/k8s/deployment.yaml"

kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/backend/k8s/rbac.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/backend/k8s/rbac-events.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/backend/k8s/deployment.yaml"
kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/backend/k8s/service.yaml"

kubectl apply -n "$NAMESPACE" -f "$ROOT_DIR/demo-ipa.yaml"

OLLAMA_READY=0
if kubectl get deployment ollama -n "$NAMESPACE" >/dev/null 2>&1; then
  log_info "Waiting for Ollama to be ready"
  if kubectl wait -n "$NAMESPACE" --for=condition=Available deployment/ollama --timeout=120s; then
    log_info "Ollama ready"
    OLLAMA_READY=1
  else
    log_warn "Ollama not ready, continuing bootstrap"
  fi
else
  log_warn "Ollama deployment not found, continuing bootstrap"
fi

if [ "$OLLAMA_READY" -eq 1 ]; then
  log_info "Pulling Ollama model"
  kubectl exec -n "$NAMESPACE" deploy/ollama -- ollama pull llama3.2:1b
fi

log_info "Restarting deployments"
kubectl rollout restart -n "$NAMESPACE" deploy/js-app
kubectl rollout restart -n "$NAMESPACE" deploy/predictor
kubectl rollout restart -n "$NAMESPACE" deploy/llm-decision-service
kubectl rollout restart -n "$NAMESPACE" deploy/ipa-controller
kubectl rollout restart -n "$NAMESPACE" deploy/ipa-backend

log_info "Waiting for deployments to become available"
kubectl wait -n "$NAMESPACE" --for=condition=Available deployment/js-app --timeout=120s
kubectl wait -n "$NAMESPACE" --for=condition=Available deployment/predictor --timeout=120s
kubectl wait -n "$NAMESPACE" --for=condition=Available deployment/llm-decision-service --timeout=120s
kubectl wait -n "$NAMESPACE" --for=condition=Available deployment/ipa-controller --timeout=120s
kubectl wait -n "$NAMESPACE" --for=condition=Available deployment/ipa-backend --timeout=120s

if kubectl get namespace monitoring >/dev/null 2>&1 && kubectl get deployment grafana -n monitoring >/dev/null 2>&1; then
  kubectl set env deployment/grafana -n monitoring \
    GF_SECURITY_ALLOW_EMBEDDING=true \
    GF_SECURITY_COOKIE_SAMESITE=lax \
    GF_SECURITY_COOKIE_SECURE=false \
    GF_SECURITY_X_FRAME_OPTIONS=allow \
    GF_SECURITY_CONTENT_SECURITY_POLICY=true \
    "GF_SECURITY_CONTENT_SECURITY_POLICY_TEMPLATE=frame-ancestors 'self' http://localhost:5173 http://127.0.0.1:5173; script-src 'self' 'unsafe-eval' 'unsafe-inline' 'strict-dynamic' \$NONCE; object-src 'none'; font-src 'self'; style-src 'self' 'unsafe-inline' blob:; img-src * data:; connect-src 'self' grafana.com ws://localhost:3000/ wss://localhost:3000/;" >/dev/null 2>&1 || true
fi

log_info "Automatic traffic generation: DISABLED"
log_info "Waiting for manual load input..."

LLM_LOCAL_PORT="15000"
PREDICTOR_LOCAL_PORT="18000"
BACKEND_LOCAL_PORT="8000"
GRAFANA_LOCAL_PORT="3000"
PROMETHEUS_LOCAL_PORT="19090"

if kubectl get namespace monitoring >/dev/null 2>&1; then
  start_resilient_port_forward "monitoring" "svc/prometheus-k8s" "$PROMETHEUS_LOCAL_PORT:9090" "prometheus"
  start_resilient_port_forward "monitoring" "svc/grafana" "$GRAFANA_LOCAL_PORT:3000" "grafana"
fi

start_resilient_port_forward "$NAMESPACE" "svc/llm-decision-service" "$LLM_LOCAL_PORT:5000" "llm-decision-service"
start_resilient_port_forward "$NAMESPACE" "svc/predictor" "$PREDICTOR_LOCAL_PORT:8000" "predictor-service"
start_resilient_port_forward "$NAMESPACE" "svc/ipa-backend" "$BACKEND_LOCAL_PORT:8000" "ipa-backend"

cat > "$ROOT_DIR/frontend/.env.local" <<EOF
VITE_API_BASE_URL=http://localhost:$BACKEND_LOCAL_PORT
VITE_GRAFANA_URL=http://localhost:$GRAFANA_LOCAL_PORT
EOF
log_info "Wrote frontend/.env.local with API=http://localhost:$BACKEND_LOCAL_PORT and Grafana=http://localhost:$GRAFANA_LOCAL_PORT"

printf "\n===== IPA PLATFORM LIVE =====\n\n"

printf "%-22s %s   [%s]\n" \
"LLM Decision Service:" \
"http://localhost:$LLM_LOCAL_PORT" \
"$(service_available "$NAMESPACE" "llm-decision-service")"

printf "%-22s %s   [%s]\n" \
"Predictor Service:" \
"http://localhost:$PREDICTOR_LOCAL_PORT" \
"$(service_available "$NAMESPACE" "predictor")"

printf "%-22s %s   [%s]\n" \
"IPA Backend API:" \
"http://localhost:$BACKEND_LOCAL_PORT" \
"$(service_available "$NAMESPACE" "ipa-backend")"

if kubectl get namespace monitoring >/dev/null 2>&1; then
  printf "%-22s %s   [%s]\n" \
  "Grafana:" \
  "http://localhost:$GRAFANA_LOCAL_PORT" \
  "$(service_available "monitoring" "grafana")"

  printf "%-22s %s   [%s]\n" \
  "Prometheus:" \
  "http://localhost:$PROMETHEUS_LOCAL_PORT" \
  "$(service_available "monitoring" "prometheus-k8s")"
else
  printf "%-22s %s\n" "Grafana:" "NOT INSTALLED"
  printf "%-22s %s\n" "Prometheus:" "NOT INSTALLED"
fi

printf "Streaming ipa-controller logs below...\n\n"

log_info "Waiting for ipa-controller pod to be ready..."
kubectl rollout status -n "$NAMESPACE" deployment/ipa-controller --timeout=180s \
  || log_warn "Controller deployment not ready yet, attempting log stream anyway"

kubectl logs -n "$NAMESPACE" -l app=ipa-controller -f
