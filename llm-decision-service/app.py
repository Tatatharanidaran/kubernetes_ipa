from flask import Flask, request, jsonify
import os
import logging
import requests

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# --- Ollama client setup ---
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "10"))


def _compact_reason(text):
    cleaned = " ".join(str(text).split())
    if not cleaned:
        return ""

    sentences = []
    start = 0
    for i, ch in enumerate(cleaned):
        if ch in ".!?":
            sentences.append(cleaned[start:i + 1].strip())
            start = i + 1
            if len(sentences) >= 2:
                break

    if sentences:
        compact = " ".join(sentences).strip()
    else:
        compact = cleaned

    # Keep it readable if the model still returns long output.
    if len(compact) > 300:
        compact = compact[:300].rstrip()
    return compact

# --- API ---
@app.route("/decide", methods=["POST"])
def decide():
    data = request.get_json(force=True)

    prediction = float(data.get("prediction", 0))
    current = int(data.get("current", 1))
    desired = int(data.get("desired", 1))

    if desired > current:
        action = "scale_up"
    elif desired < current:
        action = "scale_down"
    else:
        action = "stable"

    # Fallback if LLM unavailable
    if not OLLAMA_BASE_URL or not OLLAMA_MODEL:
        return jsonify({
            "action": action,
            "reason": "Fallback decision: LLM unavailable, using rule-based logic"
        })

    prompt = f"""
You are an autoscaling advisor.

Predicted traffic: {prediction} req/sec
Current replicas: {current}
Desired replicas: {desired}
Chosen action: {action}

Explain clearly WHY we chose the action, in 1-2 simple sentences.
Use plain language that non-experts understand.
"""

    try:
        resp = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 120
                }
            },
            timeout=OLLAMA_TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        payload = resp.json()
        reason = _compact_reason(payload.get("response", ""))
        if not reason:
            reason = "LLM returned empty response, fallback decision applied"
    except Exception as e:
        app.logger.error(f"Ollama call failed: {e}")
        reason = "LLM error occurred, fallback decision applied"

    return jsonify({
        "action": action,
        "reason": reason
    })

# --- Health endpoint ---
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
