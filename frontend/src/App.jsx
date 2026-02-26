import { NavLink, Route, Routes } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import KubernetesStatus from './pages/KubernetesStatus'
import LogsViewer from './pages/LogsViewer'
import GrafanaEmbed from './pages/GrafanaEmbed'
import StatusBar from './components/StatusBar'

function App() {
  return (
    <div className="layout">
      <header className="header">
        <h1>IPA Control Portal</h1>
        <nav>
          <NavLink to="/">Dashboard</NavLink>
          <NavLink to="/k8s">Kubernetes</NavLink>
          <NavLink to="/logs">Logs</NavLink>
          <NavLink to="/grafana">Grafana</NavLink>
        </nav>
      </header>

      <StatusBar />

      <main className="main">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/k8s" element={<KubernetesStatus />} />
          <Route path="/logs" element={<LogsViewer />} />
          <Route path="/grafana" element={<GrafanaEmbed />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
