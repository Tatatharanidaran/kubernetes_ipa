import { useEffect, useState } from 'react'

import { getGrafanaHealth } from '../api/client'

function GrafanaEmbed() {
  const grafanaUrl = (import.meta.env.VITE_GRAFANA_URL || '').trim()
  const [healthy, setHealthy] = useState(false)
  const [checking, setChecking] = useState(true)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    let active = true
    async function checkHealth() {
      try {
        const result = await getGrafanaHealth()
        if (!active) return
        setHealthy(result?.status === 'ok')
      } catch (_err) {
        if (!active) return
        setHealthy(false)
      } finally {
        if (active) setChecking(false)
      }
    }
    checkHealth()
    const timer = setInterval(checkHealth, 5000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])

  if (!grafanaUrl) {
    return (
      <div>
        <h2>Grafana Embed</h2>
        <p className="error">Grafana URL is not configured. Set `VITE_GRAFANA_URL` in your environment.</p>
      </div>
    )
  }

  return (
    <div style={{ height: 'calc(100vh - 140px)' }}>
      <h2>Grafana Embed</h2>
      {checking ? <p className="muted">Checking Grafana health...</p> : null}
      {!checking && !healthy ? (
        <p className="error">Grafana is not healthy yet. Waiting for backend health check to pass.</p>
      ) : null}
      {loadError ? <p className="error">{loadError}</p> : null}
      <div className="card" style={{ padding: 0, height: '100%' }}>
        {healthy ? (
          <iframe
            title="Grafana Dashboard"
            src={grafanaUrl}
            style={{ width: '100%', height: '100%', border: 'none' }}
            loading="lazy"
            onError={() => setLoadError('Unable to load Grafana iframe. Check Grafana security headers and availability.')}
          />
        ) : (
          <div style={{ padding: '1rem' }}>
            <p className="muted">Grafana iframe will load automatically when health becomes OK.</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default GrafanaEmbed
