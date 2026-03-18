import { useJobsStore } from '../../store/jobsStore'
import type { View } from '../../types'

interface NavItem {
  view: View
  label: string
  icon: string
  badge?: number
}

interface Props {
  view: View
  onChangeView: (v: View) => void
}

export default function Sidebar({ view, onChangeView }: Props) {
  const counts = useJobsStore((s) => s.counts)

  const navItems: NavItem[] = [
    { view: 'activity', label: 'Activity', icon: '⚡' },
    { view: 'ready', label: 'Ready', icon: '📋', badge: counts.ready },
    { view: 'applying', label: 'Applying', icon: '🔄', badge: counts.applying },
    { view: 'applied', label: 'Applied', icon: '✅', badge: counts.past },
    { view: 'pending', label: 'Pending', icon: '⚠️', badge: counts.seen },
    { view: 'settings', label: 'Settings', icon: '⚙️' },
  ]

  return (
    <nav style={{
      width: 200,
      background: 'var(--bg-surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      padding: '20px 0',
      flexShrink: 0,
    }}>
      <div style={{
        padding: '0 20px 20px',
        borderBottom: '1px solid var(--border)',
        marginBottom: 12,
      }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>Upwork Agent</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>Job Apply</div>
      </div>

      {navItems.map(({ view: v, label, icon, badge }) => (
        <button
          key={v}
          onClick={() => onChangeView(v)}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 20px',
            fontSize: 14,
            fontWeight: view === v ? 600 : 400,
            color: view === v ? 'var(--text-primary)' : 'var(--text-secondary)',
            background: view === v ? 'var(--accent-light)' : 'transparent',
            borderLeft: view === v ? '3px solid var(--accent)' : '3px solid transparent',
            border: 'none',
            transition: 'all 0.15s',
            textAlign: 'left',
            width: '100%',
            cursor: 'pointer',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>{icon}</span>
            <span>{label}</span>
          </span>
          {badge !== undefined && badge > 0 && (
            <span style={{
              background: 'var(--accent)',
              color: '#fff',
              fontSize: 11,
              fontWeight: 700,
              padding: '1px 6px',
              borderRadius: 10,
              minWidth: 18,
              textAlign: 'center',
            }}>
              {badge}
            </span>
          )}
        </button>
      ))}
    </nav>
  )
}
