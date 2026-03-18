import { useState } from 'react'
import type { Job } from '../../types'
import { openForReview, markApplied, skipJob, retryCoverLetter } from '../../api'
import { useJobsStore } from '../../store/jobsStore'
import { getJobCounts } from '../../api'

interface Props {
  job: Job
  showActions?: 'ready' | 'applying' | 'applied' | 'seen' | 'none'
}

export default function JobCard({ job, showActions = 'none' }: Props) {
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const { upsertJob, removeJob, setCounts } = useJobsStore()

  async function handleOpenReview() {
    setLoading(true)
    try {
      await openForReview(job.id)
      upsertJob({ ...job, status: 'applying' })
      const counts = await getJobCounts()
      setCounts(counts)
    } catch (err: any) {
      alert(`Failed to open review: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleMarkApplied() {
    setLoading(true)
    try {
      const updated = await markApplied(job.id)
      upsertJob(updated)
      const counts = await getJobCounts()
      setCounts(counts)
    } catch (err: any) {
      alert(`Failed to mark applied: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleRetry() {
    setLoading(true)
    try {
      await retryCoverLetter(job.id)
      // SSE will fire job_ready and counts_updated when done
    } catch (err: any) {
      alert(`Failed to retry: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function handleSkip() {
    if (!confirm(`Skip "${job.title}"?`)) return
    setLoading(true)
    try {
      await skipJob(job.id)
      removeJob(job.id)
      const counts = await getJobCounts()
      setCounts(counts)
    } catch (err: any) {
      alert(`Failed to skip: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      background: 'var(--bg-surface)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      padding: 16,
      marginBottom: 12,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <a
            href={job.job_url}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              fontSize: 15,
              fontWeight: 600,
              color: 'var(--accent)',
              textDecoration: 'none',
            }}
          >
            {job.title}
          </a>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4, display: 'flex', gap: 12 }}>
            {job.budget && <span>💰 {job.budget}</span>}
            {job.job_type && <span>📌 {job.job_type}</span>}
            {job.experience && <span>🎯 {job.experience}</span>}
            {job.client_name && <span>👤 {job.client_name}</span>}
          </div>
        </div>
        <StatusBadge status={job.status} />
      </div>

      {/* Skills */}
      {job.skills && job.skills.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {job.skills.map((s) => (
            <span key={s} style={{
              fontSize: 11,
              padding: '2px 8px',
              background: 'var(--accent-light)',
              color: 'var(--accent)',
              borderRadius: 12,
              fontWeight: 500,
            }}>
              {s}
            </span>
          ))}
        </div>
      )}

      {/* Description toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text-muted)',
          fontSize: 12,
          cursor: 'pointer',
          padding: '8px 0 0',
        }}
      >
        {expanded ? '▲ Hide description' : '▼ Show description'}
      </button>

      {expanded && (
        <div style={{
          marginTop: 8,
          fontSize: 13,
          color: 'var(--text-secondary)',
          lineHeight: 1.6,
          maxHeight: 200,
          overflowY: 'auto',
          background: 'var(--bg-hover)',
          padding: 10,
          borderRadius: 6,
        }}>
          {job.description || 'No description.'}
        </div>
      )}

      {/* Cover letter preview */}
      {job.cover_letter_text && expanded && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>
            Cover Letter
          </div>
          <div style={{
            fontSize: 12,
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            maxHeight: 150,
            overflowY: 'auto',
            background: 'var(--bg-hover)',
            padding: 10,
            borderRadius: 6,
          }}>
            {job.cover_letter_text}
          </div>
          <a
            href={`/cover-letters/${job.id}`}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 12, color: 'var(--accent)', marginTop: 4, display: 'inline-block' }}
          >
            Download PDF
          </a>
        </div>
      )}

      {/* Actions */}
      {showActions !== 'none' && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          {showActions === 'ready' && (
            <>
              <button
                onClick={handleOpenReview}
                disabled={loading}
                style={actionBtn('var(--accent)')}
              >
                {loading ? 'Opening...' : '→ Open for Review'}
              </button>
              <button onClick={handleSkip} disabled={loading} style={actionBtn('#6b7280')}>
                Skip
              </button>
            </>
          )}
          {showActions === 'applying' && (
            <>
              <button
                onClick={handleMarkApplied}
                disabled={loading}
                style={actionBtn('#22c55e')}
              >
                {loading ? 'Saving...' : '✓ Mark as Applied'}
              </button>
              <button onClick={handleSkip} disabled={loading} style={actionBtn('#6b7280')}>
                Skip
              </button>
            </>
          )}
          {showActions === 'applied' && (
            <span style={{ fontSize: 12, color: '#22c55e', fontWeight: 600 }}>
              Applied {job.applied_at ? `on ${new Date(job.applied_at).toLocaleDateString()}` : ''}
            </span>
          )}
          {showActions === 'seen' && (
            <>
              <button
                onClick={handleRetry}
                disabled={loading}
                style={actionBtn('#f59e0b')}
              >
                {loading ? 'Retrying...' : '↻ Retry Cover Letter'}
              </button>
              <button onClick={handleSkip} disabled={loading} style={actionBtn('#6b7280')}>
                Skip
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    seen: '#6b7280',
    ready: 'var(--accent)',
    applying: '#f59e0b',
    applied: '#22c55e',
    skipped: '#6b7280',
  }
  return (
    <span style={{
      fontSize: 11,
      fontWeight: 600,
      padding: '2px 8px',
      borderRadius: 10,
      background: colors[status] || '#6b7280',
      color: '#fff',
      flexShrink: 0,
    }}>
      {status}
    </span>
  )
}

function actionBtn(bg: string): React.CSSProperties {
  return {
    padding: '6px 14px',
    fontSize: 13,
    background: bg,
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontWeight: 500,
  }
}
