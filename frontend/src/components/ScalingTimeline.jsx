function ScalingTimeline({ events }) {
  if (!events || events.length === 0) {
    return <p className="muted">No scaling events recorded yet.</p>
  }

  return (
    <div className="card">
      <h3>Recent Scaling Events</h3>
      <div className="timeline">
        {events.slice(0, 5).map((event, index) => {
          const isUp = event.reason === 'scale_up'
          const arrow = isUp ? '↑' : '↓'
          return (
            <div className="timeline-item" key={`${event.timestamp}-${index}`}>
              <div className="timeline-icon">{arrow}</div>
              <div>
                <div>
                  <strong>{event.deployment}</strong> {event.old_replicas} → {event.new_replicas}
                </div>
                <small className="muted">
                  {new Date(event.timestamp).toLocaleString()} ({event.reason})
                </small>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default ScalingTimeline
