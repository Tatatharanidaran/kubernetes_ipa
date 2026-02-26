function pointsForSeries(data, min, range, width, height, padding) {
  return data
    .map((value, index) => {
      const x =
        padding +
        (index * (width - padding * 2)) / Math.max(data.length - 1, 1)
      const y =
        height -
        padding -
        ((value - min) * (height - padding * 2)) / range
      return `${x},${y}`
    })
    .join(' ')
}

function PredictionTrend({ predictedData, actualData }) {
  const width = 900
  const height = 240
  const padding = 20

  const predicted = Array.isArray(predictedData) ? predictedData : []
  const actual = Array.isArray(actualData) ? actualData : []
  const merged = [...predicted, ...actual].filter((value) => typeof value === 'number')

  if (merged.length === 0) {
    return <p className="muted">No prediction history available yet.</p>
  }

  const min = Math.min(...merged)
  const max = Math.max(...merged)
  const range = max - min || 1

  const predictedPoints = pointsForSeries(predicted, min, range, width, height, padding)
  const actualPoints = pointsForSeries(actual, min, range, width, height, padding)

  return (
    <div className="card" style={{ padding: '0.75rem' }}>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height="260" role="img" aria-label="Prediction trend chart">
        <line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} stroke="#d6e3de" />
        <line x1={padding} y1={padding} x2={padding} y2={height - padding} stroke="#d6e3de" />
        {actualPoints ? (
          <polyline
            fill="none"
            stroke="#1f6fb2"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={actualPoints}
          />
        ) : null}
        {predictedPoints ? (
          <polyline
            fill="none"
            stroke="#0d7a5f"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={predictedPoints}
          />
        ) : null}
      </svg>
      <div className="trend-legend">
        <span><i style={{ background: '#0d7a5f' }} /> Predicted</span>
        <span><i style={{ background: '#1f6fb2' }} /> Actual</span>
      </div>
    </div>
  )
}

export default PredictionTrend
