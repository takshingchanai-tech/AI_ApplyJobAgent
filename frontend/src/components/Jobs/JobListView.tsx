import { useEffect, useState } from 'react'
import type { JobStatus } from '../../types'
import { useJobsStore } from '../../store/jobsStore'
import { listJobs } from '../../api'
import JobCard from './JobCard'

interface Props {
  status: JobStatus
  title: string
  emptyMessage: string
}

export default function JobListView({ status, title, emptyMessage }: Props) {
  const { jobs, setJobs } = useJobsStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const filtered = jobs.filter((j) => {
    if (status === 'applied') return j.status === 'applied' || j.status === 'skipped'
    return j.status === status
  })

  useEffect(() => {
    setLoading(true)
    setError('')
    const queryStatus = status === 'applied' ? undefined : status
    listJobs(queryStatus)
      .then((fetched) => {
        // Merge fetched into store (don't replace everything)
        fetched.forEach((job) => useJobsStore.getState().upsertJob(job))
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [status])

  const actionType = status === 'ready' ? 'ready'
    : status === 'applying' ? 'applying'
    : status === 'applied' ? 'applied'
    : status === 'seen' ? 'seen'
    : 'none'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: 20, gap: 16, overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
          {title}
        </h2>
        <span style={{
          fontSize: 12,
          color: 'var(--text-muted)',
          background: 'var(--bg-hover)',
          padding: '2px 8px',
          borderRadius: 10,
        }}>
          {filtered.length}
        </span>
      </div>

      {error && (
        <div style={{ color: '#ef4444', fontSize: 13 }}>Error: {error}</div>
      )}

      {loading ? (
        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading...</div>
      ) : filtered.length === 0 ? (
        <div style={{
          color: 'var(--text-muted)',
          fontSize: 14,
          textAlign: 'center',
          marginTop: 60,
          fontStyle: 'italic',
        }}>
          {emptyMessage}
        </div>
      ) : (
        filtered.map((job) => (
          <JobCard key={job.id} job={job} showActions={actionType as any} />
        ))
      )}
    </div>
  )
}
