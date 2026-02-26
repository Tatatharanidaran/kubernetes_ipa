import { useEffect, useRef, useState } from 'react'
import { getKubernetesStatus, getPodLogs } from '../api/client'

function LogsViewer() {
  const [namespace, setNamespace] = useState('default')
  const [pods, setPods] = useState([])
  const [selectedPod, setSelectedPod] = useState('')
  const [logs, setLogs] = useState('')
  const [lastUpdated, setLastUpdated] = useState('')
  const [loadingPods, setLoadingPods] = useState(true)
  const [loadingLogs, setLoadingLogs] = useState(false)
  const [error, setError] = useState('')
  const logsRef = useRef(null)

  useEffect(() => {
    let active = true

    async function loadPods() {
      setLoadingPods(true)
      try {
        const status = await getKubernetesStatus(namespace)
        if (!active) return
        const podNames = (status.pods || []).map((pod) => pod.name)
        setPods(podNames)

        if (podNames.length === 0) {
          setSelectedPod('')
          setLogs('')
          return
        }

        setSelectedPod((current) => (current && podNames.includes(current) ? current : podNames[0]))
      } catch (err) {
        if (!active) return
        setError(err.message)
      } finally {
        if (active) setLoadingPods(false)
      }
    }

    loadPods()

    return () => {
      active = false
    }
  }, [namespace])

  async function loadLogs(podName) {
    if (!podName) return
    setLoadingLogs(true)
    setError('')

    try {
      const result = await getPodLogs({ podName, namespace, tailLines: 300 })
      setLogs(result.logs || '')
      setLastUpdated(new Date().toLocaleTimeString())
    } catch (err) {
      setError(err.message)
      setLogs('')
    } finally {
      setLoadingLogs(false)
    }
  }

  useEffect(() => {
    loadLogs(selectedPod)
  }, [selectedPod])

  useEffect(() => {
    if (!logsRef.current) return
    logsRef.current.scrollTop = logsRef.current.scrollHeight
  }, [logs, loadingLogs])

  return (
    <div>
      <h2>Logs Viewer</h2>

      <div className="toolbar">
        <input
          value={namespace}
          onChange={(event) => setNamespace(event.target.value || 'default')}
          placeholder="namespace"
        />

        <select
          value={selectedPod}
          onChange={(event) => setSelectedPod(event.target.value)}
          disabled={loadingPods || pods.length === 0}
        >
          {pods.length === 0 ? <option value="">No pods found</option> : null}
          {pods.map((pod) => (
            <option key={pod} value={pod}>
              {pod}
            </option>
          ))}
        </select>

        <button type="button" onClick={() => loadLogs(selectedPod)} disabled={!selectedPod || loadingLogs}>
          {loadingLogs ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {lastUpdated ? <p className="muted">Last updated: {lastUpdated}</p> : null}
      {error ? <p className="error">{error}</p> : null}

      <pre
        ref={logsRef}
        className="logs"
        style={{
          background: '#0b1220',
          color: '#d4e2ff',
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
          whiteSpace: 'pre-wrap',
          overflowY: 'auto',
          maxHeight: '60vh',
        }}
      >
        {loadingPods ? 'Loading pods...' : logs || 'Select a pod to view logs.'}
      </pre>
    </div>
  )
}

export default LogsViewer
