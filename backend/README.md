# IPA Control Portal Backend

## Run locally

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./run-dev.sh
```

## API endpoints

- `GET /health`
- `GET /api/predictions`
- `GET /api/k8s/status?namespace=default`
- `GET /api/logs/{pod_name}?namespace=default&tail_lines=200`
