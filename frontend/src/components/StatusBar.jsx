import { useEffect, useState } from 'react'
import { getKubernetesStatus, getPredictions } from '../api/client'

function pillStyle(background) {
  return {
    display: 'inline-block',
    marginLeft: '0.5rem',
    padding: '0.2rem 0.6rem',
    borderRadius: '999px',
    fontSize: '0.8rem',
    color: '#fff',
    background,
    fontWeight: 700,
  }
}

function StatusBar() {
  const [clusterHealthy, setClusterHealthy] = useState(null)
  const [predictionWarning, setPredictionWarning] = useState(null)

  useEffect(() => {
    let active = true

    async function loadStatus() {
      const [predictionsResult, k8sResult] = await Promise.allSettled([
        getPredictions(),
        getKubernetesStatus('default'),
      ])

      if (!active) return

      if (k8sResult.status === 'fulfilled') {
        const k8s = k8sResult.value
        const pods = k8s?.pods || []
        const allReady = pods.length > 0 ? pods.every((pod) => pod.ready) : false
        setClusterHealthy(allReady)
      } else {
        setClusterHealthy(false)
      }

      if (predictionsResult.status === 'fulfilled') {
        setPredictionWarning(Boolean(predictionsResult.value?.fallback))
      } else {
        setPredictionWarning(true)
      }
    }

    loadStatus()
    const timer = setInterval(loadStatus, 5000)

    return () => {
      active = false
      clearInterval(timer)
    }
  }, [])

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '1rem',
        padding: '0.65rem 1.5rem',
        borderBottom: '1px solid var(--border)',
        background: '#eef4f2',
      }}
    >
      <div>
        <strong>Cluster Health:</strong>
        <span style={pillStyle(clusterHealthy ? '#0d7a5f' : '#b11b1b')}>
          {clusterHealthy ? 'GREEN' : 'RED'}
        </span>
      </div>

      <div>
        <strong>Prediction Status:</strong>
        <span style={pillStyle(predictionWarning ? '#cc8400' : '#0d7a5f')}>
          {predictionWarning ? 'WARNING' : 'NORMAL'}
        </span>
      </div>
    </div>
  )
}

export default StatusBar
