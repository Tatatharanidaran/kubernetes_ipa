const configuredBase = import.meta.env.VITE_API_BASE_URL
const fallbackBases = ['http://localhost:8000', 'http://localhost:8100', 'http://localhost:28000']
const apiBases = configuredBase
  ? [configuredBase, ...fallbackBases.filter((base) => base !== configuredBase)]
  : fallbackBases

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function request(path) {
  let lastError = null

  for (const base of apiBases) {
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const response = await fetch(`${base}${path}`)
        if (!response.ok) {
          const message = await response.text()
          throw new Error(message || `Request failed with status ${response.status}`)
        }
        return response.json()
      } catch (error) {
        lastError = error
        if (attempt < 2) {
          await delay(250 * (attempt + 1))
        }
      }
    }
  }

  throw new Error(lastError?.message || 'NetworkError when attempting to fetch resource')
}

export function getPredictions() {
  return request('/api/predictions')
}

export function getKubernetesStatus(namespace) {
  const query = namespace ? `?namespace=${encodeURIComponent(namespace)}` : ''
  return request(`/api/k8s/status${query}`)
}

export function getScalingEvents({ namespace = 'default', limit = 5 } = {}) {
  const params = new URLSearchParams()
  if (namespace) params.set('namespace', namespace)
  if (limit) params.set('limit', String(limit))
  return request(`/api/k8s/scaling-events?${params.toString()}`)
}

export function getGrafanaHealth() {
  return request('/api/health/grafana')
}

export function getPodLogs({ podName, namespace, tailLines }) {
  const params = new URLSearchParams()
  if (namespace) params.set('namespace', namespace)
  if (tailLines) params.set('tail_lines', String(tailLines))
  return request(`/api/logs/${encodeURIComponent(podName)}?${params.toString()}`)
}
