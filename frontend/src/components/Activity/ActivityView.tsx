import { useEffect, useRef } from 'react'
import { useAgentStore } from '../../store/agentStore'
import { useAgent } from '../../hooks/useAgent'

export default function ActivityView() {
  const log = useAgentStore((s) => s.log)
  const { running, start, stop } = useAgent()
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [log])

  function levelColor(level: string) {
    if (level === 'error') return '#ef4444'
    if (level === 'warn') return '#f59e0b'
    return 'var(--text-secondary)'
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 20, gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
          Activity Log
        </h2>
        <div style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: running ? '#22c55e' : 'var(--text-muted)',
        }} />
        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          {running ? 'Agent running...' : 'Agent idle'}
        </span>
        <div style={{ flex: 1 }} />
        {running ? (
          <button onClick={stop} style={btnStyle('#ef4444')}>Stop Agent</button>
        ) : (
          <button onClick={start} style={btnStyle('var(--accent)')}>Start Agent</button>
        )}
      </div>

      <div style={{
        flex: 1,
        background: 'var(--bg-code)',
        borderRadius: 8,
        border: '1px solid var(--border)',
        overflowY: 'auto',
        padding: 16,
        fontFamily: 'monospace',
        fontSize: 12,
      }}>
        {log.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
            No activity yet. Click "Start Agent" to begin.
          </div>
        ) : (
          log.map((entry) => (
            <div key={entry.id} style={{ marginBottom: 4, lineHeight: 1.5 }}>
              <span style={{ color: 'var(--text-muted)', marginRight: 8 }}>
                {new Date(entry.timestamp).toLocaleTimeString()}
              </span>
              <span style={{
                color: levelColor(entry.level),
                textTransform: 'uppercase',
                fontSize: 10,
                fontWeight: 700,
                marginRight: 8,
              }}>
                [{entry.level}]
              </span>
              <span style={{ color: 'var(--text-primary)' }}>{entry.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

function btnStyle(bg: string): React.CSSProperties {
  return {
    padding: '7px 16px',
    fontSize: 13,
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 600,
  }
}
