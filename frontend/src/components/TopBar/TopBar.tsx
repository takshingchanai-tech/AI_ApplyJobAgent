import { useAgent } from '../../hooks/useAgent'

interface Props {
  onOpenSettings: () => void
}

export default function TopBar({ onOpenSettings }: Props) {
  const { running, start, stop } = useAgent()

  return (
    <div style={{
      height: 52,
      background: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 20px',
      gap: 12,
      flexShrink: 0,
    }}>
      <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text-primary)', flex: 1 }}>
        Upwork Job Apply Agent
      </div>

      <div style={{
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: running ? '#22c55e' : 'var(--text-muted)',
        flexShrink: 0,
      }} />
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
        {running ? 'Running' : 'Idle'}
      </span>

      {running ? (
        <button
          onClick={stop}
          style={{
            padding: '6px 14px',
            fontSize: 13,
            background: '#ef4444',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          Stop
        </button>
      ) : (
        <button
          onClick={start}
          style={{
            padding: '6px 14px',
            fontSize: 13,
            background: 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          Apply Jobs
        </button>
      )}

      <button
        onClick={onOpenSettings}
        style={{
          padding: '6px 14px',
          fontSize: 13,
          background: 'var(--bg-hover)',
          color: 'var(--text-primary)',
          border: '1px solid var(--border)',
          borderRadius: 6,
          cursor: 'pointer',
        }}
      >
        Settings
      </button>
    </div>
  )
}
