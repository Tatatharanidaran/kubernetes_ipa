function MetricCard({ title, value, subtitle }) {
  const displayValue =
    typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : (value ?? 'N/A')

  return (
    <section className="card metric-card">
      <h3>{title}</h3>
      <p className="metric-value">{displayValue}</p>
      {subtitle ? <small>{subtitle}</small> : null}
    </section>
  )
}

export default MetricCard
