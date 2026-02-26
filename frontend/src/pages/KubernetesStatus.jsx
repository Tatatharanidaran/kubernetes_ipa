import { useEffect, useState } from 'react'
import { getKubernetesStatus } from '../api/client'

function rowColor(pod) {
  if (pod.status === 'Failed') return '#b11b1b'
  if (pod.status === 'Running' && pod.ready) return '#0d7a5f'
  if (!pod.ready) return '#cc8400'
  return 'inherit'
}

function KubernetesStatus() {
  const [namespace, setNamespace] = useState('default')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true

    async function load() {
      try {
        const result = await getKubernetesStatus(namespace)
        if (!active) return
        setData(result)
        setError('')
      } catch (err) {
        if (!active) return
        setError(err.message)
      } finally {
        if (active) setLoading(false)
      }
    }

    load()
    const timer = setInterval(load, 5000)

    return () => {
      active = false
      clearInterval(timer)
    }
  }, [namespace])

  return (
    <div>
      <h2>Kubernetes Status</h2>

      <div className="toolbar">
        <input
          value={namespace}
          onChange={(event) => setNamespace(event.target.value || 'default')}
          placeholder="namespace"
        />
      </div>

      {loading ? <p>Loading cluster status...</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <section className="card">
        <h3>Pods</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Pod Name</th>
                <th>Status</th>
                <th>Ready</th>
              </tr>
            </thead>
            <tbody>
              {(data?.pods || []).map((pod) => (
                <tr key={pod.name} style={{ color: rowColor(pod), fontWeight: 600 }}>
                  <td>{pod.name}</td>
                  <td>{pod.status}</td>
                  <td>{pod.ready ? '✔' : '❌'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" style={{ marginTop: '1rem' }}>
        <h3>Deployments</h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Replicas</th>
                <th>Available</th>
              </tr>
            </thead>
            <tbody>
              {(data?.deployments || []).map((deployment) => (
                <tr key={deployment.name}>
                  <td>{deployment.name}</td>
                  <td>{deployment.replicas}</td>
                  <td>{deployment.available}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

export default KubernetesStatus
