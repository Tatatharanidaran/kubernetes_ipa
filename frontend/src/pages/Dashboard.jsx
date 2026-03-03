import { useEffect, useState } from 'react'
import {
  getAutoLoadStatus,
  getPredictions,
  getScalingEvents,
  startAutoLoad,
  stopAutoLoad,
} from '../api/client'
import MetricCard from '../components/MetricCard'
import PredictionTrend from '../components/PredictionTrend'
import ScalingTimeline from '../components/ScalingTimeline'

function Dashboard() {
  const [data, setData] = useState(null)
  const [predictionHistory, setPredictionHistory] = useState([])
  const [actualHistory, setActualHistory] = useState([])
  const [scalingEvents, setScalingEvents] = useState([])
  const [autoLoadEnabled, setAutoLoadEnabled] = useState(false)
  const [autoLoadBusy, setAutoLoadBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    async function load() {
      if (!active) return

      const [predictionResult, eventsResult, autoLoadResult] = await Promise.allSettled([
        getPredictions(),
        getScalingEvents({ namespace: 'default', limit: 5 }),
        getAutoLoadStatus('default'),
      ])

      if (!active) return

      if (predictionResult.status === 'fulfilled') {
        const result = predictionResult.value
        setData(result)
        setError('')

        if (typeof result?.prediction === 'number') {
          setPredictionHistory((prev) => [...prev, result.prediction].slice(-20))
        }
        if (typeof result?.actual_load === 'number') {
          setActualHistory((prev) => [...prev, result.actual_load].slice(-20))
        }
      } else {
        setError(predictionResult.reason?.message || 'Failed to fetch predictions')
      }

      if (eventsResult.status === 'fulfilled') {
        setScalingEvents(Array.isArray(eventsResult.value) ? eventsResult.value : [])
      }

      if (autoLoadResult.status === 'fulfilled') {
        setAutoLoadEnabled(Boolean(autoLoadResult.value?.enabled))
      }

      if (active) {
        setLoading(false)
      }
    }

    load()
    const timer = setInterval(load, 5000)

    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])

  async function handleAutoLoadToggle() {
    setAutoLoadBusy(true)
    try {
      const result = autoLoadEnabled
        ? await stopAutoLoad('default')
        : await startAutoLoad('default')
      setAutoLoadEnabled(Boolean(result?.enabled))
    } catch (err) {
      setError(err.message || 'Failed to toggle auto-load')
    } finally {
      setAutoLoadBusy(false)
    }
  }

  const fallbackEnabled = Boolean(data?.fallback)
  const fallbackText = loading && !data ? 'CONNECTING...' : (fallbackEnabled ? 'Using Safe Mode' : 'Normal')
  const lastSuccess = data?.last_success
    ? new Date(data.last_success * 1000).toLocaleString()
    : 'N/A'

  const upArrow = data?.prediction > data?.low ? '▲' : '-'
  const downArrow = data?.prediction < data?.high ? '▼' : '-'
  const predictionVsActual =
    data?.prediction > data?.actual_load ? '▲' : data?.prediction < data?.actual_load ? '▼' : '-'

  return (
    <div>
      <h2>Dashboard</h2>

      {loading ? <p>CONNECTING...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <section style={{ marginBottom: '1rem' }}>
        <h3>Prediction Metrics</h3>
        <div className="grid">
          <MetricCard
            title="Prediction"
            value={
              loading && !data
                ? 'CONNECTING...'
                : (fallbackEnabled ? 'Using Safe Mode' : (data?.prediction ?? 'N/A'))
            }
            subtitle={`Trend: ${upArrow} ${downArrow}`}
          />
          <MetricCard
            title="Actual Load"
            value={loading && !data ? 'CONNECTING...' : (data?.actual_load ?? 'N/A')}
            subtitle={`Predicted vs Actual: ${predictionVsActual}`}
          />
          <MetricCard title="Low Range" value={loading && !data ? 'CONNECTING...' : (data?.low ?? 'N/A')} />
          <MetricCard title="High Range" value={loading && !data ? 'CONNECTING...' : (data?.high ?? 'N/A')} />
        </div>
      </section>

      <section style={{ marginBottom: '1rem' }}>
        <h3>System State</h3>
        <div style={{ marginBottom: '0.75rem' }}>
          <button
            type="button"
            onClick={handleAutoLoadToggle}
            disabled={autoLoadBusy}
          >
            {autoLoadBusy
              ? 'Updating...'
              : autoLoadEnabled
                ? 'Stop Auto-Load'
                : 'Start Auto-Load'}
          </button>
          <small style={{ marginLeft: '0.6rem' }}>
            Auto-load: {autoLoadEnabled ? 'ON' : 'OFF'}
          </small>
        </div>
        <div className="grid">
          <section className="card metric-card">
            <h3>Fallback Status</h3>
            <p
              className="metric-value"
              style={{
                color: '#fff',
                background: fallbackEnabled ? '#b11b1b' : '#0d7a5f',
                display: 'inline-block',
                padding: '0.2rem 0.7rem',
                borderRadius: '999px',
                fontSize: '1rem',
              }}
            >
              {fallbackText}
            </p>
          </section>
          <MetricCard title="Last Success Timestamp" value={lastSuccess} />
        </div>
      </section>

      <section>
        <h3>Prediction Trend</h3>
        <PredictionTrend predictedData={predictionHistory} actualData={actualHistory} />
      </section>

      <section style={{ marginTop: '1rem' }}>
        <ScalingTimeline events={scalingEvents} />
      </section>
    </div>
  )
}

export default Dashboard
